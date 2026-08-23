#!/usr/bin/env python3
"""Assemble everything the written reports quote, into one set of JSON files.

The Word documents are built from these files and nothing else, so a figure
in a document and a figure in a map cannot drift apart: both come from the
same run of the pipeline. Re-run this after any new data drop and the
documents rebuild with the new numbers, the new clans and the new maps, with
no editing.

Writes into output/report/:

* `summary.json`   — the headline figures, by zone and overall
* `clandata.json`  — one record per clan: stewards, closure, overlaps, queries
* `context.json`   — version, date, provenance, the parameters in force

Usage:
    python scripts/report_data.py
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import closure  # noqa: E402
import dataio  # noqa: E402
import polygons as polygon_tools  # noqa: E402
import smooth_tracks  # noqa: E402
import stewards as steward_tools  # noqa: E402

VERSION_FILE = dataio.REPO_ROOT / "docs" / "VERSION"
CHANGELOG_FILE = dataio.REPO_ROOT / "docs" / "CHANGELOG.md"
FIELD_NOTES_FILE = (dataio.REPO_ROOT / "data" / "reference"
                    / "field_notes.json")


def field_notes() -> dict:
    """What the field has told us, keyed by survey unit.

    Accounts, not measurements. They are reproduced on the clan's page and in
    the clan's GPX, and they change no geometry and no figure — a river named
    as a boundary is knowledge the GPS cannot supply and must not be turned
    into a line by this pipeline.
    """
    if not FIELD_NOTES_FILE.exists():
        return {}
    try:
        stored = json.loads(FIELD_NOTES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {k: v for k, v in stored.items() if not k.startswith("_")}


def standing_notes() -> dict:
    """Field advice that applies everywhere, not to one clan.

    Kept apart from the per-clan notes because it constrains what the pipeline
    may ask for: a rule like "large rivers cannot reasonably be walked" has to
    reach the query generator, not just the page.
    """
    if not FIELD_NOTES_FILE.exists():
        return {}
    try:
        return json.loads(
            FIELD_NOTES_FILE.read_text(encoding="utf-8")).get("_standing", {})
    except Exception:
        return {}


def changes_since(version: str) -> list[str]:
    """The bullets under this version's heading in docs/CHANGELOG.md.

    Printed in the document itself, so a reader holding an earlier copy can
    see what moved without diffing two Word files.
    """
    if not CHANGELOG_FILE.exists():
        return []
    wanted = f"## {version}"
    collecting, bullets, current = False, [], ""
    for line in CHANGELOG_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if collecting:
                break
            collecting = line.strip() == wanted
            continue
        if not collecting:
            continue
        if line.startswith("- "):
            if current:
                bullets.append(current)
            current = line[2:].strip()
        elif line.strip() and current:
            current += " " + line.strip()
        elif not line.strip() and current:
            bullets.append(current)
            current = ""
    if current:
        bullets.append(current)
    # These go into Word as plain runs, so Markdown emphasis would show up as
    # literal asterisks and backticks on the page.
    return [re.sub(r"\*\*|`", "", line) for line in bullets]


def _json(value):
    """pandas NA and numpy scalars, made safe for json.dump.

    Used both to clean values on the way in and as json's `default` hook, so
    it must never hand back something json cannot encode — returning the value
    unchanged there sends json round the same object forever.
    """
    if value is None:
        return None
    try:
        if not isinstance(value, (list, tuple, dict)) and pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (pd.Timestamp, date)):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, (str, int, bool, list, dict)):
        return value
    return str(value)


def gpx_index(gpx_dir: Path) -> dict:
    """Each clan's GPX file and how many gaps it marks, read back from it.

    Read out of the files themselves rather than recomputed, so the document
    can only ever name a file that exists and a gap count that is really in
    it.
    """
    import re

    out = {}
    for path in sorted(gpx_dir.glob("*.gpx")):
        text = path.read_text(encoding="utf-8")
        out[path.stem] = {
            "file": path.name,
            "gaps": len(re.findall(r"<name>GAP \d+ OF \d+ START</name>", text)),
            "km": round(sum(float(m) for m in re.findall(
                r"- NOT WALKED - ([\d.]+) km</name>", text)), 2),
        }
    return out


def parcel_count(geometry) -> int:
    """How many separate pieces of land a polygon describes."""
    if geometry is None or geometry.is_empty:
        return 0
    return len(getattr(geometry, "geoms", [geometry]))


def gather(tracks_path: Path, polygons_path: Path, clans_dir: Path,
           stewards_dir: Path, tolerance: float,
           gpx_dir: Path | None = None) -> dict:
    tracks = gpd.read_file(tracks_path,
                           layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
    surveys = gpd.read_file(polygons_path,
                            layer="survey_polygons").to_crs(dataio.METRIC_CRS)
    clan_polygons = gpd.read_file(polygons_path,
                                  layer="clan_polygons").to_crs(dataio.METRIC_CRS)

    tracks["_unit"] = dataio.survey_group(tracks)
    surveys["_unit"] = surveys["source_name"]
    named = tracks[tracks.clan.astype(str).str.strip() != ""]

    closures = closure.analyse_all(tracks, closure.DEFAULT_TOLERANCE_M,
                                   closure.DEFAULT_THRESHOLD)
    closures = closures.set_index("source_name")

    overlaps = polygon_tools.overlaps(clan_polygons, "clan", tolerance)
    agreed = polygon_tools.shared_lines(tracks, tolerance)

    gpx = gpx_index(gpx_dir) if gpx_dir and gpx_dir.exists() else {}
    notes = field_notes()

    joining = _read_csv(clans_dir / "joining_effect.csv")
    steward_table = _read_csv(stewards_dir / "stewards.csv")
    steward_days = _read_csv(stewards_dir / "steward_days.csv")

    # ---- headline ----------------------------------------------------
    boundary_only = tracks[tracks.feature_type == smooth_tracks.BOUNDARY_TYPE]
    spurs = sum(smooth_tracks.spur_length(group) for _, group
                in boundary_only.groupby("source_name"))
    surveyed = surveys[surveys.basis == "surveyed"]
    inferred = surveys[surveys.basis == "inferred"]
    mca = dataio.load_boundary()
    try:
        bridge_km = gpd.read_file(polygons_path, layer="inferred_bridges") \
            .to_crs(dataio.METRIC_CRS).length.sum() / 1000
    except Exception:
        bridge_km = 0.0

    strict_pieces, wide_pieces, per_clan = [], [], []
    for _, row in clan_polygons.iterrows():
        others = unary_union([g for name, g in zip(clan_polygons.clan,
                                                   clan_polygons.geometry)
                              if name != row.clan])
        shared = row.geometry.intersection(others)
        wide = polygon_tools.beyond_tolerance(shared, tolerance)
        if shared.area > 0:
            strict_pieces.append(shared)
        if wide.area > 0:
            wide_pieces.append(wide)
        per_clan.append({
            "clan": row.clan,
            "area_ha": round(row.geometry.area / 1e4, 1),
            "contested_ha": round(shared.area / 1e4, 1),
            "beyond_tol_ha": round(wide.area / 1e4, 1),
            "pct_contested": round(shared.area / row.geometry.area * 100, 1),
            "pct_beyond_tol": round(wide.area / row.geometry.area * 100, 1),
        })
    contested = pd.DataFrame(per_clan)

    zones = []
    for zone, group in tracks.groupby("zone"):
        zone_polys = surveys[surveys.zone == zone]
        zone_boundary = group[group.feature_type == smooth_tracks.BOUNDARY_TYPE]
        zone_spurs = sum(smooth_tracks.spur_length(part) for _, part
                         in zone_boundary.groupby("source_name"))
        zones.append({
            "zone": zone,
            "clans": int(group[group.clan.astype(str).str.strip() != ""]
                         .clan.nunique()),
            "stewards": int(group.steward.nunique()),
            "surveys": int(group.source_name.nunique()),
            "walked_km": round(group.geometry.length.sum() / 1000, 1),
            "boundary_km": round((zone_boundary.geometry.length.sum()
                                  - zone_spurs) / 1000, 1),
            "area_ha": round(zone_polys.area_ha.sum(), 0),
        })

    multi_parcel = [
        {"clan": row.clan, "parcels": parcel_count(row.geometry),
         "area_ha": round(row.geometry.area / 1e4, 1)}
        for _, row in clan_polygons.iterrows()
        if parcel_count(row.geometry) > 1]

    dated_days = steward_days[steward_days.date.notna()] \
        if not steward_days.empty else steward_days

    summary = {
        "clans": int(named.clan.nunique()),
        "stewards": int(tracks.steward.nunique()),
        "surveys": int(tracks.source_name.nunique()),
        "units": int(len(surveys)),
        "tracks": int(len(tracks)),
        "walked_km": round(tracks.geometry.length.sum() / 1000, 1),
        "boundary_km": round((boundary_only.geometry.length.sum() - spurs)
                             / 1000, 1),
        "surveyed_n": int(len(surveyed)),
        "inferred_n": int(len(inferred)),
        "surveyed_ha": round(surveyed.area_ha.sum(), 0),
        "inferred_ha": round(inferred.area_ha.sum(), 0),
        "total_ha": round(surveys.area_ha.sum(), 0),
        "bridge_km": round(bridge_km, 1),
        "outline_km": round(surveys.geometry.length.sum() / 1000, 1),
        "footprint_ha": round(unary_union(list(clan_polygons.geometry)).area
                              / 1e4, 0),
        "mca_ha": round(mca.area / 1e4, 0) if mca is not None else None,
        "clans_mapped": int(len(clan_polygons)),
        "clans_overlap": int((contested.contested_ha > 0).sum()),
        "clans_overlap_beyond_tol": int((contested.beyond_tol_ha > 0).sum()),
        "contested_ha": round(unary_union(strict_pieces).area / 1e4, 0)
        if strict_pieces else 0,
        "contested_beyond_tol_ha": round(unary_union(wide_pieces).area / 1e4, 0)
        if wide_pieces else 0,
        "overlap_pairs": int(len(overlaps)),
        "overlap_pairs_beyond_tol": int((overlaps.verdict == "overlap").sum())
        if not overlaps.empty else 0,
        "overlap_tolerance_m": tolerance,
        "clans_multi_parcel": len(multi_parcel),
        "multi_parcel": multi_parcel,
        "shared_line_pairs": int(len(agreed)),
        "clans_with_field_notes": len(notes),
        "standing_notes": standing_notes().get("notes", []),
        "standing_notes_source": standing_notes().get("source"),
        "clans_river_boundary": sum(1 for v in notes.values()
                                    if v.get("river_boundary")),
        "gpx_clans": len(gpx),
        "gpx_gaps": sum(g["gaps"] for g in gpx.values()),
        "gpx_gap_km": round(sum(g["km"] for g in gpx.values()), 1),
        "stewards": int(len(steward_table)),
        "steward_days": int(len(dated_days)),
        "field_days": int(dated_days.date.nunique()) if len(dated_days) else 0,
        "first_walk": str(dated_days.date.min()) if len(dated_days) else None,
        "last_walk": str(dated_days.date.max()) if len(dated_days) else None,
        "zones": zones,
        "contested_table": contested.sort_values("pct_contested",
                                                 ascending=False)
        .to_dict("records"),
        "overlap_table": overlaps.to_dict("records") if not overlaps.empty
        else [],
        "shared_line_table": agreed.to_dict("records") if not agreed.empty
        else [],
    }

    # ---- per clan ----------------------------------------------------
    records = []
    for unit, group in named.groupby("_unit", sort=True):
        clan = group.clan.iloc[0]
        zone = group.zone.iloc[0]
        row = closures.loc[unit] if unit in closures.index else None
        polygon = surveys[surveys._unit == unit]
        geometry = polygon.geometry.iloc[0] if len(polygon) else None

        people = []
        for steward, walk in group.groupby("steward"):
            person = steward_table[steward_table.steward == steward] \
                if not steward_table.empty else pd.DataFrame()
            days = steward_days[(steward_days.steward == steward)
                               & (steward_days.clan == clan)] \
                if not steward_days.empty else pd.DataFrame()
            people.append({
                "steward": steward,
                "tracks": int(len(walk)),
                "km": round(walk.geometry.length.sum() / 1000, 2),
                "days": int(days.date.notna().sum()) if len(days) else 0,
                "first": _json(days.date.min()) if len(days) else None,
                "last": _json(days.date.max()) if len(days) else None,
                "type": ", ".join(sorted(set(walk.feature_type.dropna()))),
            })
        people.sort(key=lambda p: -p["km"])

        mine = overlaps[(overlaps.clan_a == clan) | (overlaps.clan_b == clan)] \
            if not overlaps.empty else pd.DataFrame()
        clan_overlaps = []
        for _, pair in mine.iterrows():
            first = pair.clan_a == clan
            clan_overlaps.append({
                "with": pair.clan_b if first else pair.clan_a,
                "ha": pair.shared_ha,
                "pct": pair.pct_of_a if first else pair.pct_of_b,
                "beyond_tol_ha": pair.beyond_tol_ha,
                "beyond_tol_pct": (pair.beyond_tol_pct_of_a if first
                                   else pair.beyond_tol_pct_of_b),
                "verdict": pair.verdict,
            })
        clan_overlaps.sort(key=lambda o: -o["ha"])

        mine_lines = agreed[(agreed.clan_a == clan) | (agreed.clan_b == clan)] \
            if not agreed.empty else pd.DataFrame()
        shared = []
        for _, pair in mine_lines.iterrows():
            first = pair.clan_a == clan
            shared.append({
                "with": pair.clan_b if first else pair.clan_a,
                "km": pair.shared_km,
                "pct": pair.pct_of_a if first else pair.pct_of_b,
            })
        shared.sort(key=lambda s: -s["pct"])

        join = joining[joining.clan == clan] if not joining.empty \
            else pd.DataFrame()
        join_row = join.iloc[0] if len(join) else None

        records.append({
            "unit": unit, "clan": clan, "zone": zone,
            "stewards": people,
            "n_stewards": int(group.steward.nunique()),
            "walked_km": round(group.geometry.length.sum() / 1000, 2),
            "spur_km": round(smooth_tracks.spur_length(group) / 1000, 2),
            "status": _json(row.status) if row is not None else None,
            "chains": int(row.chains) if row is not None else None,
            "gap_km": round(row.gap_m / 1000, 2)
            if row is not None and pd.notna(row.gap_m) else None,
            "gap_pct": _json(row.gap_pct) if row is not None else None,
            "area_ha": _json(polygon.area_ha.iloc[0]) if len(polygon) else None,
            "basis": _json(polygon.basis.iloc[0]) if len(polygon) else None,
            "parcels": parcel_count(geometry),
            "bridges": int(polygon.bridges.iloc[0])
            if len(polygon) and "bridges" in polygon else 0,
            "overlaps": clan_overlaps,
            "shared_lines": shared,
            "join_sep_ha": _json(join_row.separate_ha)
            if join_row is not None else None,
            "join_joined_ha": _json(join_row.joined_ha)
            if join_row is not None else None,
            # `join_row["map"]` and not `join_row.map`: attribute access finds
            # Series.map, the method, and quietly puts it in the JSON in place
            # of the file name. Every clan map went missing from the document
            # that way, with no error anywhere.
            "map": _json(join_row["map"]) if join_row is not None else None,
            "field_notes": notes.get(unit, {}).get("notes", []),
            "field_source": notes.get(unit, {}).get("source"),
            "river_boundary": bool(notes.get(unit, {}).get("river_boundary")),
            "gpx": gpx.get(dataio.safe_name(unit), {}).get("file"),
            "gpx_gaps": gpx.get(dataio.safe_name(unit), {}).get("gaps", 0),
        })

    records.sort(key=lambda r: (r["zone"], r["clan"]))
    return {"summary": summary, "clans": records}


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def context(tolerance: float) -> dict:
    version = (VERSION_FILE.read_text(encoding="utf-8").strip()
               if VERSION_FILE.exists() else "0")
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                cwd=dataio.REPO_ROOT, capture_output=True,
                                text=True).stdout.strip() or None
    except Exception:
        commit = None
    today = date.today()
    return {
        "version": version,
        "changes": changes_since(version),
        "date": today.isoformat(),
        "date_long": today.strftime("%d %B %Y").lstrip("0"),
        "commit": commit,
        "overlap_tolerance_m": tolerance,
        "smoothing_spacing_m": 20,
        "clip_distance_km": 10,
        "metric_crs": dataio.METRIC_CRS,
        "max_gap_share": polygon_tools.DEFAULT_MAX_GAP,
        "closure_tolerance_m": closure.DEFAULT_TOLERANCE_M,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tracks", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg")
    parser.add_argument("--polygons", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_polygons.gpkg")
    parser.add_argument("--clans-dir", type=Path,
                        default=dataio.OUT_DIR / "clans")
    parser.add_argument("--stewards-dir", type=Path,
                        default=dataio.OUT_DIR / "stewards")
    parser.add_argument("--gpx-dir", type=Path, default=dataio.OUT_DIR / "gpx")
    parser.add_argument("--out-dir", type=Path,
                        default=dataio.OUT_DIR / "report")
    parser.add_argument("--overlap-tolerance", type=float,
                        default=polygon_tools.OVERLAP_TOLERANCE_M)
    args = parser.parse_args(argv)

    for path in (args.tracks, args.polygons):
        if not path.exists():
            print(f"Missing {path}. Run scripts/run_pipeline.py first.")
            return 1

    data = gather(args.tracks, args.polygons, args.clans_dir,
                  args.stewards_dir, args.overlap_tolerance,
                  args.gpx_dir)
    meta = context(args.overlap_tolerance)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(
        json.dumps(data["summary"], indent=1, default=_json), encoding="utf-8")
    (args.out_dir / "clandata.json").write_text(
        json.dumps(data["clans"], indent=1, default=_json), encoding="utf-8")
    (args.out_dir / "context.json").write_text(
        json.dumps(meta, indent=1), encoding="utf-8")

    s = data["summary"]
    print(f"Version {meta['version']}, {meta['date_long']}")
    print(f"  {s['clans']} clans, {s['surveys']} surveys, "
          f"{s['boundary_km']:,.0f} km of boundary")
    print(f"  overlap: {s['clans_overlap']} of {s['clans_mapped']} clans "
          f"strictly, {s['clans_overlap_beyond_tol']} beyond the "
          f"{s['overlap_tolerance_m']:.0f} m tolerance")
    print(f"  contested: {s['contested_ha']:,.0f} ha strictly, "
          f"{s['contested_beyond_tol_ha']:,.0f} ha beyond tolerance")
    print(f"  {s['clans_multi_parcel']} clan(s) hold land in more than one "
          f"parcel")
    print(f"\nWrote {args.out_dir}/summary.json, clandata.json, context.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
