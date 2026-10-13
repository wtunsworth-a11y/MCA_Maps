#!/usr/bin/env python3
"""Walking that is not boundary.

A steward walks to a place as well as along a line. Ginangi's file holds
45 km of walking, and 1.6 km of it is two tight knots of short recordings
sitting on a road junction by the Afore Market and at the Semmara
community -- somebody arriving somewhere and marking it, not somebody
walking an edge. The closing step cannot tell the difference. It reached
out to both knots and drew 10.3 km of chord across the middle of the clan
to do it.

Nothing is deleted and no raw file is touched. A recording named here is
left out of the boundary network for one survey, by the person reviewing
that survey's map, and it still appears on the map, still counts as
walked ground, and still carries whatever the steward wrote on it.

Keyed by survey unit -- '<Clan> - <Zone>', the same key the polygon layer
uses. Each entry is a place and a radius: any recording lying wholly
within that circle is off the boundary. A circle rather than a list of
names because the names are what the recording app happened to save, and
three of Ginangi's five are a timestamp.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402

REGISTER = dataio.REFERENCE_DIR / "off_boundary.json"


def circles(unit: str) -> list:
    if not REGISTER.exists():
        return []
    held = json.loads(REGISTER.read_text())
    return [row for row in held.get(unit, []) if "at" in row]


def drop(unit: str, parts: list) -> list:
    """The parts that are boundary, for this survey only.

    Applied where the boundary is written down, not in the shared
    pipeline: the recordings are untouched everywhere else, and the
    stored boundary is the layer we are free to edit.
    """
    found = circles(unit)
    if not found:
        return parts
    from shapely.geometry import Point

    keep = []
    for part in parts:
        inside = any(Point(row["at"]).buffer(row["radius"]).contains(part)
                     for row in found)
        if not inside:
            keep.append(part)
    return keep
