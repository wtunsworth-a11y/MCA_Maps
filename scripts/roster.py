#!/usr/bin/env python3
"""The clans there are to hear from, set against the clans that have mapped.

The forum named 185 clans across eleven zones. Fifty-one surveys have come
in so far. This holds the roster, says which clans the data has reached,
and — the part that matters for the next hundred and fifty — says which
clans are still to be heard from, by zone and by village.

A roster name and a name typed into a GPS are not the same thing. "Ginagi"
on the roster and "Ginangi" in the recordings may be one clan or two, and
nothing here guesses. A name matches only when it matches exactly. Where
it does not, the pair is shown as a question and the link is written down
one clan at a time, by `--link`, after someone has said so:

    python scripts/roster.py                      # coverage, zone by zone
    python scripts/roster.py --questions          # near names, for review
    python scripts/roster.py --awaiting "Zone 8"  # who is still to map
    python scripts/roster.py --link Ginagi --zone "Zone 7A" \\
        --to "Ginangi — Zone 7A"   # one decided link, nothing else touched

`--link` never changes the roster and never changes a recording. It writes
a line in roster_links.json saying that this roster entry and this survey
are the same clan, so the report can count it once and name it the way the
clan was named at the forum.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402

ROSTER = dataio.REFERENCE_DIR / "clan_roster.json"
LINKS = dataio.REFERENCE_DIR / "roster_links.json"


def roster() -> dict:
    """The forum's list, as received. Read-only here."""
    if not ROSTER.exists():
        return {"entries": []}
    return json.loads(ROSTER.read_text(encoding="utf-8"))


def links() -> dict:
    """Decided links between a roster entry and a survey unit.

    Keyed "<Zone>|<roster clan>" so that the same clan name in two zones
    stays two entries, which is the whole point of the zone being in the
    survey name as well.
    """
    if not LINKS.exists():
        return {}
    return json.loads(LINKS.read_text(encoding="utf-8"))


def key(zone: str, clan: str) -> str:
    return f"{zone}|{clan}"


def surveys(data_path: Path) -> dict:
    """Every survey that has come in, with its clan name and zone.

    Read from the report's own data and not from the recordings, because
    the report's data is what has been looked at and agreed. A survey
    that has not been through review is not a survey the roster should
    count as mapped.
    """
    return from_records(json.loads(data_path.read_text(encoding="utf-8")))


def from_records(records: list) -> dict:
    """The same, from the records in hand."""
    found = {}
    for record in records:
        found[record["unit"]] = {
            "unit": record["unit"],
            "clan": ("" if record.get("clan_equivalent")
                     else str(record.get("clan") or "").strip()),
            "name": str(record.get("clan") or "").strip(),
            "zone": str(record.get("zone") or "").strip(),
            "tracks": sum(w["tracks"] for w in record.get("stewards", [])),
        }
    return found


def coverage(data_path: Path) -> dict:
    """Coverage read from a written clandata.json."""
    return tally(surveys(data_path))


def tally(found: dict) -> dict:
    """Which roster clans the data has reached, and which it has not.

    Three ways in, in this order, and no others:
      * the roster name and the survey's clan name are the same, in the
        same zone;
      * a link someone decided and wrote down;
      * nothing — the clan is awaiting data.

    A survey that matches no roster entry is reported too. It is not a
    mistake and nothing is done about it here: it may be a spelling, a
    clan the forum did not name, or ground that is not a clan at all.
    """
    book = roster()
    decided = links()

    by_name: dict = {}
    for info in found.values():
        if info["clan"]:
            by_name.setdefault(key(info["zone"], info["clan"]), []).append(info)

    taken, rows = set(), []
    for entry in book.get("entries", []):
        this = key(entry["zone"], entry["clan"])
        hit = list(by_name.get(this, []))
        linked = decided.get(this, {}).get("units") or []
        for unit in linked:
            if unit in found and found[unit] not in hit:
                hit.append(found[unit])
        for info in hit:
            taken.add(info["unit"])
        rows.append({
            "zone": entry["zone"],
            "clan": entry["clan"],
            "village": entry["village"],
            "units": [i["unit"] for i in hit],
            "mapped": bool(hit),
            "how": ("name" if by_name.get(this) else
                    "linked" if linked else None),
        })

    spare = [info for unit, info in sorted(found.items()) if unit not in taken]
    return {"roster": book, "rows": rows, "surveys": found, "spare": spare}


