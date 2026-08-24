# Methods: cleaning and reviewing the clan boundary data

**Status: living document.** The processing is ongoing and this record is
updated as steps change. Every figure quoted here is reproducible by running
the scripts in `scripts/` against the archives in `data/raw/`.

Last updated: 2026-08-18.

---

## 1. Scope and source

69 GPS surveys of clan land boundaries in Oro Province, Papua New Guinea,
supplied as seven zip archives — one per zone — covering zones 2, 3, 6, 7A, 7B
and 8. Surveys are dated July and August 2026.

The reference boundary is the WDPA **Managalas Conservation Area** polygon
(WDPAID 555651673, designated 2017), supplied as KML and stored at
`data/reference/mca_boundary.kml`. Measured in EPSG:32755 it covers
**213,269 ha**; the file's own `GIS_AREA` attribute states 214,696 ha, a 0.7%
difference arising from how the two projections measure the same polygon.

## 2. Principles

1. **Raw data is never edited.** `data/raw/` holds the archives exactly as
   supplied. Every derived product is written elsewhere and is reproducible by
   re-running the scripts. No step writes back to the source.
2. **Repair rather than discard.** Where a file is unreadable for a mechanical
   reason, the mechanism is fixed and the data kept. Files are only dropped
   when there is nothing recoverable in them.
3. **Flag rather than correct.** Anything requiring local knowledge — whether
   two clan names are the same clan, whether an outlying track is real — is
   reported for human decision, not silently resolved.
4. **Separate measured from inferred.** Any figure resting on an assumption is
   labelled as such and carries a measure of how much was assumed.
5. **Report sensitivity.** Where a result depends on a chosen threshold, the
   result is reported across a range of that threshold, not at one value only.

## 3. Coordinate reference systems

| Purpose | CRS | Why |
| --- | --- | --- |
| Storage and exchange | EPSG:4326 (WGS84) | Native CRS of the source data |
| All measurement | **EPSG:32755** (UTM 55S) | True metres for this longitude |
| Web basemaps only | EPSG:3857 | Tile convention |

Every distance, length, spacing, buffer and area is computed in EPSG:32755.
This matters: Web Mercator overstates distance at 9°S by about 1.2%. An early
draft of this work quoted 1,349 km of track measured in Web Mercator; the
correct figure is **1,327 km**.

## 4. Processing stages

### 4.1 Unpacking and reading (`scripts/dataio.py`)

Archives are extracted to `data/processed/extracted/`, a regenerable cache
(`--refresh` rebuilds it). Zips nested inside zips are unwrapped, since some
exports bundle per-region archives. Extraction paths are checked so no archive
entry can write outside its target directory.

Readable formats: shapefile, GeoPackage, GeoJSON, KML, GML, GPX, FlatGeobuf,
and delimited text with coordinate columns. `.json` files are probed as GeoJSON
and skipped quietly if they are not spatial.

Delimited text has its separator and encoding sniffed (UTF-8, UTF-8-BOM,
CP1252, Latin-1 in order). Latitude and longitude columns are matched
case-insensitively against a list of common names, overridable with
`--lat-col` / `--lon-col`. **Failures are printed, never swallowed** — an early
version silently dropped every CSV because of an incompatible pandas argument,
which is exactly the failure mode this rule exists to prevent.

### 4.2 Geometry repair (`scripts/geomfix.py`)

These are GPS track exports and they contain two defects that GEOS rejects:

**Single-point track parts.** 31 of the 69 files contain at least one track
part holding one recorded fix. A one-point LineString is not legal geometry, so
GEOS refuses the *entire feature* — in the worst case a 35-track boundary was
being lost because two of its tracks never got a second fix.

The repair rewrites the WKB with those parts removed. Surviving parts are
copied **byte-for-byte** out of the original buffer; only the container
header's part count changes. No coordinate is re-encoded, and Z values are
preserved. Both EWKB (high-bit Z/M flags, optional embedded SRID) and ISO WKB
(1000/2000/3000 type offsets) are handled, in either byte order.

**Stationary parts.** A receiver left running in one place logs many fixes at a
single coordinate. Structurally the part is a valid LineString, but every
vertex is identical, so GEOS reduces it to fewer than two distinct vertices and
marks the whole feature invalid. Six features were affected. These parts are
dropped on the same basis: they record no line, so nothing is lost. Comparison
is on X/Y only, matching how GEOS judges validity.

Repairs are only kept where the result is valid; a genuinely self-intersecting
polygon would be left alone for a human. Every repair is printed as it happens.

**Result:** all 69 files load, 601 features, 0 invalid geometries, Z preserved
on the 600 features that carry it in the source.

### 4.3 Reading metadata from file names (`scripts/clans.py`)

The zone, clan and steward are encoded in file names, not in the data. Two
conventions are in use, and both place the clan name beside the word "clan",
so that word anchors the parse:

```
Jethro_Akse_Asingi_Clan_Land_Boundary_Zone_2_14July2026
└─ steward ─┘ └clan┘                  └zone┘ └─ date ─┘

manuvoora_clan_egobeyas_kuarisi_tracks_zone_6
└─ clan ─┘     └─── steward ────┘     └zone┘
```

Which side holds the steward is decided by whether any real name survives
after the anchor once structural words are removed. Clan names of two words
("Nupa Ora") are preserved — taking only the token adjacent to the anchor
truncated them in an earlier version.

Four files omit the zone from their name; these **inherit the zone from the
archive they arrived in**, which is authoritative.

Parsing reads the *original file stem*, not the layer name. Layer names are
truncated to 60 characters for GeoPackage table limits, which in one case cut
`14July2026` to `14July20`; the date regex then missed it and the fragment was
mistaken for part of a steward's name.

Derived attributes on every feature: `clan`, `steward`, `zone`,
`feature_type`, `survey_date`, `source_name`.

Dates with a two-digit year are reported as the raw text rather than having a
century invented for them. One source file name contains a typo, `14July206`,
which is passed through unaltered.

A second date form is in use, `Aug_26` — a month and a two-digit number, with
no day. It must be recognised even though it cannot be resolved: left
unmatched, the month name survives into the token list and gets read as part
of somebody's name. `Lenard_Urami_Sahirut_Clan_Boundary_Zone_6_Aug_26` parsed
as clan "Lenard Urami Sahirut", steward "Aug", until `MONTH_YEAR_PATTERN` was
added. The text is kept as written: the trailing number could be a day or a
year, and §6.5 settled that the file-name date is when the archive was
collated, so nothing downstream depends on resolving it.

**Where a track disagrees with its file about who walked it.** The steward
comes from the file name, which for most surveys is the only place it is
recorded. Some devices also write a name onto each track, and
`stewards.name_mismatches()` reports every case where the two disagree —
currently four tracks, 15.2 km, inside
`solomon_makanisa_sahirut_clan_boundary_aug_26.gpkg` that credit Lenard Urami.
**Nothing is reassigned.** Who walked which track is a question for the field,
and guessing would put a day's work against the wrong person's name. It is
listed in *Managalas Steward Days* and in
`output/stewards/name_mismatches.csv`.

**Confirmed spelling corrections.** Two clan-name pairs were flagged by name
similarity, corroborated by near-total polygon overlap, and confirmed by the
survey team as typos. They are merged through an alias table in
`scripts/clans.py`, which is the single place to change them:

| Recorded as | Kept as | Evidence |
| --- | --- | --- |
| Manuvuoora | **Manuvoora** | 834.6 ha shared — 99.0% / 77.9% |
| Sungulkol | **Sugulkol** | 258.7 ha shared — 71.3% / 96.7% |

This takes the distinct clan count from 48 to **46**.

**Survey composition after parsing:**

