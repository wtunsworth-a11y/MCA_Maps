#!/usr/bin/env python3
"""Build the Word documents, named and stamped with their version and date.

Two documents come out of here:

* **Managalas Clan Land Mapping** — the survey results, a page per clan, and
  the queries for each clan.
* **Managalas Steward Days** — who walked, on which days, and how far.

Both are named `<title>_v<version>_<date>.docx`, so a new build never
overwrites the copy already in someone's inbox and nobody has to guess which
of two files is the later one. The version lives in `docs/VERSION`; bump it
when the content changes materially, and the date moves on its own.

Usage:
    python scripts/build_reports.py
    python scripts/build_reports.py --skip-data     # reuse output/report/*.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import report_data  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent

DOCUMENTS = [
    ("build_report_docx.js", "Managalas_Clan_Land_Mapping"),
    ("build_stewards_docx.js", "Managalas_Steward_Days"),
]


def _fingerprint(summary_path: Path, context: dict) -> dict:
    """What this build rests on, in enough detail to notice a data change.

    A version number is a promise that two files with the same name hold the
    same thing. The pipeline rebuilds the documents as its last stage, so a
    new data drop will happily regenerate an already-issued version under its
    own name — which breaks that promise silently. This is the check that
    catches it.
    """
    summary = (json.loads(summary_path.read_text(encoding="utf-8"))
               if summary_path.exists() else {})
    return {
        "clans": summary.get("clans"),
        "surveys": summary.get("surveys"),
        "units": summary.get("units"),
        "boundary_km": summary.get("boundary_km"),
        "last_walk": summary.get("last_walk"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json-dir", type=Path,
                        default=dataio.OUT_DIR / "report")
    parser.add_argument("--stewards-dir", type=Path,
                        default=dataio.OUT_DIR / "stewards")
    parser.add_argument("--out-dir", type=Path, default=dataio.OUT_DIR)
    parser.add_argument("--skip-data", action="store_true",
                        help="reuse the JSON already in --json-dir")
    parser.add_argument("--force", action="store_true",
                        help="rebuild a version even though it was already "
                             "built from different data")
    args = parser.parse_args(argv)

    if not args.skip_data:
        if report_data.main([]) != 0:
            return 1

    context_path = args.json_dir / "context.json"
    if not context_path.exists():
        print(f"No {context_path}. Run scripts/report_data.py first.")
        return 1
    context = json.loads(context_path.read_text(encoding="utf-8"))
    version, day = context["version"], context["date"]

    summary_path = args.json_dir / "summary.json"
    fingerprint = _fingerprint(summary_path, context)
    stamp_path = args.json_dir / "built.json"
    previous = (json.loads(stamp_path.read_text(encoding="utf-8"))
                if stamp_path.exists() else {})
    clash = previous.get(f"{version}_{day}")
    if clash and clash != fingerprint and not args.force:
        print(f"REFUSING to rebuild version {version} of {day}.\n")
        print("  A document with that name was already built from different "
              "data:")
        for key in sorted(set(clash) | set(fingerprint)):
            was, now = clash.get(key), fingerprint.get(key)
            flag = "  <-- changed" if was != now else ""
            print(f"    {key:12s} was {was}   now {now}{flag}")
        print("\n  Two documents would then both call themselves version "
              f"{version}, which is the confusion versioning exists to "
              "prevent.")
        print("  Bump docs/VERSION, or pass --force if you are sure the "
              "issued copy can be replaced.")
        return 1

    if shutil.which("node") is None:
        print("node is not available; cannot build the Word documents.")
        return 1

    built = []
    for script, stem in DOCUMENTS:
        name = f"{stem}_v{version}_{day}.docx"
        target = args.out_dir / name
        source = (args.stewards_dir if "stewards" in script else args.json_dir)
        result = subprocess.run(
            ["node", str(SCRIPTS / script), str(source),
             str(args.json_dir if "stewards" in script else dataio.REPO_ROOT),
             str(target)],
            capture_output=True, text=True, cwd=dataio.REPO_ROOT)
        if result.returncode != 0:
            print(f"  FAIL  {script}")
            print("\n".join("        " + line for line
                            in result.stderr.strip().splitlines()[-10:]))
            return 1
        print(f"  ok    {name}  "
              f"({target.stat().st_size / 1e6:.1f} MB)")
        built.append(target)

    previous[f"{version}_{day}"] = fingerprint
    stamp_path.write_text(json.dumps(previous, indent=1), encoding="utf-8")

    # Older builds are left alone deliberately — the point of versioning the
    # name is that the copy someone already has stays valid and findable.
    stale = sorted(p for p in args.out_dir.glob("*.docx") if p not in built)
    if stale:
        print(f"\n{len(stale)} earlier build(s) kept alongside: "
              f"{', '.join(p.name for p in stale[-3:])}")
    print(f"\nVersion {version}, {context['date_long']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