def questions(state: dict, cutoff: float = 0.62) -> list:
    """Names that look like each other but are not the same.

    For review, one at a time. Nothing here is applied: two names being
    close is not evidence that two clans are one, and in a place where
    neighbouring clans share ancestral names it can easily be the
    opposite.
    """
    asked = []
    for info in state["spare"]:
        if not info["clan"]:
            continue
        # The whole roster for the zone, mapped entries included. A survey
        # whose nearest roster name is already claimed by a different
        # survey is the case that matters most here: two surveys, one
        # name on the list. That may be two stewards of one clan, or a
        # sub-clan that mapped its own ground.
        pool = [r for r in state["rows"] if r["zone"] == info["zone"]] \
            or state["rows"]
        scored = []
        for row in pool:
            score = difflib.SequenceMatcher(
                None, info["clan"].lower(), row["clan"].lower()).ratio()
            if score >= cutoff:
                scored.append((score, row))
        # Closest first. Sorting these by name instead would bury the one
        # that actually looks like the survey's name under whatever
        # happens to come first in the alphabet.
        scored.sort(key=lambda pair: -pair[0])
        for score, row in scored[:3]:
            asked.append({
                "survey": info["unit"], "survey_clan": info["clan"],
                "survey_zone": info["zone"], "roster_clan": row["clan"],
                "roster_zone": row["zone"], "village": row["village"],
                "same_zone": row["zone"] == info["zone"],
                "roster_taken": [u for u in row["units"]],
                "score": round(score, 3),
            })
    asked.sort(key=lambda a: (a["survey_zone"], a["survey_clan"],
                              -a["score"]))
    return asked


def for_report(records: list) -> dict:
    """The roster as the document shows it: who has mapped, who has not.

    Awaiting clans are listed in full, by zone and village, so a clan can
    see its own name and say whether the list has it right.
    """
    state = tally(from_records(records))
    book = state["roster"]
    zones: dict = {}
    for row in state["rows"]:
        tally_row = zones.setdefault(row["zone"],
                                     {"zone": row["zone"], "on_roster": 0,
                                      "mapped": 0})
        tally_row["on_roster"] += 1
        tally_row["mapped"] += 1 if row["mapped"] else 0
    for tally_row in zones.values():
        tally_row["awaiting"] = tally_row["on_roster"] - tally_row["mapped"]
    awaiting = [{"zone": r["zone"], "clan": r["clan"], "village": r["village"]}
                for r in state["rows"] if not r["mapped"]]
    mapped = [{"zone": r["zone"], "clan": r["clan"], "village": r["village"],
               "units": r["units"]}
              for r in state["rows"] if r["mapped"]]
    return {
        "source": book.get("source"),
        "received": book.get("received"),
        "on_roster": len(state["rows"]),
        "mapped": len(mapped),
        "awaiting": len(awaiting),
        "zones": list(zones.values()),
        "awaiting_list": awaiting,
        "mapped_list": mapped,
        # Surveys the roster does not name. Left as a question, never
        # matched by resemblance.
        "unmatched": [{"clan": i["name"], "zone": i["zone"],
                       "unit": i["unit"]} for i in state["spare"]],
        "questions": questions(state),
        "links": len(links()),
    }