| Zone | Clans | Clan Stewards | Surveys | Tracks | Length (km) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Zone 2 | 15 | 18 | 20 | 203 | 320.5 |
| Zone 3 | 4 | 8 | 8 | 17 | 48.7 |
| Zone 6 | 5 | 7 | 7 | 80 | 151.6 |
| Zone 7A | 3 | 6 | 6 | 37 | 73.7 |
| Zone 7B | 12 | 18 | 18 | 78 | 282.3 |
| Zone 8 | 8 | 10 | 10 | 185 | 236.1 |
| **Total** | **46** | **67** | **69** | **600** | **1,112.9** |

Clan totals do not sum down the column: some clans hold land in more than one
zone. Lengths are smoothed (§4.6).

**Feature types recorded:**

| Type | Surveys | Tracks | Length (km) |
| --- | ---: | ---: | ---: |
| Land Boundary | 66 | 584 | ~1,092 |
| Road | 1 | 13 | 4.3 |
| Sacred Site | 1 | 3 | 10.6 |
| Steward Block | 1 | 1 | 6.3 |

See §6.4 — the last three are not clan land boundaries but are currently
included in the figures.

### 4.4 Merging (`scripts/dataio.py`)

The 69 layers are merged into one attributed layer. Separate layers per file
are unusable in QGIS; a single layer carrying the parsed attributes can be
categorised, filtered and queried. Per-zone layers are written alongside it.

Two schema reconciliations happen here, both reported:

- **Case-variant columns.** GeoPackage field names are case-insensitive, so
  `name` (from GPX sources) and `Name` (from KML) collide on write. They were
  verified to be perfectly disjoint — 418 + 183 = 601, every feature — and are
  therefore the same field from two source schemas, so they are coalesced.
  Where variants genuinely overlap they are suffixed instead, because merging
  would discard one of two real values.
- **Empty columns.** 16 columns are empty for every row after the union of
  schemas and are dropped.

### 4.5 Clipping to the MCA (`scripts/smooth_tracks.py`)

Track parts more than **10 km** (`--max-distance-km`) from the MCA boundary are
dropped. Distance is measured to the conservation *area*, so anything inside it
is zero away; only genuinely outside data is removed.

Filtering is per track part, not per feature, so one errant track does not take
a survey's good data with it.

**Result: one part dropped** — the test track described in §6.1. All other
recorded data lies within 10 km of the conservation area.

### 4.6 Resampling and smoothing (`scripts/smooth_tracks.py`)

Handheld GPS fixes scatter by several metres even along a straight walk, which
inflates every distance measured from them. Two steps:

1. **Resample** to one point every **20 m** (`--spacing`), so every track is
   described at the same resolution regardless of walking speed. The final
   point is the true line end rather than the last whole step, so no track is
   silently shortened.
2. **Smooth** with a **3-point moving average** (`--window`, or `--no-smooth`).
   Track endpoints are held in place, because closure analysis measures exactly
   those endpoints; averaging them would pull a boundary's ends together and
   flatter the closure figures.

Elevation is dropped at this point. It is GPS-derived and noisier than the
horizontal fix, and nothing downstream uses it.

Effect on total length, each step reported separately so the contribution of
each is visible:

| Step | Length | Change |
| --- | ---: | ---: |
| Raw | 1,327.2 km | |
| After clipping | 1,327.1 km | −0.0% |
| After resampling | 1,206.9 km | −9.1% |
| After smoothing | 1,112.9 km | −7.8% |

The **−16% overall is the GPS bounce being removed** — the raw figure was
inflated by jitter, not the smoothed figure deflated. Vertices fall from
122,610 to 69,372. Achieved spacing: median 18.2 m, p95 19.9 m (the moving
average pulls points slightly closer than the 20 m resampling target).

Output goes to `data/smoothed/mca_tracks_smoothed.gpkg` — a separate directory
from both the raw archives and the intermediate cache.

### 4.7 Closure analysis (`scripts/closure.py`)

Closure is judged **per survey**, not per track: a boundary is walked over
several sessions, so a single track says nothing about whether the land is
ringed.

Track ends within **25 m** (`--tolerance`) are treated as joined. Then the
tracks are **polygonized**, and a boundary counts as closed when the polygon it
encloses has a perimeter of at least **50%** of the distance walked
(`--min-enclosure`).

**This test is geometric on purpose.** An earlier version chained endpoints and
asked whether the graph formed a loop. That was wrong: walking a line out and
back closes a connectivity graph while enclosing nothing. It misclassified real
cases in both directions. The geometric test separates the two populations
cleanly — genuine closures enclose 166–1,901 ha with a perimeter of 99–100% of
the walk, everything else encloses near-zero area at under 5%. There is no
ambiguous middle, which is why a 50% threshold is safe.

For surveys that do not close, the **gap to close** is the straight-line
distance still needed to join the recorded pieces into one ring. For a survey
recorded in one piece this reduces to the distance between its two open ends —
the definition originally requested — and it extends naturally to surveys
recorded in several pieces, where every join counts. The pieces are ordered
and oriented by `order_chains` — nearest open end first, then 2-opt (§4.8) —
so the figure is the shortest joining that search finds rather than the first
one tried. It remains an upper bound on the true minimum, so a survey is never
reported as closer to closure than it is. The closure report and the polygon
builder use the same ordering, so the gap quoted and the gap drawn are one
measurement. Under **10%** of the distance walked (`--threshold`) counts as
near closure.

Short dead-end branches are pruned first, up to a **cumulative** 10% of the
survey's distance (`--max-spur`). Surveyors walk in to where a boundary starts
and out again at the end, and those access spurs would otherwise read as extra
open ends. The budget is cumulative rather than per-branch: applied per-branch
it consumed 25 km of one 30 km survey one leg at a time, leaving a stub that
trivially looked like a closed ring. Enclosure is also measured against
everything walked rather than the post-pruning remainder, so no verdict can be
manufactured by pruning a survey down.

Surveys under 100 m (`--min-length`) are reported as too short to assess.

**Result at the default 25 m tolerance:** 7 closed, 7 near closure, 54 open,
1 too short. Because the answer moves with the tolerance, it is always reported
across a range:

| Tolerance | Closed | Near | Open |
| ---: | ---: | ---: | ---: |
| 10 m | 0 | 6 | 62 |
| **25 m** | **7** | **7** | **54** |
| 50 m | 10 | 6 | 52 |
| 100 m | 13 | 4 | 51 |

**By zone (at 25 m):**

| Zone | Closed | Near | Open | Too short |
| --- | ---: | ---: | ---: | ---: |
| Zone 2 | 4 | 2 | 14 | 0 |
| Zone 3 | 0 | 0 | 7 | 1 |
| Zone 6 | 0 | 2 | 5 | 0 |
| Zone 7A | 0 | 0 | 6 | 0 |
| Zone 7B | 3 | 1 | 14 | 0 |
| Zone 8 | 0 | 2 | 8 | 0 |

Closure is concentrated in zones 2 and 7B; zones 3, 6, 7A and 8 have no fully
closed boundary at this tolerance.

**The seven closed boundaries:**

| Zone | Clan | Clan Steward | Walked (km) | Area (ha) |
| --- | --- | --- | ---: | ---: |
| Zone 2 | Sukandi | Rodney Ajinko | 29.09 | 1,901.4 |
| Zone 7B | Wohukol | Darline Walele | 17.10 | 308.6 |
| Zone 7B | Wohukol | Nelson Runage | 17.81 | 306.1 |
| Zone 2 | Majanko | Gilford Amakana | 7.51 | 275.8 |
| Zone 2 | Murai | Nehemiah Nindori | 7.33 | 198.9 |
| Zone 2 | Asingi | Jethro Akse | 6.43 | 166.1 |
| Zone 7B | Abuankol | Simeon Pasip | 0.51 | 0.6 |

