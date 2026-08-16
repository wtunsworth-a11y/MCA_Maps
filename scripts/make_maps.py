#!/usr/bin/env python3
"""Stage 2 — present the data as maps.

Renders every layer found in data/raw as a static PNG and an interactive HTML
map, then a combined HTML map stacking all layers with a layer switcher.

Usage:
    python scripts/make_maps.py
    python scripts/make_maps.py --only survey_2026
    python scripts/make_maps.py --colour-by status
    python scripts/make_maps.py --out-dir output --no-static
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402

PALETTE = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed",
           "#0891b2", "#be185d", "#4d7c0f", "#b45309", "#1e40af"]


# --------------------------------------------------------------------------
# Static maps
# --------------------------------------------------------------------------

def render_static(layer: dataio.Layer, out_dir: Path,
                  colour_by: str | None) -> Path:
    """Write a PNG of one layer, with a tile basemap underneath if available."""
    gdf = layer.gdf.to_crs(dataio.WEB_MERCATOR)
    fig, ax = plt.subplots(figsize=(11, 9), dpi=150)

    kind = layer.qgis_geometry
    shared = {"ax": ax, "alpha": 0.8}
    if colour_by and colour_by in gdf.columns:
        shared |= {"column": colour_by, "legend": True, "cmap": "viridis",
                   "legend_kwds": {"fontsize": 8, "loc": "lower right"}}
    else:
        shared |= {"color": PALETTE[0]}

    if kind == "Point":
        gdf.plot(markersize=14, edgecolor="white", linewidth=0.4, **shared)
    elif kind == "Line":
        gdf.plot(linewidth=1.0, **shared)
    else:
        gdf.plot(edgecolor="#1e3a8a", linewidth=0.5, **shared)

    _add_basemap(ax, gdf)
    ax.set_axis_off()
    ax.set_title(f"{layer.name}  ({len(gdf):,} features)", fontsize=13, pad=12)
    fig.tight_layout()

    out_path = out_dir / f"{layer.name}.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


_basemap_warned = False


def _add_basemap(ax, gdf) -> None:
    """Best-effort tile basemap; the map still renders fine without one."""
    global _basemap_warned
    try:
        import contextily as cx
    except ImportError:
        if not _basemap_warned:
            print("  (no basemap: pip install contextily)")
            _basemap_warned = True
        return
    try:
        cx.add_basemap(ax, crs=gdf.crs, source=cx.providers.CartoDB.Positron,
                       attribution_size=6)
    except Exception as exc:
        if not _basemap_warned:
            print(f"  (no basemap: tiles unreachable — {type(exc).__name__})")
            _basemap_warned = True


# --------------------------------------------------------------------------
# Interactive maps
# --------------------------------------------------------------------------

def render_interactive(layers: list[dataio.Layer], out_path: Path,
                       title: str) -> Path:
    """Write a folium map holding one toggleable overlay per layer."""
    import folium

    minx, miny, maxx, maxy = dataio.combined_bounds(layers)
    fmap = folium.Map(location=[(miny + maxy) / 2, (minx + maxx) / 2],
                      zoom_start=6, tiles="CartoDB positron")
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(fmap)

    for index, layer in enumerate(layers):
        colour = PALETTE[index % len(PALETTE)]
        gdf = _json_safe(layer.gdf)
        fields = [c for c in gdf.columns if c != "geometry"][:10]
        folium.GeoJson(
            gdf.to_json(),
            name=f"{layer.name} ({len(gdf):,})",
            marker=folium.CircleMarker(radius=4, fill=True, fill_opacity=0.7,
                                       color=colour, fill_color=colour),
            style_function=lambda _f, c=colour: {
                "color": c, "weight": 1.5, "fillColor": c, "fillOpacity": 0.35,
            },
            highlight_function=lambda _f: {"weight": 3, "fillOpacity": 0.6},
            tooltip=folium.GeoJsonTooltip(fields=fields) if fields else None,
            popup=folium.GeoJsonPopup(fields=fields) if fields else None,
        ).add_to(fmap)

    folium.LayerControl(collapsed=False).add_to(fmap)
    fmap.fit_bounds([[miny, minx], [maxy, maxx]])
    fmap.get_root().html.add_child(folium.Element(
        "<h3 style='font-family:system-ui;margin:8px 12px;font-weight:600'>"
        f"{title}</h3>"
    ))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(out_path))
    return out_path


def render_zone_map(track_layers: list[dataio.Layer], out_path: Path,
                    polygons_gpkg: Path | None = None,
                    boundary_path: Path | None = None,
                    title: str = "MCA clan boundaries") -> Path:
    """An interactive map with every zone switchable on and off.

    Tracks and mapped areas are separate overlays per zone, so a zone can be
    shown as lines, as area, or both. Areas are drawn under the tracks and the
    MCA boundary under everything.
    """
    import folium
    import geopandas as gpd

    minx, miny, maxx, maxy = dataio.combined_bounds(track_layers)
    fmap = folium.Map(location=[(miny + maxy) / 2, (minx + maxx) / 2],
                      zoom_start=10, tiles="CartoDB positron",
                      control_scale=True)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap",
                     show=False).add_to(fmap)

    zone_colour = {layer.name: PALETTE[i % len(PALETTE)]
                   for i, layer in enumerate(track_layers)}

    if boundary_path and Path(boundary_path).exists():
        boundary = gpd.read_file(boundary_path).to_crs(dataio.WGS84)
        folium.GeoJson(
            boundary.to_json(), name="MCA boundary",
            style_function=lambda _f: {"color": "#475569", "weight": 2,
                                       "fillColor": "#94a3b8",
                                       "fillOpacity": 0.10},
        ).add_to(fmap)

    if polygons_gpkg and Path(polygons_gpkg).exists():
        try:
            areas = gpd.read_file(polygons_gpkg,
                                  layer="survey_polygons").to_crs(dataio.WGS84)
        except Exception:
            areas = None
        if areas is not None and not areas.empty:
            for zone, group in areas.groupby("zone", sort=True):
                colour = zone_colour.get(dataio.safe_name(str(zone)), PALETTE[0])
                fields = [c for c in ("clan", "custodian", "basis", "area_ha",
                                      "gap_pct", "walked_km")
                          if c in group.columns]
                folium.GeoJson(
                    _json_safe(group).to_json(),
                    name=f"{zone} — area ({len(group)})",
                    show=False,
                    style_function=lambda f, c=colour: {
                        "color": c, "weight": 1,
                        "fillColor": c,
                        "fillOpacity": 0.45 if f["properties"].get("basis")
                        == "surveyed" else 0.20,
                        "dashArray": "" if f["properties"].get("basis")
                        == "surveyed" else "4,3",
                    },
                    tooltip=folium.GeoJsonTooltip(fields=fields),
                    popup=folium.GeoJsonPopup(fields=fields),
                ).add_to(fmap)

    for layer in track_layers:
        colour = zone_colour[layer.name]
        gdf = _json_safe(layer.gdf)
        fields = [c for c in ("zone", "clan", "custodian", "feature_type",
                              "survey_date", "name")
                  if c in gdf.columns]
        folium.GeoJson(
            gdf.to_json(),
            name=f"{layer.name.replace('_', ' ')} — tracks ({len(gdf):,})",
            style_function=lambda _f, c=colour: {"color": c, "weight": 2},
            highlight_function=lambda _f: {"weight": 5},
            tooltip=folium.GeoJsonTooltip(fields=fields) if fields else None,
            popup=folium.GeoJsonPopup(fields=fields) if fields else None,
        ).add_to(fmap)

    folium.LayerControl(collapsed=False).add_to(fmap)
    fmap.fit_bounds([[miny, minx], [maxy, maxx]])

    legend = "".join(
        f"<div style='display:flex;align-items:center;gap:6px;margin:2px 0'>"
        f"<span style='width:14px;height:3px;background:{c};display:inline-block'></span>"
        f"<span>{n.replace('_', ' ')}</span></div>"
        for n, c in zone_colour.items())
    fmap.get_root().html.add_child(folium.Element(
        "<div style=\"position:fixed;bottom:22px;left:12px;z-index:9999;"
        "background:rgba(255,255,255,.94);padding:10px 12px;border-radius:6px;"
        "font:12px/1.45 system-ui;box-shadow:0 1px 4px rgba(0,0,0,.25)\">"
        f"<div style='font-weight:600;margin-bottom:4px'>{title}</div>{legend}"
        "<div style='margin-top:6px;color:#475569'>Solid fill = surveyed<br>"
        "Hatched fill = inferred</div></div>"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(out_path))
    return out_path


def _json_safe(gdf, precision: int | None = 6):
    """Cast dates and objects to strings so folium can serialise them.

    Coordinates are also rounded, by default to 6 decimal places — about 11 cm
    at this latitude, far finer than a handheld GPS fix. Full float precision
    would roughly treble the size of the HTML for no visible gain.
    """
    out = gdf.copy()
    for column in out.columns:
        if column != "geometry" and not pd.api.types.is_numeric_dtype(out[column]):
            out[column] = out[column].astype(str)
    if precision is not None:
        import shapely
        out["geometry"] = shapely.set_precision(
            out.geometry.values, 10 ** -precision)
    return out


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    dataio.add_common_args(parser)
    parser.add_argument("--out-dir", type=Path, default=dataio.OUT_DIR,
                        help="where rendered maps are written")
    parser.add_argument("--colour-by", default=None,
                        help="attribute column to shade the static maps by")
    parser.add_argument("--no-static", action="store_true",
                        help="skip the PNG renders")
    parser.add_argument("--no-combined", action="store_true",
                        help="skip the all-layers combined map")
    parser.add_argument("--separate", action="store_true",
                        help="render one map per source file instead of "
                             "merging them into a single attributed layer")
    parser.add_argument("--group-by", default="zone",
                        help="attribute used to split the merged layer "
                             "(default: zone)")
    parser.add_argument("--smoothed", nargs="?", const=str(
                            dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg"),
                        default=None,
                        help="map the smoothed tracks instead of the raw "
                             "archives")
    parser.add_argument("--layer", default="tracks_smoothed",
                        help="layer to read when --smoothed is used")
    args = parser.parse_args(argv)

    if args.smoothed:
        prepared = dataio.load_prepared(Path(args.smoothed), args.layer)
        if prepared is None:
            print(f"No smoothed data at {args.smoothed} — "
                  "run scripts/smooth_tracks.py first.")
            return 1
        layers = dataio.split_by(prepared, args.group_by)
        args.colour_by = args.colour_by or args.group_by
        args.out_dir.mkdir(parents=True, exist_ok=True)
        print(f"Mapping smoothed tracks ({len(prepared.gdf):,} features) "
              f"to {args.out_dir}")
        if not args.no_static:
            print(f"  {render_static(prepared, args.out_dir, args.colour_by).name}")
        zone_map = render_zone_map(
            layers, args.out_dir / "zones_interactive.html",
            polygons_gpkg=dataio.SMOOTHED_DIR / "mca_polygons.gpkg",
            boundary_path=dataio.MCA_BOUNDARY,
            title="MCA clan boundaries by zone")
        print(f"  {zone_map.name}")
        return 0

    if not args.raw_dir.exists():
        print(f"No raw data directory at {args.raw_dir}")
        return 1

    sources = dataio.load_from_args(args)
    if not sources:
        print(f"\nNothing to map yet — no readable data under {args.raw_dir}.\n"
              "Copy your zip archives in there and re-run this script.")
        return 0

    if args.separate:
        layers, overview = sources, None
    else:
        overview = dataio.combine(sources)
        layers = dataio.split_by(overview, args.group_by)
        args.colour_by = args.colour_by or args.group_by
        print(f"\nMerged {len(sources)} source layer(s) into "
              f"{len(layers)} by {args.group_by}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nWriting maps to {args.out_dir}")

    if overview is not None:
        if not args.no_static:
            print(f"  {render_static(overview, args.out_dir, args.colour_by).name}")
        print(f"  {render_interactive(layers, args.out_dir / 'overview.html', 'All zones').name}")

    for layer in layers:
        if not args.no_static:
            print(f"  {render_static(layer, args.out_dir, args.colour_by).name}")
        html = render_interactive([layer], args.out_dir / f"{layer.name}.html",
                                  layer.name)
        print(f"  {html.name}")

    if overview is None and len(layers) > 1 and not args.no_combined:
        combined = render_interactive(layers, args.out_dir / "all_layers.html",
                                      "All layers")
        print(f"  {combined.name}")

    print("\nNext: python scripts/export_qgis.py  → GeoPackage + QGIS project")
    return 0


if __name__ == "__main__":
    sys.exit(main())