def record_link(zone: str, clan: str, units: list, why: str = "") -> dict:
    """Write down one decided link. One clan, nothing swept."""
    book = roster()
    names = {key(e["zone"], e["clan"]) for e in book.get("entries", [])}
    this = key(zone, clan)
    if this not in names:
        raise SystemExit(f"{clan} is not on the roster in {zone}. "
                         "The roster is the forum's list and is not edited "
                         "here.")
    decided = links()
    row = decided.setdefault(this, {"zone": zone, "clan": clan, "units": []})
    for unit in units:
        if unit not in row["units"]:
            row["units"].append(unit)
    if why:
        row.setdefault("why", []).append(why)
    LINKS.write_text(json.dumps(decided, indent=1, ensure_ascii=False) + "\n",
                     encoding="utf-8")
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path,
                        default=dataio.OUT_DIR / "report" / "clandata.json",
                        help="the report's data, as reviewed and agreed")
    parser.add_argument("--questions", action="store_true",
                        help="names that look alike, for review one by one")
    parser.add_argument("--awaiting", metavar="ZONE", nargs="?", const="",
                        help="clans still to map, all zones or one")
    parser.add_argument("--spare", action="store_true",
                        help="surveys that match no roster entry")
    parser.add_argument("--link", metavar="CLAN",
                        help="record that a roster clan and a survey are one")
    parser.add_argument("--zone", help="the roster zone of --link")
    parser.add_argument("--to", dest="to", action="append", default=[],
                        metavar="UNIT", help="the survey unit, as named")
    parser.add_argument("--why", default="", help="who said so, and when")
    args = parser.parse_args(argv)

    if args.link:
        if not args.zone or not args.to:
            print("--link needs --zone and at least one --to")
            return 1
        row = record_link(args.zone, args.link, args.to, args.why)
        print(f"{args.link} ({args.zone}) -> {', '.join(row['units'])}")
        return 0

    if not args.data.exists():
        print(f"Missing {args.data}. Run scripts/report_data.py first.")
        return 1
    state = coverage(args.data)

    if args.questions:
        asked = questions(state)
        if not asked:
            print("No near names to review.")
            return 0
        print(f"{len(asked)} pair(s) to decide, one at a time:\n")
        for a in asked:
            same = "same zone" if a["same_zone"] else "DIFFERENT zone"
            print(f"  roster  {a['roster_clan']}  ({a['roster_zone']}, "
                  f"{a['village']})")
            print(f"  survey  {a['survey_clan']}  ({a['survey_zone']})  "
                  f"[{same}]")
            if a["roster_taken"]:
                print("          that roster name is already mapped by "
                      + ", ".join(a["roster_taken"]))
            print(f"          {a['survey']}\n")
        return 0

    if args.spare:
        for info in state["spare"]:
            print(f"  {info['name'] or '(no clan named)':28} "
                  f"{info['zone']:9} {info['tracks']:3} recordings  "
                  f"{info['unit']}")
        return 0

    if args.awaiting is not None:
        rows = [r for r in state["rows"] if not r["mapped"]
                and (not args.awaiting
                     or r["zone"].lower() == args.awaiting.lower())]
        for row in rows:
            print(f"  {row['zone']:9} {row['clan']:20} {row['village']}")
        print(f"\n{len(rows)} clan(s) awaiting data")
        return 0

    zones = {}
    for row in state["rows"]:
        tally = zones.setdefault(row["zone"], {"on_roster": 0, "mapped": 0})
        tally["on_roster"] += 1
        tally["mapped"] += 1 if row["mapped"] else 0
    print(f"{state['roster'].get('source','')}\n")
    print(f"  {'Zone':10} {'On roster':>9} {'Mapped':>7} {'Awaiting':>9}")
    for zone, tally in zones.items():
        print(f"  {zone:10} {tally['on_roster']:9} {tally['mapped']:7} "
              f"{tally['on_roster'] - tally['mapped']:9}")
    on = sum(t["on_roster"] for t in zones.values())
    did = sum(t["mapped"] for t in zones.values())
    print(f"  {'all':10} {on:9} {did:7} {on - did:9}")
    print(f"\n  {len(state['surveys'])} survey(s) in, {len(state['spare'])} "
          f"of them matching no roster entry by name")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
