"""Repair WKB geometries that GEOS refuses to load.

The clan boundary GeoPackages are GPS track exports, and some tracks contain
parts with a single recorded point. A one-point LineString is not legal
geometry, so GEOS rejects the *entire* feature — a 35-track boundary is lost
because two of its tracks never got a second fix.

Rather than drop those files, this module rewrites the WKB with the degenerate
parts removed. Surviving parts are copied byte-for-byte out of the original
buffer, so no coordinate is re-encoded or shifted; only the container header's
part count changes.

Handles both EWKB (high-bit Z/M flags, optional embedded SRID) and ISO WKB
(1000/2000/3000 type offsets), in either byte order.
"""

from __future__ import annotations

import struct

WKB_POINT = 1
WKB_LINESTRING = 2
WKB_POLYGON = 3
WKB_MULTIPOINT = 4
WKB_MULTILINESTRING = 5
WKB_MULTIPOLYGON = 6
WKB_GEOMETRYCOLLECTION = 7

MULTI_TYPES = {WKB_MULTIPOINT, WKB_MULTILINESTRING, WKB_MULTIPOLYGON,
               WKB_GEOMETRYCOLLECTION}

EWKB_Z = 0x80000000
EWKB_M = 0x40000000
EWKB_SRID = 0x20000000

# The minimum number of points a part needs to be legal geometry.
MIN_POINTS = {WKB_LINESTRING: 2, WKB_POINT: 1}
MIN_RING_POINTS = 4  # a closed ring: 3 distinct corners plus the repeat


class WkbError(ValueError):
    """The buffer is not WKB this module knows how to walk."""


class _Header:
    __slots__ = ("order", "base", "dims", "body", "end")

    def __init__(self, order: str, base: int, dims: int, body: int):
        self.order = order      # struct byte-order character
        self.base = base        # geometry type with Z/M/SRID flags stripped
        self.dims = dims        # coordinates per point (2, 3 or 4)
        self.body = body        # offset just past the header


def _read_header(buf: bytes, off: int) -> _Header:
    if off + 5 > len(buf):
        raise WkbError("truncated geometry header")
    order = "<" if buf[off] == 1 else ">"
    raw_type = struct.unpack_from(order + "I", buf, off + 1)[0]
    cursor = off + 5

    if raw_type & (EWKB_Z | EWKB_M | EWKB_SRID):
        has_z = bool(raw_type & EWKB_Z)
        has_m = bool(raw_type & EWKB_M)
        if raw_type & EWKB_SRID:
            cursor += 4  # embedded SRID, which we preserve by copying bytes
        base = raw_type & 0x0FFFFFFF
    else:
        has_z = has_m = False
        base = raw_type
        if base >= 3000:
            base, has_z, has_m = base - 3000, True, True
        elif base >= 2000:
            base, has_m = base - 2000, True
        elif base >= 1000:
            base, has_z = base - 1000, True

    if not WKB_POINT <= base <= WKB_GEOMETRYCOLLECTION:
        raise WkbError(f"unknown geometry type {raw_type}")
    return _Header(order, base, 2 + has_z + has_m, cursor)


def _geometry_end(buf: bytes, off: int) -> int:
    """Offset of the first byte past the geometry starting at off."""
    header = _read_header(buf, off)
    cursor = header.body
    stride = header.dims * 8

    if header.base == WKB_POINT:
        return cursor + stride

    if header.base == WKB_LINESTRING:
        count = struct.unpack_from(header.order + "I", buf, cursor)[0]
        return cursor + 4 + count * stride

    if header.base == WKB_POLYGON:
        rings = struct.unpack_from(header.order + "I", buf, cursor)[0]
        cursor += 4
        for _ in range(rings):
            points = struct.unpack_from(header.order + "I", buf, cursor)[0]
            cursor += 4 + points * stride
        return cursor

    count = struct.unpack_from(header.order + "I", buf, cursor)[0]
    cursor += 4
    for _ in range(count):
        cursor = _geometry_end(buf, cursor)
    return cursor


def _part_point_count(buf: bytes, off: int) -> int:
    """Points in a Point/LineString part; rings use their exterior ring."""
    header = _read_header(buf, off)
    if header.base == WKB_POINT:
        return 1
    if header.base in (WKB_LINESTRING, WKB_POLYGON):
        return struct.unpack_from(header.order + "I", buf, header.body)[0]
    return 2  # nested multi-parts are judged by their own recursion


def repair(wkb: bytes) -> tuple[bytes | None, int]:
    """Drop degenerate parts from a geometry.

    Returns the repaired WKB and the number of parts removed. Returns
    ``(None, n)`` when nothing legal survives. A geometry that needs no repair
    comes back unchanged with a count of zero.
    """
    buf = bytes(wkb)
    header = _read_header(buf, 0)

    if header.base not in MULTI_TYPES:
        # A bare part: keep it only if it stands up on its own.
        minimum = MIN_POINTS.get(header.base)
        if minimum is not None and _part_point_count(buf, 0) < minimum:
            return None, 1
        if header.base == WKB_POLYGON:
            return _repair_polygon(buf, 0)
        return buf, 0

    count = struct.unpack_from(header.order + "I", buf, header.body)[0]
    cursor = header.body + 4

    kept: list[bytes] = []
    dropped = 0
    for _ in range(count):
        end = _geometry_end(buf, cursor)
        part = buf[cursor:end]
        part_header = _read_header(buf, cursor)

        if part_header.base in MULTI_TYPES or part_header.base == WKB_POLYGON:
            fixed, removed = repair(part)
            dropped += removed
            if fixed is not None:
                kept.append(fixed)
            else:
                dropped += 1
        else:
            minimum = MIN_POINTS.get(part_header.base, 0)
            if _part_point_count(buf, cursor) >= minimum:
                kept.append(part)
            else:
                dropped += 1
        cursor = end

    if not kept:
        return None, dropped
    if dropped == 0:
        return buf, 0

    rebuilt = (buf[:header.body]
               + struct.pack(header.order + "I", len(kept))
               + b"".join(kept))
    return rebuilt, dropped


def _repair_polygon(buf: bytes, off: int) -> tuple[bytes | None, int]:
    """Drop rings too short to close; a bad exterior ring kills the polygon."""
    header = _read_header(buf, off)
    order, stride = header.order, header.dims * 8
    rings = struct.unpack_from(order + "I", buf, header.body)[0]
    cursor = header.body + 4

    kept: list[bytes] = []
    dropped = 0
    for index in range(rings):
        points = struct.unpack_from(order + "I", buf, cursor)[0]
        end = cursor + 4 + points * stride
        if points >= MIN_RING_POINTS:
            kept.append(buf[cursor:end])
        else:
            if index == 0:
                return None, rings  # exterior ring is unusable
            dropped += 1
        cursor = end

    if not kept:
        return None, max(dropped, 1)
    if dropped == 0:
        return buf[off:cursor], 0
    return (buf[off:header.body] + struct.pack(order + "I", len(kept))
            + b"".join(kept)), dropped