**The seven near closures**, smallest gap first — these are the surveys where a
short additional walk would complete a boundary:

| Zone | Clan | Clan Steward | Walked (km) | Gap (m) | Gap % |
| --- | --- | --- | ---: | ---: | ---: |
| Zone 8 | Gubai | Kenny Noi | 91.86 | 4,911 | 5.3 |
| Zone 8 | Dusi | Max Mamo | 32.95 | 1,888 | 6.3 |
| Zone 7B | Natang | Stafford Gidiri | 46.50 | 3,392 | 7.3 |
| Zone 6 | Naharaura | Zechariah Sasavo | 32.63 | 2,490 | 7.6 |
| Zone 6 | Pina Ora | Alban Ezekiel | 18.85 | 1,430 | 8.3 |
| Zone 2 | Juaiko | Gasper K Philip J | 24.30 | 1,883 | 8.5 |
| Zone 2 | Kasaki | Ananias Masua | 15.13 | 1,345 | 9.8 |

### 4.8 Building area polygons (`scripts/polygons.py`)

Two kinds of polygon, kept strictly apart in a `basis` column:

- **Surveyed** — the tracks already ring the land; the polygon is exactly what
  was walked. Nothing assumed.
- **Inferred** — the tracks stop short, the open ends are bridged with straight
  lines, and the ring is an estimate. Every one carries `gap_pct`, the share of
  its perimeter bridged rather than walked.

Polygons bridged across more than **50%** of the walk (`--max-gap`) are dropped
as too speculative to report as an area. `--surveyed-only` restricts everything
to walked rings.

An inferred polygon is a working estimate of ground covered. **It is not a
boundary anyone has agreed to** and must not be presented as one.

#### The straight lines are not boundary

An inferred polygon's outline is part walked line and part straight line. The
straight parts are **not boundary and are never presented as such**. They mark
where the receiver was switched off at the end of one walk and switched on
again somewhere else; the steward did not fly across the landscape, they walked
away and came back another day.

They are therefore:

- written as their own layer, `inferred_bridges`, never merged into the
  boundary line;
- drawn in **pink dashes** on every map they appear on, in a colour used for
  nothing else;
- excluded from every distance total, which counts walked ground only;
- reported per clan as "not walked (km)", and raised as a query asking for the
  missing stretch.

Currently **169.7 km of the outlines, in 188 stretches, is straight line
nobody walked — 26% of the 653 km of outline drawn around the mapped areas**.
That is not a small correction to an otherwise complete survey: a quarter of
what looks like boundary on a map of areas is inference, it is concentrated in
a few clans (Tuoko 17.1 km, Mariura 14.2 km, Rondi 12.4 km), and the per-clan
tables say which.

#### Which way round each piece is taken — a corrected result

Joining several disconnected pieces into a ring is two decisions: the order to
visit them in, and **which end of each piece to enter by**. The second was
being made badly, and it mattered more than the first.

The original code chained pieces greedily, nearest open end first, and never
reconsidered a piece's direction. Take one the wrong way round and its
bridging lines cross, producing a **bow-tie**: a figure-of-eight enclosing two
small lobes where the walk actually encloses one large block. Tuoko showed it
plainly — two straight lines crossing in the middle of the clan's land, and an
area that was the sum of two triangles.

The fix treats it as what it is, a travelling-salesman tour over the pieces
(`closure.order_chains`): nearest-neighbour to start, then **2-opt**, whose
move reverses a run of pieces — flipping each one's direction as well as their
order. In Euclidean space a self-crossing tour is never the shortest, so a
2-opt local optimum has no crossing bridges left and the bow-tie unties itself.

The effect, holding all other parameters fixed:

| | Before | After |
| --- | ---: | ---: |
| Tuoko | 3,282 ha, two lobes | **3,676 ha, one block** |
| Bimkol | no area | **158 ha** |
| Darekikol | 528 ha | 587 ha |
| Total mapped | 32,294 ha | **33,109 ha** |
| Polygons that are geometrically valid | 33 of 35 | **36 of 36** |

Two consequences beyond the numbers. `_enclosed()` now **unions** the pieces
it keeps rather than collecting them into a multipolygon, because a
self-crossing outline produced overlapping lobes whose areas were being added
together — ground counted twice. And the closing-gap figure in the closure
report uses the same ordering, so the gap quoted and the gap drawn are the
same measurement.

This was found from the field, not from the code: the straight lines looked
wrong on a map, and the question asked was "what would the polygon look like
if you reversed the directionality of one of the polylines". That is exactly
what the 2-opt move does.

#### Land held in more than one piece

A clan's land does not have to be one block, and the pipeline does not assume
it is. `polygons._enclosed()` returns **every** substantial area the tracks
enclose as a multipolygon, not just the largest, and the clan's area is their
sum. Each parcel is drawn on the maps and carried into QGIS.

This was not free. An earlier version took the largest polygon only, and
Wohukol lost an entire northern parcel to it. The loss looked like joining
stewards being harmful when it was in fact this function throwing ground away.

Parcels smaller than **2% of the clan's largest** are dropped: at that size a
loop is a track crossing itself, not a holding. The threshold is a floor on
noise, not a judgement about how small a real parcel can be — if a clan knows
of a parcel missing from its map, that is a survey still to walk, and it is
raised as a query on the clan's page.

Note one consequence: whether the walks describe one parcel or three is a
finding about the *survey*, not a settled fact about the tenure. A clan whose
tracks enclose two parcels may hold two blocks, or may have walked one
boundary in two disconnected pieces. Both readings appear on the clan's page,
and the query asks which it is.

| | Boundaries | Area |
| --- | ---: | ---: |
| Surveyed | 5 | 2,541.7 ha |
| Inferred | 31 | 30,566.5 ha |
| Dropped (gap > 50%) | 13 | — |
| Sum | 36 | 33,108.9 ha |
| Combined footprint (overlaps counted once) | | 28,032 ha |

The footprint is **13.1% of the MCA's 213,269 ha**. Note that **92% of the
mapped area is inferred**; only 2,542 ha rests on boundaries that actually
close, and 26% of the total outline drawn is straight line nobody walked.

**Mapped area by zone**, counted per clan-within-zone (§4.7) rather than per
file, so a clan walked by several stewards appears once:

| Zone | Boundaries | of which surveyed | Area (ha) |
| --- | ---: | ---: | ---: |
| Zone 2 | 12 | 4 | 18,906.8 |
| Zone 3 | 1 | 0 | 9.5 |
| Zone 6 | 4 | 0 | 3,088.8 |
| Zone 7A | 3 | 0 | 1,384.6 |
| Zone 7B | 10 | 1 | 6,693.2 |
| Zone 8 | 6 | 0 | 3,026.0 |
| **Total** | **36** | **5** | **33,108.9** |

Areas sum to more than the 28,032 ha footprint because polygons overlap
(§4.9); the difference is counted once in the footprint.

### 4.9 Overlap analysis (`scripts/polygons.py`)

