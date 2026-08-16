#!/usr/bin/env python3
"""Stage 3 — hand the data over to QGIS.

Writes every layer into a single GeoPackage, then generates a QGIS project
file (.qgs) that loads those layers, styles them by geometry type, adds an
OpenStreetMap basemap and zooms to the data. Double-click the .qgs and
everything is already set up.

Targets QGIS 3.28 LTR (Firenze); the format is forward-compatible with newer
releases.

Usage:
    python scripts/export_qgis.py
    python scripts/export_qgis.py --gpkg data/processed/mca_maps.gpkg
    python scripts/export_qgis.py --no-basemap --qgis-version 3.34.0-Prizren
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402

DEFAULT_QGIS_VERSION = "3.28.12-Firenze"

PALETTE = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed",
           "#0891b2", "#be185d", "#4d7c0f", "#b45309", "#1e40af"]

OSM_XYZ = ("type=xyz&url=https://tile.openstreetmap.org/"
           "%7Bz%7D/%7Bx%7D/%7By%7D.png&zmax=19&zmin=0")

CRS_BLOCKS = {
    "EPSG:4326": """<spatialrefsys nativeFormat="Wkt">
      <wkt>GEOGCRS["WGS 84",ENSEMBLE["World Geodetic System 1984 ensemble",MEMBER["World Geodetic System 1984 (Transit)"],MEMBER["World Geodetic System 1984 (G730)"],MEMBER["World Geodetic System 1984 (G873)"],MEMBER["World Geodetic System 1984 (G1150)"],MEMBER["World Geodetic System 1984 (G1674)"],MEMBER["World Geodetic System 1984 (G1762)"],MEMBER["World Geodetic System 1984 (G2139)"],ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]],ENSEMBLEACCURACY[2.0]],PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]],CS[ellipsoidal,2],AXIS["geodetic latitude (Lat)",north,ORDER[1],ANGLEUNIT["degree",0.0174532925199433]],AXIS["geodetic longitude (Lon)",east,ORDER[2],ANGLEUNIT["degree",0.0174532925199433]],USAGE[SCOPE["Horizontal component of 3D system."],AREA["World."],BBOX[-90,-180,90,180]],ID["EPSG",4326]]</wkt>
      <proj4>+proj=longlat +datum=WGS84 +no_defs</proj4>
      <srsid>3452</srsid>
      <srid>4326</srid>
      <authid>EPSG:4326</authid>
      <description>WGS 84</description>
      <projectionacronym>longlat</projectionacronym>
      <ellipsoidacronym>EPSG:7030</ellipsoidacronym>
      <geographicflag>true</geographicflag>
    </spatialrefsys>""",
    "EPSG:3857": """<spatialrefsys nativeFormat="Wkt">
      <wkt>PROJCRS["WGS 84 / Pseudo-Mercator",BASEGEOGCRS["WGS 84",ENSEMBLE["World Geodetic System 1984 ensemble",MEMBER["World Geodetic System 1984 (Transit)"],ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]],ENSEMBLEACCURACY[2.0]],PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]],ID["EPSG",4326]],CONVERSION["Popular Visualisation Pseudo-Mercator",METHOD["Popular Visualisation Pseudo Mercator",ID["EPSG",1024]],PARAMETER["Latitude of natural origin",0,ANGLEUNIT["degree",0.0174532925199433],ID["EPSG",8801]],PARAMETER["Longitude of natural origin",0,ANGLEUNIT["degree",0.0174532925199433],ID["EPSG",8802]],PARAMETER["False easting",0,LENGTHUNIT["metre",1],ID["EPSG",8806]],PARAMETER["False northing",0,LENGTHUNIT["metre",1],ID["EPSG",8807]]],CS[Cartesian,2],AXIS["easting (X)",east,ORDER[1],LENGTHUNIT["metre",1]],AXIS["northing (Y)",north,ORDER[2],LENGTHUNIT["metre",1]],ID["EPSG",3857]]</wkt>
      <proj4>+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +k=1 +units=m +nadgrids=@null +wktext +no_defs</proj4>
      <srsid>3857</srsid>
      <srid>3857</srid>
      <authid>EPSG:3857</authid>
      <description>WGS 84 / Pseudo-Mercator</description>
      <projectionacronym>merc</projectionacronym>
      <ellipsoidacronym>EPSG:7030</ellipsoidacronym>
      <geographicflag>false</geographicflag>
    </spatialrefsys>""",
}


# --------------------------------------------------------------------------
# GeoPackage
# --------------------------------------------------------------------------

def write_geopackage(layers: list[dataio.Layer], gpkg_path: Path) -> Path:
    """Write every layer into one GeoPackage, replacing any previous file."""
    gpkg_path.parent.mkdir(parents=True, exist_ok=True)
    if gpkg_path.exists():
        gpkg_path.unlink()

    for layer in layers:
        gdf = _gpkg_safe(layer.gdf)
        gdf.to_file(gpkg_path, layer=layer.name, driver="GPKG")
        print(f"  {gpkg_path.name} ← {layer.name} ({len(gdf):,} features)")
    return gpkg_path


def _gpkg_safe(gdf):
    """Coerce columns OGR cannot store (lists, dicts, mixed objects) to text."""
    out = gdf.copy()
    for column in out.columns:
        if column == "geometry":
            continue
        series = out[column]
        if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
            continue
        if pd.api.types.is_datetime64_any_dtype(series):
            continue
        out[column] = series.astype(str).where(series.notna(), None)
    return out


# --------------------------------------------------------------------------
# QGIS project file
# --------------------------------------------------------------------------

def build_project(layers: list[dataio.Layer], gpkg_path: Path,
                  project_path: Path, qgis_version: str,
                  basemap: bool, title: str) -> Path:
    """Generate a .qgs referencing the GeoPackage layers, zoomed to the data."""
    relative_gpkg = _relative_to(gpkg_path, project_path.parent)
    entries = [
        {
            "id": f"{layer.name}_{index:03d}",
            "name": layer.name,
            "source": f"{relative_gpkg}|layername={layer.name}",
            "geometry": layer.qgis_geometry,
            "colour": PALETTE[index % len(PALETTE)],
        }
        for index, layer in enumerate(layers)
    ]

    minx, miny, maxx, maxy = dataio.combined_bounds(layers)
    pad_x = (maxx - minx) * 0.05
    pad_y = (maxy - miny) * 0.05
    extent = (minx - pad_x, miny - pad_y, maxx + pad_x, maxy + pad_y)

    # QGIS draws the tree top-down, so the basemap belongs at the bottom.
    tree = "\n".join(_tree_entry(e["id"], e["name"], e["source"]) for e in entries)
    maplayers = "\n".join(_vector_maplayer(e) for e in entries)
    order = "\n".join(f'    <layer id={quoteattr(e["id"])}/>' for e in entries)

    if basemap:
        tree += "\n" + _tree_entry("osm_basemap", "OpenStreetMap", OSM_XYZ,
                                   provider="wms")
        maplayers += "\n" + _raster_maplayer()
        order += '\n    <layer id="osm_basemap"/>'

    project = f"""<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis projectname={quoteattr(title)} version={quoteattr(qgis_version)}>
  <homePath path=""/>
  <title>{escape(title)}</title>
  <projectCrs>
    {CRS_BLOCKS["EPSG:4326"]}
  </projectCrs>
  <layer-tree-group>
    <customproperties/>
{tree}
    <custom-order enabled="0"/>
  </layer-tree-group>
  <mapcanvas name="theMapCanvas" annotationsVisible="1">
    <units>degrees</units>
    <extent>
      <xmin>{extent[0]:.10f}</xmin>
      <ymin>{extent[1]:.10f}</ymin>
      <xmax>{extent[2]:.10f}</xmax>
      <ymax>{extent[3]:.10f}</ymax>
    </extent>
    <rotation>0</rotation>
    <destinationsrs>
      {CRS_BLOCKS["EPSG:4326"]}
    </destinationsrs>
  </mapcanvas>
  <projectlayers>
{maplayers}
  </projectlayers>
  <layerorder>
{order}
  </layerorder>
  <properties>
    <Gui>
      <CanvasColour type="QString">#ffffff</CanvasColour>
    </Gui>
    <Measure>
      <Ellipsoid type="QString">EPSG:7030</Ellipsoid>
    </Measure>
  </properties>
