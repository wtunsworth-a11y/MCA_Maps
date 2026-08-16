# Methods: cleaning and reviewing the clan boundary data

**Status: living document.** The processing is ongoing and this record is
updated as steps change. Every figure quoted here is reproducible by running
the scripts in `scripts/` against the archives in `data/raw/`.

Last updated: 2026-08-16.

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

The zone, clan and custodian are encoded in file names, not in the data. Two
conventions are in use, and both place the clan name beside the word "clan",
so that word anchors the parse:

```
Jethro_Akse_Asingi_Clan_Land_Boundary_Zone_2_14July2026
└─ custodian ─┘ └clan┘                  └zone┘ └─ date ─┘

manuvoora_clan_egobeyas_kuarisi_tracks_zone_6
└─ clan ─┘     └─── custodian ────┘     └zone┘
```

Which side holds the custodian is decided by whether any real name survives
after the anchor once structural words are removed. Clan names of two words
("Nupa Ora") are preserved — taking only the token adjacent to the anchor
truncated them in an earlier version.

Four files omit the zone from their name; these **inherit the zone from the
archive they arrived in**, which is authoritative.

Parsing reads the *original file stem*, not the layer name. Layer names are
truncated to 60 characters for GeoPackage table limits, which in one case cut
`14July2026` to `14July20`; the date regex then missed it and the fragment was
mistaken for part of a custodian's name.

Derived attributes on every feature: `clan`, `custodian`, `zone`,
`feature_type`, `survey_date`, `source_name`.

Dates with a two-digit year are reported as the raw text rather than having a
century invented for them. One source file name contains a typo, `14July206`,
which is passed through unaltered.

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

| Zone | Clans | Custodians | Surveys | Tracks | Length (km) |
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
recorded in several pieces, where every join counts. Chaining is greedy
(nearest open end first), which is an upper bound on the true minimum, so a
survey is never reported as closer to closure than it is. Under **10%** of the
distance walked (`--threshold`) counts as near closure.

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

| Zone | Clan | Custodian | Walked (km) | Area (ha) |
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

| Zone | Clan | Custodian | Walked (km) | Gap (m) | Gap % |
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

| | Polygons | Area |
| --- | ---: | ---: |
| Surveyed | 7 | 3,157.5 ha |
| Inferred | 35 | 23,178.8 ha |
| Dropped (gap > 50%) | 26 | — |
| Sum | 42 | 26,336.3 ha |
| Combined footprint (overlaps counted once) | | 20,789.8 ha |

The footprint is **9.7% of the MCA's 213,269 ha**. Note that **88% of the
mapped area is inferred**; only 3,158 ha rests on boundaries that actually
close.

**Mapped area by zone:**

| Zone | Polygons | of which surveyed | Area (ha) |
| --- | ---: | ---: | ---: |
| Zone 2 | 12 | 4 | 10,962.7 |
| Zone 3 | 2 | 0 | 76.2 |
| Zone 6 | 4 | 0 | 3,320.7 |
| Zone 7A | 3 | 0 | 1,656.6 |
| Zone 7B | 13 | 3 | 6,402.8 |
| Zone 8 | 8 | 0 | 3,917.3 |
| **Total** | **42** | **7** | **26,336.3** |

Areas sum to more than the 20,789.8 ha footprint because polygons overlap
(§4.9); the difference, 5,546.5 ha, is counted once in the footprint.

### 4.9 Overlap analysis (`scripts/polygons.py`)

Pairwise intersections are computed at both survey and clan level (clan
polygons being the dissolve of that clan's surveys). Reported as shared
hectares and as a share of each polygon's own area — asymmetric on purpose,
since a small polygon may be almost wholly inside a large one.

This serves two distinct purposes: locating where clans genuinely contest
ground, and testing whether two similar clan names are one clan recorded twice.

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

**3 named sites across 2 mapped units and 3 walks**, all Sukandi clan, walked by
Millinton Beso in Zone 2:

| Sites | Named | Walks | Walked (km) | Bridged (ha) | Hull (ha) | Bridged gap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Birezama + Bijanuri | 2 | 1 | 6.02 | 296.9 | 343.2 | 41% |
| Mitakin | 1 | 2 | 4.58 | 16.0 | 112.8 | 60% |
| **Total** | **3** | **3** | **10.60** | **312.9** | **456.0** | |

| Measure | Bridged | Hull |
| --- | ---: | ---: |
| Total area | 312.9 ha | 456.0 ha |
| Average per mapped unit | 156.4 ha | 228.0 ha |
| Share of Sukandi's 1,903 ha clan land | **16.4%** | **24.0%** |

Birezama and Bijanuri were walked together in one track and cannot be separated
afterwards, so they are reported as a single unit. The gap between the two
estimates for Mitakin — 16 ha bridged against 113 ha hull — shows how little the
walk constrains its area; that figure should not be quoted without the range.

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
| `--max-gap` | 50% | polygons | Inferred polygon rejected beyond this |
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

### 6.3 Borori / Darekikol

Two differently-named Zone 7A clans share **286.8 ha — 49.3% of one and 46.5%
of the other**. This is not a spelling artefact: both names are distinct and
both are separately mapped. It is either a genuine boundary dispute or a survey
error, and it is the single largest overlap between clans that are not
suspected duplicates. **This one needs a decision from someone who knows the
ground.**

### 6.4 Non-boundary surveys are currently included

Three surveys are not clan land boundaries but are being processed as though
they were:

| Type | Zone | Custodian | Tracks | Length | Polygon built |
| --- | --- | --- | ---: | ---: | --- |
| Road | 7A | Paul Digori | 13 | 4.3 km | none |
| Sacred Site | 2 | Millinton Beso | 3 | 10.6 km | 466.5 ha, inferred |
| Steward Block | 7B | Ruth Makisa | 1 | 6.3 km | 237.3 ha, inferred |

The sacred site is currently attributed to the Sukandi clan and contributes
466.5 ha to that clan's mapped area; the steward block has no clan and adds
237.3 ha to the Zone 7B total. **Decision needed:** whether these belong in the
boundary and area figures at all. They are tagged with `feature_type` and can
be excluded with a filter at any point.

### 6.5 Survey dates in file names are not survey dates

**None** of the 52 surveys carrying GPS timestamps has a file-name date that
matches the tracks inside it. File names give `14July2026` (48 surveys) while
the tracks themselves were recorded between **2025-04 and 2026-08**, and 20
surveys contain tracks spanning more than one month.

The reading is that the file-name date is when the files were compiled or
submitted, not when the boundary was walked. Until confirmed, the `survey_date`
attribute should not be relied on. Nothing downstream uses it, so no figure in
this document changes either way — but it is wrong as recorded, and it means
**the data covers a 16-month survey campaign, not a single July 2026 round**.

Raised as query Q19.

### 6.6 Zone 3 is an outlier

Zone 3 has 8 surveys and 48.7 km walked but yields only **2 polygons and
76.2 ha** — by far the lowest return of any zone. Per-survey track counts are
1–4, against a median of 18 across the dataset. This looks like partial
delivery or an incomplete survey round rather than a processing artefact, but
it should be checked against what was expected for that zone.

### 6.7 Smoothing is a judgement call

The 20 m resampling was specified. The 3-point moving average on top was not —
it removes a further 7.8% of total length. If the intent is to report distance
walked, that is arguably over-corrected; if the intent is to report boundary
length, it is closer to right. `--no-smooth` gives resampling only.

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

The current pack holds **20 queries**.

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

New zones, clans and custodians need no configuration: they are read from the
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

## 11. Reproducing

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
