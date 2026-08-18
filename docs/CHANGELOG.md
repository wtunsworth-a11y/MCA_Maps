# Document changelog

What changed between versions of the generated documents. The top section is
read by `scripts/report_data.py` and printed in the document itself, so a
reader can see what moved since the copy they already have.

Format: `## <version>` followed by bullets. Newest first.

## 1.5

- Corrected the overview map. It matched tracks to closed boundaries on the
  file name while the polygon layer is keyed on the survey unit — one clan's
  walk within one zone — so 606 of 607 tracks were drawn purple as "walked but
  too open to give an area", including the 534 belonging to boundaries that do
  close. The map read as far more incomplete than the survey is. No figure was
  affected, only the map.

## 1.4

- New survey included: **Sahirut**, Zone 6, walked by Lenard Urami and Solomon
  Makanisa. Two files, seven tracks, 23.3 km. Sahirut is one clan with two
  stewards, not two clans.
- Flagged, not fixed: four tracks in Solomon Makanisa's file carry names
  crediting Lenard Urami — 15.2 km. The steward is taken from the file name,
  which is the only place most surveys record it, so where a track says
  otherwise the file name is not obviously right. Nothing has been reassigned;
  the question is listed in Managalas Steward Days for the field to settle.
- The file-name date parser now recognises the `Aug_26` form. Left unmatched,
  the month name survived into the parse and was read as somebody's name —
  `Lenard_Urami_Sahirut_Clan_Boundary_Zone_6_Aug_26` came out as clan "Lenard
  Urami Sahirut", steward "Aug". The date is kept as written, since a
  two-digit number after a month could be a day or a year and inventing either
  would be worse than reporting the text.

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