</qgis>
"""
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text(project, encoding="utf-8")
    return project_path


def _tree_entry(layer_id: str, name: str, source: str,
                provider: str = "ogr") -> str:
    return (f'    <layer-tree-layer id={quoteattr(layer_id)} '
            f'name={quoteattr(name)} source={quoteattr(source)} '
            f'providerKey={quoteattr(provider)} checked="Qt::Checked" '
            f'expanded="1" patch_size="-1,-1"><customproperties/>'
            f'</layer-tree-layer>')


def _vector_maplayer(entry: dict) -> str:
    return f"""    <maplayer type="vector" geometry={quoteattr(entry["geometry"])} hasScaleBasedVisibilityFlag="0" readOnly="0">
      <id>{escape(entry["id"])}</id>
      <datasource>{escape(entry["source"])}</datasource>
      <layername>{escape(entry["name"])}</layername>
      <srs>
        {CRS_BLOCKS["EPSG:4326"]}
      </srs>
      <provider encoding="UTF-8">ogr</provider>
      {_renderer(entry["geometry"], entry["colour"])}
      <blendMode>0</blendMode>
      <layerOpacity>1</layerOpacity>
    </maplayer>"""


def _renderer(geometry: str, colour: str) -> str:
    """A single-symbol renderer appropriate to the geometry family."""
    rgb = _to_rgba(colour)
    if geometry == "Point":
        symbol_type, layer_class = "marker", "SimpleMarker"
        options = {
            "name": "circle", "color": rgb, "outline_color": "255,255,255,255",
            "outline_width": "0.2", "size": "2.4", "size_unit": "MM",
            "outline_width_unit": "MM", "joinstyle": "bevel",
        }
    elif geometry == "Line":
        symbol_type, layer_class = "line", "SimpleLine"
        options = {
            "line_color": rgb, "line_width": "0.5", "line_width_unit": "MM",
            "line_style": "solid", "capstyle": "round", "joinstyle": "round",
        }
    else:
        symbol_type, layer_class = "fill", "SimpleFill"
        options = {
            "color": _to_rgba(colour, alpha=90), "style": "solid",
            "outline_color": rgb, "outline_width": "0.3",
            "outline_width_unit": "MM", "outline_style": "solid",
            "joinstyle": "bevel",
        }

    props = "\n".join(
        f'              <Option name={quoteattr(k)} type="QString" '
        f'value={quoteattr(v)}/>'
        for k, v in options.items()
    )
    return f"""<renderer-v2 type="singleSymbol" forceraster="0" symbollevels="0" enableorderby="0">
        <symbols>
          <symbol type={quoteattr(symbol_type)} name="0" alpha="1" force_rhr="0" frame_rate="10" is_animated="0" clip_to_extent="1">
            <layer class={quoteattr(layer_class)} enabled="1" pass="0" locked="0">
              <Option type="Map">
{props}
              </Option>
            </layer>
          </symbol>
        </symbols>
      </renderer-v2>"""


def _raster_maplayer() -> str:
    return f"""    <maplayer type="raster" hasScaleBasedVisibilityFlag="0">
      <id>osm_basemap</id>
      <datasource>{escape(OSM_XYZ)}</datasource>
      <layername>OpenStreetMap</layername>
      <srs>
        {CRS_BLOCKS["EPSG:3857"]}
      </srs>
      <provider>wms</provider>
      <pipe>
        <rasterrenderer type="singlebandcolordata" band="1" opacity="1" alphaBand="-1" nodataColor="">
          <rasterTransparency/>
        </rasterrenderer>
        <brightnesscontrast brightness="0" contrast="0" gamma="1"/>
        <huesaturation saturation="0" grayscaleMode="0" colorizeOn="0"/>
        <rasterresampler maxOversampling="2"/>
      </pipe>
      <blendMode>0</blendMode>
    </maplayer>"""


def _to_rgba(hex_colour: str, alpha: int = 255) -> str:
    value = hex_colour.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return f"{r},{g},{b},{alpha}"


def _relative_to(target: Path, start: Path) -> str:
    """A relative path if one is expressible, otherwise an absolute one."""
    try:
        import os
        return "./" + os.path.relpath(target, start).replace("\\", "/")
    except ValueError:
        return str(target)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    dataio.add_common_args(parser)
    parser.add_argument("--gpkg", type=Path, default=dataio.GPKG_PATH,
                        help="GeoPackage to write")
    parser.add_argument("--project", type=Path, default=None,
                        help="QGIS project file to write "
                             "(defaults to alongside the GeoPackage)")
    parser.add_argument("--title", default="MCA Maps", help="project title")
    parser.add_argument("--qgis-version", default=DEFAULT_QGIS_VERSION,
                        help="QGIS version stamped into the project file")
    parser.add_argument("--no-basemap", action="store_true",
                        help="omit the OpenStreetMap XYZ basemap layer")
    args = parser.parse_args(argv)

    if not args.raw_dir.exists():
        print(f"No raw data directory at {args.raw_dir}")
        return 1

    layers = dataio.load_from_args(args)
    if not layers:
        print(f"\nNothing to export — no readable data under {args.raw_dir}.")
        return 0

    project_path = args.project or args.gpkg.with_suffix(".qgs")

    print(f"\nWriting GeoPackage to {args.gpkg}")
    write_geopackage(layers, args.gpkg)

    build_project(layers, args.gpkg, project_path, args.qgis_version,
                  basemap=not args.no_basemap, title=args.title)
    print(f"\nWrote QGIS project: {project_path}")
    print(f"Open it in QGIS {args.qgis_version.split('-')[0]} or newer — "
          f"{len(layers)} layer(s) load styled and zoomed to the data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