Pairwise intersections are computed at both survey and clan level (clan
polygons being the dissolve of that clan's surveys). Reported as shared
hectares and as a share of each polygon's own area — asymmetric on purpose,
since a small polygon may be almost wholly inside a large one.

This serves two distinct purposes: locating where clans genuinely contest
ground, and testing whether two similar clan names are one clan recorded twice.

#### A 100 m tolerance, reported as a separate category

Every overlap is reported twice.

* **Strict** — every square metre two polygons share. This is the exact
  measurement, and every total is built from it.
* **Beyond tolerance** — the same overlap with any strip narrower than 100 m
  removed.

The tolerance comes from the field, not from the geometry. GPS fixes land
about 10 m apart under open sky and further under canopy; a boundary followed
on foot wanders around terrain; and two people walking the same edge on
different days will not walk the same line. Where two recorded lines run
within 100 m of each other, the ground between them is not a competing claim.
100 m is inconsequential here.

Implemented as a morphological opening: erode the shared area by 50 m, then
dilate it back by 50 m, and clip the result to the original. What survives is
every point sitting inside a 50 m disc that lies wholly within the shared
area — that is, ground at least 100 m across in every direction. A sliver
between two lines 60 m apart disappears entirely; a genuinely shared block
comes back essentially unchanged.

The distinction matters for the ILG question and it is not rhetorical. Of the
**54 pairs** of clans whose mapped land intersects, **20 share only strips
narrower than 100 m** — those pairs walked the same edge and agree on it.
Those 20 account for 19 ha of the 4,968 ha of pairwise shared area.

Counting each piece of ground once rather than once per pair, **4,712 ha is
claimed by more than one clan strictly, and 4,649 ha beyond the tolerance**;
**32 of 35 mapped clans overlap another strictly, 27 beyond the tolerance**.
The finding survives the allowance almost untouched, which is the reason for
making the allowance at all.

#### Where clans agree: shared lines

The mirror image, and not visible in an overlap table at all. Two clans can
walk the same edge — agreeing on a boundary — while enclosing no shared
ground whatsoever, because neither walk closes into a polygon.
`polygons.shared_lines()` reports, for each pair, the length of each clan's
own line running within the tolerance of the other's, in both directions
(the two are rarely equal: a short boundary can sit entirely along a long
one).

**Deari and Nui** are the case in point. Their polygons never meet — neither
walk closes — so they appear nowhere in the overlap table. Yet 94% of Deari's
13.1 km of line runs within 100 m of Nui's, the two lines cross 292 times,
and Deari's whole recorded extent sits inside Nui's. Under the 100 m rule
these two clans do not overlap: they share a boundary. Whether the remaining
8.4 km Nui walked beyond Deari's line is Nui's own further boundary is a
question for the two clans.

**Clan-to-clan overlaps after the confirmed typo merges** — 31 pairs, largest
twelve shown:

| Clan A | Clan B | Shared (ha) | % of A | % of B |
| --- | --- | ---: | ---: | ---: |
| Borori | Darekikol | 286.8 | 49.3 | 46.5 |
| Asoro | Sukandi | 233.2 | 6.6 | 12.3 |
| Juaiko | Sukandi | 204.6 | 15.8 | 10.8 |
| Rondi | Sukandi | 185.9 | 27.7 | 9.8 |
| Kasaki | Murai | 154.4 | 28.5 | 77.6 |
| Majanko | Manoko | 64.8 | 23.5 | 17.4 |
| Naharaura | Pina Ora | 59.6 | 10.0 | 7.3 |
| Binunkol | Jariji | 44.3 | 4.4 | 7.1 |
| Kasaki | Majanko | 39.9 | 7.4 | 14.5 |
| Ambunkol | Natang | 21.4 | 7.3 | 1.8 |
| Asoro | Juaiko | 15.2 | 0.4 | 1.2 |
| Manuvoora | Pina Ora | 14.2 | 1.3 | 1.8 |

Most are small edge overlaps consistent with adjoining clans and inferred
boundaries. Two stand out: **Borori / Darekikol** (§6.3), and **Kasaki / Murai**
where 77.6% of Murai's polygon sits inside Kasaki's — both are inferred
polygons, so this may be an artefact of bridging rather than a real dispute.

The full pairwise tables, at both clan and survey level, are in
`output/polygon_report.md`.

### 4.10 Sacred sites (`scripts/sacred_sites.py`)

Sacred sites are recorded differently from land boundaries and are reported
separately. The site name is written on the **track**, not the file name; one
walk can cover more than one site; and one site can be walked more than once.
Sites are therefore grouped by the name on the track.

None of these walks closes — every one has open ends across 40–60% of its
length — so every area is an estimate, and two are given: **bridged** (open ends
joined with straight lines, the same method as clan boundaries, so the figures
are comparable) and **hull** (the convex hull of the walk, an upper bound). The
true area lies between them.

**Locations, names and geometry are not shared** (§11.2). Sacred sites are
reported by area and share of clan land only, and are withheld from every
project file, exported layer and map by `dataio.publishable`.

**3 sites across 2 mapped units and 3 walks**, all within one clan's land:

| Unit | Sites | Walks | Walked (km) | Bridged (ha) | Hull (ha) | Bridged gap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 2 | 1 | 6.02 | 296.9 | 343.2 | 41% |
| B | 1 | 2 | 4.58 | 16.0 | 112.8 | 60% |
| **Total** | **3** | **3** | **10.60** | **312.9** | **456.0** | |

| Measure | Bridged | Hull |
| --- | ---: | ---: |
| Total area | 312.9 ha | 456.0 ha |
| Average per mapped unit | 156.4 ha | 228.0 ha |
| Share of Sukandi's 1,903 ha clan land | **16.4%** | **24.0%** |

Unit A covers two sites walked together in one track, which cannot be separated
afterwards. The gap between the two estimates for unit B — 16 ha bridged against
113 ha hull — shows how little the walk constrains its area; that figure should
not be quoted without the range.

#### Reading for the write-up

Two Papua New Guinean papers on customary restricted areas, both from Manus,
both in *Pacific Conservation Biology*. Neither is a method used here; both
bear directly on how these sites should be described.

- **Whitmore, N., Lamaris, J., Takendu, W., Charles, D., Chuwek, T., Mohe, B.,
  Kanau, L. & Pe-eu, S. (2016).** The context and potential sustainability of
  traditional terrestrial periodic *tambu* areas: insights from Manus Island,
  Papua New Guinea. *Pacific Conservation Biology* **22**(2), 151–158.
  [doi:10.1071/PC15036](https://doi.org/10.1071/PC15036)

  Periodic *tambu* — closure followed by harvest — treated as a clan
  institution rather than a folk analogue of a protected area. Its most
  useful finding for this work is that the three clans studied differed in
  purpose, in adherence to tradition, and in how far the practice had
  hybridised with modern land governance. Customary management is **not
  uniform across clans**, which is exactly the pattern the boundary data shows
  for tenure (§4.9), and it argues against writing up the Managalas sacred
  sites as a single category with a single rule.

- **Lamaris, J. & Whitmore, N. (2018).** Forest connectivity is important for
  sustaining Admiralty cuscus (*Spilocuscus kraemeri*) in traditional
  terrestrial no-take areas on Manus Island, Papua New Guinea. *Pacific
  Conservation Biology* **24**(1), 55–62.
  [doi:10.1071/PC17030](https://doi.org/10.1071/PC17030)

  Radio-tracking in and around a 21 ha *tambu* area: the animals' ranging
  crossed the boundary, so the area's value depended on the forest around it
  rather than on its own extent. The bearing on this survey is direct. The
  sacred sites recorded here are **313–456 ha** on a bracketed estimate, and
  that number on its own says little about what they conserve; what surrounds
  them, and whether it stays forested, matters more. It also gives a defensible
  reason to report the sites by **area and share of clan land** without
  locations — the ecological argument does not need coordinates.

Both are worth citing in the benefit-sharing argument too: they are evidence
from PNG that clan-governed restriction already functions as conservation, and
that its terms differ clan by clan.

## 5. Parameters

All defaults, all overridable at the command line.

| Parameter | Default | Script | Governs |
| --- | ---: | --- | --- |
| `--max-distance-km` | 10 km | smooth_tracks | Clip distance from MCA |
| `--spacing` | 20 m | smooth_tracks | Resampled point spacing |
| `--window` | 3 points | smooth_tracks | Moving-average width |
| `--tolerance` | 25 m | closure, polygons | Track ends treated as joined |
| `--threshold` | 10% | closure | Gap counted as near closure |
| `--max-spur` | 10% | closure, polygons | Cumulative spur-pruning budget |
| `--min-enclosure` | 50% | closure, polygons | Perimeter share to count as closed |
| `--min-length` | 100 m | closure | Too short to assess |
| `passes` (in code) | 200 | closure | 2-opt improvement passes when ordering the pieces |
| `--max-gap` | 50% | polygons | Inferred polygon rejected beyond this |
| `--overlap-tolerance` | 100 m | polygons, clan_maps | Shared strip narrower than this is not overlap |
| `min_share` (in code) | 2% | polygons | Smallest parcel kept, as a share of the largest |
| `--outlier-factor` | 3× | inspect_data | Distance from survey centre to flag |
| `--min-overlap-pct` | 20% | queries | Overlap large enough to query |
| `--max-per-category` | 5 | queries | Queries raised per category |

## 6. Open questions for domain review

These are flagged, not resolved. Each needs local knowledge.

### 6.1 One test recording — resolved, no action outstanding

An 81 m track named `2026-06-11 18:50 test`, in Zone 7B / Ginangi / Joshua
Mokondo's file, sits 370 m from the centre of Popondetta and 32 km from the
nearest other survey data. Across all 601 features, exactly one vertex falls
within 5 km of Popondetta. The reading that this is a device switched on and
tested in town is consistent with every measurement. It is removed by the 10 km
clip and no further action is required.

### 6.2 Similar clan names

**Closed 2026-08-16. All four flagged pairs are resolved.**

Automated name comparison flagged four pairs of clan names as similar enough to
be possible duplicates. Each was then tested against polygon overlap and put to
the survey team:

| Pair | Overlap | Outcome |
| --- | --- | --- |
| Manuvoora / Manuvuoora | 834.6 ha — 99.0% / 77.9% | **One clan.** Confirmed typo — merged, keeping *Manuvoora* |
| Sugulkol / Sungulkol | 258.7 ha — 71.3% / 96.7% | **One clan.** Confirmed typo — merged, keeping *Sugulkol* |
| Abuankol / Ambunkol | none | **Different clans.** Both mapped, no shared ground |
| Manang / Marang | not comparable | **Different clans.** Confirmed by the survey team |

The two confirmed typos are merged through the alias table in §4.3, taking the
distinct clan count from 48 to **46** (zone 6: 6→5, zone 7B: 13→12). The two
confirmed-distinct pairs are left exactly as recorded.

Worth noting how the two kinds of evidence combined. Name similarity alone
would have been wrong twice out of four — Abuankol/Ambunkol and Manang/Marang
are genuinely separate clans despite looking like typos. Overlap alone could
not settle Manang/Marang at all, because Marang's survey does not close and so
has no polygon to compare. Only the survey team could close that one, which is
why §2 treats name matching as a flagging step and never as a correction.

Any future pair should go the same route: flag by similarity, test by overlap,
confirm with the team before merging.

### 6.3 Borori / Darekikol — resolved: a dispute, mapped as recorded

Two differently-named Zone 7A clans share **286.8 ha — 49.3% of one and 46.5%
of the other**.

**Resolved 2026-08-16: this is a genuine dispute, and both boundaries are
mapped exactly as recorded.** Neither is adjusted, clipped or reconciled. The
overlap is the finding, not an error to remove.

This sets the rule for overlaps generally (§6.8).

### 6.4 Non-boundary surveys — resolved: out of the distance totals

Three surveys are not clan land boundaries but are being processed as though
they were:

| Type | Zone | Clan Steward | Tracks | Length | Polygon built |
| --- | --- | --- | ---: | ---: | --- |
| Road | 7A | Paul Digori | 13 | 4.3 km | none |
| Sacred Site | 2 | Millinton Beso | 3 | 10.6 km | 466.5 ha, inferred |
| Steward Block | 7B | Ruth Makisa | 1 | 6.3 km | 237.3 ha, inferred |

**Resolved 2026-08-16: excluded from the boundary distance totals.** Distance
now counts land boundary only. The three keep their own reporting — sacred sites
in §4.10, the road and steward block in the layers and query pack — but they no
longer inflate the boundary figures.

The same decision removes the **walk to the boundary**. A surveyor walks in to
where the boundary starts and out again at the end; those dead-end legs are
real distance covered but they are not boundary. `smooth_tracks.spur_length`
measures them per survey and takes them out.

Both together change the headline distance:

| Measure | Distance |
| --- | ---: |
| Raw, as recorded | 1,327.2 km |
| Smoothed | 1,112.9 km |
| **Boundary — non-boundary surveys and access legs removed** | **924.5 km** |

| Zone | Walked (km) | Boundary (km) |
| --- | ---: | ---: |
| Zone 2 | 320.5 | 257.4 |
| Zone 3 | 48.7 | 42.0 |
| Zone 6 | 151.6 | 125.9 |
| Zone 7A | 73.7 | 53.9 |
| Zone 7B | 282.3 | 230.6 |
| Zone 8 | 236.1 | 214.8 |
| **Total** | **1,112.9** | **924.5** |

### 6.5 Survey dates — resolved: two different dates, both correct

**None** of the 52 surveys carrying GPS timestamps has a file-name date that
matches the tracks inside it. File names give `14July2026` (48 surveys) while
the tracks themselves were recorded between **2025-04 and 2026-08**, and 20
surveys contain tracks spanning more than one month.

**Resolved 2026-08-16: both dates are right, they just mean different things.**
The GPS timestamp is when the ground was walked; the file-name date is when the
archive was collated and delivered. Neither is an error and no correction is
needed.

Two things follow. The `survey_date` attribute is a **delivery** date, not a
survey date, and should be read that way. And the data covers a **16-month
survey campaign** running 2025-04 to 2026-08, not a single July 2026 round —
which is worth knowing when comparing boundaries that may have moved between
walks.

The query is withdrawn from the pack.

### 6.6 Zone 3 is an outlier

Zone 3 has 8 surveys and 48.7 km walked but yields only **2 polygons and
76.2 ha** — by far the lowest return of any zone. Per-survey track counts are
1–4, against a median of 18 across the dataset. This looks like partial
delivery or an incomplete survey round rather than a processing artefact, but
it should be checked against what was expected for that zone.

### 6.7 Smoothing — resolved: keep it

The 20 m resampling was specified; the 3-point moving average on top was not,
and removes a further 7.8% of length. **Confirmed 2026-08-16 as correct to
keep.** Distances in this document are therefore smoothed throughout.

### 6.8 Overlapping clan areas — resolved: never combined, never reconciled

**Clans are never merged and their surveys are never combined.** Overlaps
between clan areas are a permanent feature of the tenure here, not an error to
resolve, and every boundary is mapped as recorded.

This reverses an earlier line of analysis. A `clan_combine` step had been built
to test whether a clan's several surveys were complementary arcs of one
boundary — it found that combining Nituri's three surveys would yield 5,124 ha
where separately they yield none. That step is **removed**, and the consequence
is accepted: a clan whose surveys do not individually close simply has no
mapped area.

Overlaps are still measured and reported (§4.9) — they are a finding worth
having. They are no longer raised as queries.

### 6.12 What goes on a clan's own page — resolved: their survey, not their neighbours'

These pages are printed and taken to the clan they are about. That constrains
what may appear on them, and the constraint is not cosmetic.

**Neighbouring clans are named, never drawn.** An earlier version rendered
each neighbour's mapped land in grey and shaded the ground both had walked
around in red. Put in front of elders, that is a picture of a dispute — and
in most cases the honest description is that both surveys are unfinished. The
map now shows one clan's work, the stretches nobody has walked, and the
neighbours' names placed where each neighbour lies.

**Unfinished is not disputed.** Where a boundary does not close, the word
used throughout is *incomplete*. Any overlap involving such a boundary is
stated as provisional, because the overlap is measured against the straight
lines bridging the unwalked stretches rather than against anything anyone
walked or said.

**Two queries were withdrawn.** One asked whether ground two clans had both
walked around was "disputed, shared by agreement, or recorded wrongly"; the
other asked whether a shared edge was agreed. Neither is answerable from this
data, and both invite an argument the survey has no business starting. What
remains are practical requests: walk the missing stretches, confirm the
parcels, say what runs along a gap.

The overlap figures themselves are unchanged and still reported per clan
under "Ground also claimed by another clan". The finding is kept; the framing
that turned it into an accusation is not.

### 6.9 How close is too close — resolved: 100 m, as a separate category

Two lines recorded within **100 m** of each other are the same line as far as
the ground is concerned. GPS mapping, field conditions and the vagaries of the
terrain make 100 m inconsequential here.

Overlap is therefore reported **twice, never once**: strictly, for the exact
numbers, and again with strips narrower than 100 m removed, for the figure
that reflects what the field would recognise as two clans claiming the same
ground. Neither replaces the other, and both appear side by side in every
document (§4.9).

The allowance turns out to change little — 78 ha of 4,708 ha, and 19 of 50
pairs — which is precisely what makes it worth having made.

### 6.10 Land held in more than one piece — resolved: supported throughout

A clan may hold separate, non-contiguous areas of land, and the pipeline keeps
all of them (§4.8). The area reported for a clan is the sum of its parcels,
each parcel is drawn, and the count appears on the clan's page with a query
asking whether it is right.

### 6.11 Deari and Nui — resolved by measurement: a shared line, not an overlap

Asked directly: do the lines for Deari and Nui overlap?

They do not overlap in area, because neither walk closes and neither has a
polygon. What they have is a **shared line**: 94% of Deari's 13.1 km runs
within 100 m of Nui's, the two cross 292 times, and Deari's whole recorded
extent lies inside Nui's. Under the 100 m rule (§6.9) that is one boundary
recorded by two clans, and it counts as agreement.

Nui walked 8.4 km beyond Deari's line. Whether that is Nui's own further
boundary is a question for the two clans, and it is raised on both pages.



### 4.11 Landform: watercourses and ridgelines (`hydrology.py`, `landform.py`)

No hydrology dataset is reachable (§8), so both networks are derived from the
Copernicus DEM. Streams: depressions filled, D8 routing, channels above 1,000
upstream cells (~0.9 km² of drainage). Ridges use the same machinery on the
**inverted** surface — invert the elevation and crests become the channels of
the inverted DEM — then keep only lines with positive topographic position
index, since inverted routing will otherwise trace a line down an even slope
where no ridge exists.

Two artefacts had to be handled in both. The DEM window reaches the Solomon
Sea, where flat zero elevation gives D8 no gradient and it fans into parallel
diagonal lines; the sea is masked before routing. Flow still escapes along the
masked edge, so a second pass drops channels sampling at sea level —
unmistakable once measured, sinuosity 1.00 against a real-channel median of
1.23.

Result: **2,178 stream segments (3,527 km)** and **1,773 ridge segments**,
clipped to the MCA + 10 km.

Each survey's walk is then split by what it runs within 50 m of:

| Follows | Share of 1,113 km |
| --- | ---: |
| Watercourses | 18.8% |
| Ridgelines | 11.7% |
| Both at once | 0.2% |
| **Either** | **30.3%** |
| Neither | 69.7% |

**These shares must be read against chance, not on their own.** Drainage here
is dense enough that any line picks up correspondence for free. Displacing the
same tracks 400 m and re-measuring gives the chance rate:

| Follows | Real | By chance | Ratio |
| --- | ---: | ---: | ---: |
| Watercourses | 19.8% | 9.5% | **2.1×** |
| Ridgelines | 12.2% | 7.8% | **1.6×** |

So the correspondence is real but roughly half the headline figure is what any
line would score. The genuine signal is about **10 points of water-following
and 4 points of ridge-following**, not 30%.

The unmatched majority is not following some other landform: its topographic
position index is a median −1.9 m against a landscape median of −0.3 m, and
22.5% of it sits within 5 m of the local mean against 22.0% for the landscape
as a whole. In other words it sits mid-slope, statistically indistinguishable
from arbitrary ground. What it actually follows — paths, garden edges, agreed
lines, vegetation changes — cannot be determined from a DEM.

### 4.12 Clans tested separately and combined (`clan_combine.py`)

A clan walked by several stewards may be several independent accounts of one
boundary, or one boundary split between stewards. The two need opposite
treatment, so every multi-survey clan is assessed both ways.

The discriminator is **duplication**: the share of walked distance running
within 20 m of another steward's track. It separates the two populations
cleanly, and the outcome follows it:

| Duplication | Reading | Effect of combining |
| --- | --- | --- |
| Low (Nituri 2.3%, Gumuri 1.3%, Murai 0.0%) | Complementary arcs of one boundary | Large gains — Nituri +5,124 ha |
| High (Rondi 99.2%, Riribudeh 98.8%, Wohukol 94.8%) | Independent accounts of the same ring | Combining *loses* area — merging two accounts confuses the geometry |

**Nothing is combined automatically.** Whether several surveys describe one
boundary is a question about the clan, not the geometry. 20 clans have more
than one survey; combining changes the area for 5, and would add **7,216 ha**
that no separate survey yields. Mariura is a caution: 100% duplication yet
+855 ha, which is a false positive of the kind the duplication figure exists to
catch.

### 4.13 Who walked, and when (`scripts/stewards.py`)

The record of the work, kept apart from the record of the land. Every figure
comes from the GPS, not from a file name.

Dates are recovered in this order:

1. the `Created` timestamp the recording app writes into each track's
   description — 528 of 600 tracks;
2. a date at the start of the track name, the naming convention on some
   devices — a further 71;
3. nothing, for **1 track**, which is counted in every distance figure but in
   no day count, and named in the document so it can be chased.

The `survey_date` attribute is deliberately unused here. §6.5 settled what it
is: the date the archive was collated and delivered. Every file in a delivery
carries the same one, so it says nothing about when a boundary was walked.

Two limits worth stating. A track is dated by when it was **created**, so a
walk running past midnight is counted entirely on the day it began. And the
distance is measured along the smoothed track, which is the ground the
receiver recorded, not the distance the steward's legs covered — in this
terrain the latter is materially greater.

Current record: **67 stewards, 233 steward-days across 118 distinct days on
the ground**, between 2025-02-18 and 2026-08-13, covering 1,113 km. Seven
steward-days record more than 25 km, which is a long way on foot here; those
are listed as queries rather than assumed wrong, since the two ordinary
explanations — a receiver left running during vehicle travel, or one track
saved across more than one day — can only be settled on site.

### 4.13b What the field tells us (`data/reference/field_notes.json`)

The stewards know things no receiver records. This file is where those
accounts live, keyed by survey unit, carried onto the clan's page under "From
the field" and into the clan's GPX so the steward reads it on the handheld.

**Nothing here changes a geometry or a figure.** A river named as a boundary
is knowledge; drawing it would be this pipeline inventing a boundary rather
than recording one.

Two kinds of entry:

- **Per clan** — what the field says about that clan's boundary. Savasi's
  eastern border is the Baraje river, and the mapping is unfinished at both
  ends. The recorded line supports the first: Savasi's main 3.74 km piece runs
  40% along a watercourse in the terrain model at a 50 m tolerance.
- **Standing** (`_standing`) — advice that constrains what the pipeline may
  ask for, and therefore has to reach the query generator rather than just the
  page.

#### Large rivers are not walkable, so nobody is asked to walk one

The first standing entry. Boulders, rapids and steep drops make a large river
physically difficult and unsafe to follow on foot, so a gap along one is not a
gap anyone should be asked to close by walking. Where the boundary is a large
river the survey team will complete that stretch by editing, and **how to draw
a robust river boundary is an open decision, not yet made**.

A clan marked `"river_boundary": true` therefore gets a different query. The
generator would otherwise have asked Savasi to walk a set of rapids, which it
did in v1.10 before this was recorded. What it asks instead is the thing that
would actually help: where the river stops being the boundary, at each end.

This is the second time an auto-generated query had to be withdrawn for asking
something the data could not support (§6.12 was the first). Both came from the
field looking at the document, which is the argument for sending it.

#### Asking what a gap is (`scripts/gap_map.py`)

A gap can be three different things and only the field knows which: ground not
yet walked, ground that **cannot** be walked, or a straight line the clan is
content with. They need opposite treatment — a job for a steward, a job for an
editor, or nothing at all — and until they are told apart the pipeline calls
them all unfinished survey.

`gap_map.py` puts the question in an answerable form: the walked line in grey,
every gap in pink and **numbered**, with lengths and how much of each follows
a watercourse in the terrain model. The reply comes back as "gap 3 is the
Jarahe gorge, join it straight" and is recorded against that number.

The water share is corroboration only. The drainage is modelled from a 30 m
DEM, not surveyed, so a high share is a reason to ask whether a gap is a river
and never a reason to assert that it is.

**Use `--steward` when the field annotated one steward's printout.** The gaps
in a joined survey include the lines joining one steward's walk to another's,
and those are not features on the ground. Manuvoora shows why: the joined
survey has 11.4 km of gap, but 7.9 km of that is two long diagonals tying
Egobeyas Kuarisi's walk to Granville Nepo's. His own walk has 7.6 km of gap in
seven pieces, and those are the ones his annotations describe.

### 4.14 Giving the survey back (`scripts/clan_gpx.py`)

One GPX file per clan, written to `output/gpx/`, for the Clan Stewards who
walked it to load onto the phone or handheld they mapped with. The point is
that a steward should be able to see on the ground what the office sees.

Each file holds three kinds of thing, kept apart deliberately:

| In the file | Named | What it is |
| --- | --- | --- |
| Track per steward | `Tuoko - Kaupa Dota` | What was walked, after smoothing |
| Track per gap | `GAP 3 OF 8 - NOT WALKED - 2.31 km` | The straight line between two loose ends |
| Waypoint pair per gap | `GAP 3 OF 8 START` / `... END` | Where the walking stopped, to navigate to |

The waypoints are the useful part. A gap drawn as a line tells a steward that
something is missing; a waypoint lets them go to the exact spot and carry on.
Every gap track and waypoint carries the same description in full: *this
straight line is not a boundary — it joins the two ends so the shape can be
closed on paper*.

**Gaps under 100 m (`--min-gap`) are not marked.** Two track ends that close
are the same place to anyone standing there, and sending a steward to walk
30 m they have already walked wastes their time while burying the gaps that
matter. Of 221 joins in the current data, 186 clear 100 m, and those account
for 266.6 km of the 268.3 km.

That 266.6 km is larger than the 169.7 km of bridges in the polygon layer
(§4.8), and deliberately so: the polygon layer holds only the surveys complete
enough to give an area, while a clan whose walk is too open for that still
needs to know where its gaps are — arguably more than anyone.

Files are GPX 1.1, element order validated (metadata, waypoints, then tracks),
and pass through `dataio.publishable()` like every other shared output, so no
sacred site appears in one.

### 4.15 Documents, and how they are versioned (`scripts/build_reports.py`)

Two Word documents are generated, both from `output/report/*.json` and
nothing else, so a figure in the text and a figure on a map cannot drift
apart — they come from the same run:

| Deliverable | Contents |
| --- | --- |
| `Managalas_Clan_Land_Mapping_v<version>_<date>.docx` | Results, a page per clan, queries per clan |
| `Managalas_Steward_Days_v<version>_<date>.docx` | Who walked, on which days, how far |
| `output/gpx/<Clan>_<Zone>.gpx` | The survey back to the clan, gaps marked (§4.14) |

The version lives in `docs/VERSION` and is bumped when the content changes
materially; the date moves on its own.

**The build refuses to reissue a version under changed data.** A version
number is a promise that two files with the same name hold the same thing,
and the pipeline rebuilds the documents as its last stage — so a new data drop
regenerates an already-issued version under its own name and breaks that
promise silently. It nearly did: the Savasi drop rebuilt v1.8 with 49 clans in
it while a 48-clan v1.8 was already circulating. `build_reports.py` now
records what each build rested on in `output/report/built.json` (clans,
surveys, units, boundary km, last walk) and stops with a diff if those move
without the version moving. `--force` overrides it. Both appear in the file name, on the
title page, and in the footer of every page, so a page photographed or
photocopied on its own still says which version it came from. **Earlier
builds are never overwritten** — that is the point of versioning the name.

Two details that matter more than they look:

* **Images keep their proportions.** The builder reads each PNG's real pixel
  dimensions out of its IHDR chunk and scales to fit a box, rather than
  forcing fixed width and height. Managalas is a particular shape and a
  document that deforms it is worse than one with no map at all.
* **Every clan starts on a new page**, so a single clan's pages can be taken
  out and discussed with that clan without the rest of the document going
  with them.

## 7. Raising queries with the field team

`scripts/queries.py` turns everything the data cannot settle into a numbered
query pack at `output/queries/`, each with its own map so the discussion on site
is about specific ground rather than a general concern.

Queries are **regenerated from the current data on every run**. A query the data
no longer supports simply stops being produced, so the pack never carries a
stale question, and a new round of surveys raises new queries automatically.
Resolved queries are recorded in §6 and their generator removed.

Categories raised, capped at five each so the pack stays answerable:
overlapping clan areas, boundaries close to completion, boundaries too open to
give an area, surveys that are not clan land boundaries, dates that disagree,
and zones returning little mapped area.

One rule matters more than the rest: **a systemic issue is one query, not many.**
The date discrepancy (§6.5) affects 52 surveys identically; raised per survey it
produced 40 near-identical queries and buried the five that needed a person to
think. It is now a single query with a summary.

Two categories were **retired** once settled: overlapping clan areas (§6.8, a
fact of the tenure rather than a question) and the file-name dates (§6.5, two
different dates both correct). Removing them took the pack from 20 queries to
**14**, which is the point — a pack carrying settled questions gets skimmed.

The pack opens with an index map, `Q00_index.png`, numbering every query on one
sheet so a reader can see where the work is before reading any of it.

## 8. Background data layers

What is available depends on where the work runs.

**In this processing environment**, outbound access is restricted. Tested and
blocked: OpenStreetMap tiles, Carto, ESRI World Imagery and Topo, OpenTopoMap,
the Protected Planet API, Overpass, OpenTopography and GADM. This is why the
static maps carry no aerial or street background — it is an environment limit,
not a choice, and it affects no measurement.

**Reachable, and now in use:** the Copernicus GLO-30 DEM on AWS S3
(`copernicus-dem-30m.s3.amazonaws.com`), open data needing no credentials.

`scripts/fetch_dem.py` reads it. Because the tiles are cloud-optimised GeoTIFF,
only the window covering the data is transferred rather than whole degrees —
tiles `S09/E148` and `S10/E148` are cropped and mosaicked to a single raster of
2,193 × 2,427 px covering **−1 m to 3,044 m** of elevation. A shaded-relief
render is derived from it (default light from the north-west at 45°, 1.5×
vertical exaggeration).

Both are written to `data/reference/dem/` and are **git-ignored**: they are
re-fetchable, and nothing in the pipeline requires them. A run without network
access still completes; the maps simply draw without terrain behind them.

Terrain now backs every static map, every query map, and the QGIS project (as
`Terrain hillshade`, on by default, with `Elevation (m)` available beneath it).
It is not merely decorative — it shows that mapped areas sit in the valleys
while the unmapped north and west of the MCA is rugged mountain, and it lets a
field discussion about an unclosed boundary refer to the ground between the two
open ends.

Re-fetch when new surveys fall outside the area already covered:
`python scripts/run_pipeline.py --fetch-dem`.

**Not yet done:** using the DEM analytically — checking whether boundaries
follow ridgelines or watercourses, which would corroborate them independently
of the surveys.

**In QGIS on your own machine** none of these restrictions apply. The generated
project already carries an OpenStreetMap XYZ layer, and any other XYZ or WMS
source can be added normally — ESRI World Imagery is the usual choice for
checking a boundary against visible ground features.

The MCA boundary itself is held locally at `data/reference/mca_boundary.kml`, so
nothing in the pipeline depends on a network at all.

## 9. Repeat runs

The work is expected to repeat as more surveys arrive. Drop new archives into
`data/raw/` and run:

```bash
python scripts/run_pipeline.py
```

Every stage rebuilds from the raw archives. No stage keeps state between runs
and none writes back to `data/raw/`, so a later round cannot be contaminated by
an earlier one and re-running is always safe.

**The audit is the safeguard against silent loss.** Each run reconciles counts
from the archives through to the polygons:

| Checked | Current |
| --- | ---: |
| Archives | 7 |
| Source layers found | 69 |
| Raw features | 601 |
| Features after merge | 601 |
| Features after clipping | 600 |
| Clipped out | 1 |
| Surveys in / out | 69 / 69 |
| Polygons built | 42 |
| Surveys without an area | 27 |

Any difference must be explained by a rule the pipeline states — an unreadable
archive, a track outside the clip distance, a survey too open to enclose an
area. Anything unexplained is reported as a **LOSS** and the run **exits
non-zero**, so a silent drop cannot pass unnoticed between rounds. Invalid or
null geometries in the output are treated the same way.

New zones, clans and stewards need no configuration: they are read from the
file names. Two things will need a human on each new round — confirming any
newly flagged clan-name similarities (§6.2), and answering the new queries in
`output/queries/`.

## 10. Not yet verified

- **The QGIS project has never been opened in QGIS.** No QGIS is available in
  the environment used for processing. The project file is validated
  structurally — well-formed XML, every datasource resolving to a real
  GeoPackage layer, category and symbol counts matching — but the first real
  open will be on a user's machine. Target version is 3.28.12-Firenze.
- **No ground truth.** Nothing here has been checked against an independent
  survey, a cadastral record, or anyone's knowledge of the boundaries. All
  verification to date is internal consistency.
- **Basemap tiles** could not be fetched in the processing environment, so
  static maps render without them. This does not affect any measurement.

## 11. Towards publication

This section exists because the work is intended to become a paper. It records
what is ready, and — more usefully — what is not.

### 11.1 What is in place

**Reproducibility.** `scripts/provenance.py` stamps every run into
`output/PROVENANCE.md` and `provenance.json`: library versions down to GEOS and
GDAL, the git commit, the SHA-256 of every input archive, the parameters in
force, and the headline results. If a figure changes between runs, comparing
archive digests says immediately whether the data moved or the code did.

**Citations.** Data sources and their licences, and the methods papers behind
the flow routing, depression filling and topographic position test, are held in
`provenance.py` and reproduced in every provenance record. Background reading
for the write-up sits alongside them — currently the two Manus *tambu* papers
(§4.10), which are the closest published precedent for treating clan-governed
restricted areas as conservation in Papua New Guinea.

**Method transparency.** Every parameter has a stated default and rationale
(§5); every threshold-dependent result is reported across a range rather than
at one value; and the landform findings carry a null model (§4.11) without
which they would be overstated by roughly half.

**One source for every stated figure.** The two Word documents are generated
from `output/report/*.json` and nothing else (§4.14), and that JSON is
generated from the same run of the pipeline that draws the maps. A number in a
paragraph and a number on a map cannot disagree, because neither was typed.
Each document carries its version, its date and the code revision it was built
from, on the title page and in the footer of every page.

**Sensitivity to the judgement calls, not just the parameters.** Where a
finding rests on a decision rather than a measurement — what counts as an
overlap, above all — the result is reported under both readings side by side
(§4.9, §6.9) rather than under the one that suits the argument.

**Negative and corrected results are recorded, not quietly dropped.** The
graph-based closure test that proved wrong, the spur-pruning bug that
manufactured false closures, the Web Mercator distances that overstated length
by 1.2%, the silent CSV failure — all are in §3, §4.2 and §4.7. A methods paper
is more useful for them, not less.

### 11.2 What is missing, and needs a decision

**Ethics and consent are not addressed at all.** This is the significant gap.
The data records *who holds which land*, by name, for 46 clans and 67 named
stewards, including sacred sites whose locations are given precisely. Before
any of it is published:

- On what basis was the survey data collected, and does that basis extend to
  publication?
- Have the clans and stewards consented to their boundaries, names and land
  areas appearing in a paper?
- **Sacred sites need separate consideration.** Publishing precise locations of
  sites of cultural significance may be actively harmful, and is a different
  question from publishing boundaries. The safe default is to report them only
  in aggregate.
- Are the disputed overlaps (§6.3) publishable while the dispute is live?
- The WDPA polygon carries its own terms of use for redistribution.

**None of this is a technical question and none of it is mine to answer.** No
consent or licence information came with the data, so nothing here assumes any.

**Not yet done for a paper:**

- No independent validation. Nothing has been checked against a cadastral
  record, an independent survey, or ground truth. All verification to date is
  internal consistency (§10).
- The area figures are 88% inferred (§4.8). That is stated everywhere it
  appears, and would need to lead any results section rather than follow it.
- Results live in six separate reports. A paper needs a single results table
  with a fixed figure and table numbering.
- The 16-month survey window (§6.5) means boundaries may have moved between
  walks. Nothing tests for that.
- Sample size for the closure findings is small: 7 closed boundaries out of 69.

### 11.3 The claim worth making

The defensible contribution is not the boundaries themselves — too much is
inferred, and none is independently validated. It is the **method**: that
community GPS boundary surveys can be assessed for completeness and
corroborated against terrain automatically, and that the corroboration must be
measured against a null model or it is largely an artefact of drainage density.
The 2.1× and 1.6× figures (§4.11), not the 30.3%, are the result.

## 12. Reproducing

```bash
pip install -r requirements.txt
python scripts/run_pipeline.py
```

That runs every stage in order and audits the result. To run a stage alone:

```bash
python scripts/inspect_data.py --summary --report output/data_profile.md
python scripts/smooth_tracks.py
python scripts/closure.py  --report output/closure_report.md
python scripts/polygons.py --report output/polygon_report.md \
    --map output/areas_mapped.png
python scripts/sacred_sites.py --report output/sacred_sites.md
python scripts/queries.py
python scripts/make_maps.py  --smoothed
python scripts/export_qgis.py --smoothed --with-boundary --with-polygons \
    --gpkg data/smoothed/mca_smoothed_qgis.gpkg
```

Outputs are git-ignored throughout, because all of them rebuild from
`data/raw/`. Only the raw archives, the reference boundary, the code and the
written reports are committed.
