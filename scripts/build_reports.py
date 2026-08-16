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
