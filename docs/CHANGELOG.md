## 1.16 — 16 October 2026

* **A survey is a clan's boundary in a zone, and the count now says so.**
  The headline read "Surveys included: 72", which counted source files,
  while the same document said a pair of Clan Stewards is one survey. The
  two could not both be true. Surveys are now counted as clan-and-zone
  units — 51 — and the number of files they arrived in is given beside it.

* **The process narrative is out of the clan report.** The developer
  changelog was being printed into the document the clans read, along with
  paragraphs on how piece ordering affects the result and why two stewards
  are one survey. The facts stay; the reasoning about the software has gone
  back to this file, which is where it belongs.

* **Sacred sites are named for the landowners and the reviewer** (rule 19),
  with the notice that the report goes to them and to nobody else. The
  circuits stay out of the boundary network.

* **Each clan page shows the map that went to the clan**, under its review
  round and date, with the reviewer's reasoning. Rounds are kept, so a later
  round cannot overwrite what an earlier one showed.

# Document changelog

What changed between versions of the generated documents. The top section is
read by `scripts/report_data.py` and printed in the document itself, so a
reader can see what moved since the copy they already have.

Format: `## <version>` followed by bullets. Newest first.

## 1.15

- **A pair of Clan Stewards is one survey, and the clan maps now say so.**
  Stewards come in pairs and are not mapping different things: together they
  make one outer boundary and, where the clan has them, the inner boundaries
  of its sacred sites. The maps used to set each steward's walk against the
  joined result — "joining costs 1,236 ha" on Manuvoora — which reported a
  loss that never happened, because half a pair is not a survey and has no
  area to lose. Rondi shows what the pair is worth: Humphrey Poto's walk
  alone would need 11.5 km of straight line to close, Jefferson Amunisa's
  15.8 km, and the two together close exactly with nothing inferred.
- Each clan's map is now the finished thing: the land as mapped, each
  steward's line, any boundary derived rather than walked, and the stretches
  still not walked. Nothing else.
- **Manuvoora's map no longer carries a straight line across it.** The clan
  maps were built without the river route and the hand joins, so a boundary
  that closed in the figures still showed 11.4 km of pink on the page.

## 1.14

- **The land inside a sacred site's boundary goes back to the clan.** Where a
  Clan Steward walked around a named place, the circuit came through as a
  closed ring inside the outer boundary, and the pipeline cut the ground
  inside it out of the clan's land and drew a hole on the map at that spot.
  Both were wrong: the clan holds that ground, and the hole marked a location
  that is not ours to share. 253 rings are filled back in across 29 surveys,
  returning 24.6 ha.
- **New, shorter document: "The completed boundaries".** Only the clans whose
  boundary closes on the ground their stewards walked, with nothing inferred
  in the area. The full report carries all 49 clans and a finished map is
  hard to find among the unfinished ones.
- A steward's own spelling of "sacred site" is now read as one when counting.
  Recorded as a reading of the words, not a change to them: the raw files are
  never edited, and what any steward wrote about these places stays out of
  this document.

## 1.13

- **Every clan's page now says whether sacred sites were recorded.** The Clan
  Stewards were asked for the outer boundary and the sacred sites, so whether
  a clan recorded any is part of the answer, and "none recorded" is as much a
  finding as a count. Reported by number and area only; locations are not
  shared and appear on no map or layer.
- Counting them meant reading what the steward wrote. Only three features in
  the whole dataset are tagged as a sacred site. The usual way one was
  recorded is the way the rest of the land is recorded — the steward walked
  around the place and filed the circuit as a land boundary, because to a
  clan every named parcel inside the outer boundary has a boundary, and the
  boundary of a sacred site is a boundary. Those arrive as a closed ring
  inside the outer one, and only the steward's own note says what the ring
  is. Three clans recorded sacred sites: Juaiko, Rondi and Sukandi.

## 1.12

- **The closure test now asks whether the tracks enclose the ground.** It used
  to ask whether the main ring's perimeter was at least half the distance
  walked, which punished thorough work: Rondi's steward walked 59 km in 62
  pieces to map a 29.5 km boundary, the test wanted 29.49 km of ring, the ring
  was 29.47 km, and a survey that encloses 1,563 ha unaided was reported as
  inferred — with 12.43 km of straight line drawn across it that changed the
  area by nothing. Rondi is now reported as surveyed. Abuankol no longer is:
  its 0.5 km of track rings 1 ha where the inference rings 4.
- **Manuvoora — Zone 6 is closed.** The field told us the boundary follows a
  river with four waterfalls along it — Ija, Taram, Pururi and Parari — which
  cannot be walked; that stretch is traced along the modelled drainage. Four
  breaks in the recording, 443 m in all, are joined by hand. Both kinds of
  line are recorded apart from walked line and add no walked distance, because
  nobody walked them.

## 1.11

- **Nobody is asked to walk a river.** Large rivers are physically difficult
  and unsafe to follow — boulders, rapids, steep drops — so a gap along one is
  not a gap anyone should close on foot. Where the boundary is a large river
  the survey team will complete that stretch by editing, and how to draw a
  robust river boundary is an open decision, not yet made. Recorded as
  standing field advice and shown in "How to read the clan entries".
- Savasi's query changes accordingly. Version 1.10 asked whether the missing
  stretches could be walked; that stretch is the Baraje. It now asks the thing
  that would help instead — where the river stops being the boundary, at each
  end.

## 1.10

- New: **From the field** on a clan's page, for what the stewards tell us that
  the GPS cannot. It is kept in `data/reference/field_notes.json`, appears on
  the clan's page and in the clan's GPX so the steward sees it on the device,
  and changes no geometry and no figure.
- First entries, for **Savasi**: the eastern border of Savasi's clan land is
  along the Baraje river, and the mapping is unfinished at the northern and
  southern ends. The recorded line supports the first — the main 3.74 km piece
  runs 40% along a watercourse in the terrain model — but the river is not
  drawn as a boundary. Naming a river is knowledge; turning it into a line
  would be this pipeline inventing a boundary rather than recording one.

## 1.9

- New survey included: **Savasi**, Zone 3, walked by Oscar Isuni. Three tracks,
  4.0 km. It gives no area yet — the tracks are in three separate pieces with
  5.1 km of straight line needed to join them, more than was walked — so it
  appears as an unclosed line and its page says incomplete. The three gaps are
  marked in `Savasi_Zone_3.gpx` with waypoints at each end.
- Zone 3 now has 5 clans and 9 Clan Stewards across 52.8 km walked.

## 1.8

- The zone map is now titled **Zone Boundaries based on clan boundary
  mapping**, on the map itself and in the report. The previous name invited
  the reading that these are zone boundaries somebody surveyed. They are not:
  what a zone covers here is the sum of the clan surveys inside it, so its
  edge moves every time a clan finishes a boundary. A note under the map says
  so.

## 1.7

- New map: the same survey coloured by zone. Each zone gets one colour, used
  twice — a transparent wash for the land mapped and the same colour solid for
  the boundaries walked but not yet closed — so a zone reads as one thing
  whether its surveys finished or not. It answers how far each zone has got,
  which is the question anyone planning the next round of walking is asking.

## 1.6

- Simplified the overview map to three things. Every mapped area is now one
  transparent wash, whether the boundary closed on its own or the closure was
  inferred; the washes are not merged, so ground recorded by two clans reads
  darker and by three darker still. The overlap draws itself, with no separate
  colour for it. Boundaries walked but still too open to give an area are
  orange, and the stretches nobody walked stay as pink dashes.

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
