# Document changelog

What changed between versions of the generated documents. The top section is
read by `scripts/report_data.py` and printed in the document itself, so a
reader can see what moved since the copy they already have.

Format: `## <version>` followed by bullets. Newest first.

## 1.3

- The people who walked these boundaries are **Clan Stewards**, and are named
  so throughout — in both documents, on every map, and in the data itself.
  The GeoPackage and CSV field is now `steward` rather than `custodian`, so
  QGIS projects and saved filters keyed on the old name will need repointing
  once.
- New: **a GPX file for each clan**, in `output/gpx/`, to give back to the
  stewards who walked it. Each holds the tracks they recorded, the gaps drawn
  as clearly-named straight lines, and a START and END waypoint at every gap
  so a steward can navigate to where the walking stopped and carry on. 186
  gaps are marked across 47 clans — 266.6 km still to walk.
- The companion document is now **Managalas Steward Days**.

## 1.2

- Clan maps no longer draw neighbouring clans' boundaries. A neighbour is
  named where it lies, and nothing more. Drawing another clan's line on this
  clan's page, with the ground between shaded as claimed by both, made a
  picture of a dispute out of a survey that is in most cases simply
  unfinished.
- Two queries removed. Neither should have been asked: both invited clans to
  take a position on ground their neighbours had also walked, when the data
  supports no such question and most of the boundaries involved are simply
  unfinished.
- "Boundary walked alongside another clan" is now **Neighbouring clans**.
  "Ground also claimed by another clan" stays as it was.
- Where a boundary is unfinished it is called **incomplete**, on the map and
  in the text, and any overlap involving it is stated as provisional — the
  unwalked stretches are straight lines, and the overlap is measured against
  those lines rather than against anything anyone walked.
- New section, "What an overlap here is not": an overlap in these figures is a
  statement about two surveys, not about two clans.
- Per-clan heading "Problems" is now "What the survey shows".

## 1.1

- Overlap between clans is now reported twice: strictly, and again with shared
  strips narrower than 100 m removed. Two lines recorded closer than that are
  the same line, not two claims. The allowance changes little, which is the
  point of making it.
- Where clans **agree** is reported for the first time: pairs whose recorded
  lines run within 100 m of each other. Deari and Nui share 94% of Deari's
  line and appear in no overlap figure at all.
- Corrected how disconnected pieces of a survey are joined into a ring. Taking
  a piece the wrong way round made the joining lines cross, enclosing two
  slivers instead of one block. Tuoko gains 394 ha, Bimkol gains an area it
  previously had none of, and every polygon is now geometrically valid.
- The straight lines nobody walked are drawn in pink on every map, written as
  their own layer, and reported per clan. They are not boundary.
- Every clan now has a map and its own page, with its neighbours and the
  ground they share drawn on it.
- Land held in more than one parcel is kept and counted; the parcel count
  appears on each clan's page.
- New document: **Managalas Walker Days** — who walked, on which days, and how
  far, from the GPS record rather than file names.
- Documents carry a version and date in the file name, on the title page and
  in the footer of every page. Earlier builds are never overwritten.
- Embedded maps keep their true proportions.

## 1.0

- First circulated document: survey results, per-clan detail and field
  queries. Issued without a version number.
