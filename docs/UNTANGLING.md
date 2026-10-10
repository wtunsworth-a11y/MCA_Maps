# Untangling received GPS files

What arrives from the field is not a boundary. It is a folder of GPS files
recorded on phones and handhelds by Clan Stewards, in varying apps, over
months, by people who were mapping something the land itself does not mark.
Turning that into an area a clan can be shown — and a figure anyone can
defend — is most of the work, and almost none of it is the geometry people
expect.

This document records what went wrong in the Managalas Conservation Area
survey, what was done about it, and which of those fixes actually moved the
numbers. It is written so the next survey does not have to rediscover it.

**The governing fact.** These boundaries come from oral tradition. There are
no cairns, fences or beacons. A steward walks where the knowledge says the
line runs. That has two consequences which run through everything below: the
line is reproduced remarkably precisely, and where it is not, that is a
finding rather than an error.

---

## 1. What two stewards agree on

Clan Stewards work in pairs. Fourteen clans here were walked by a pair along
the same line, and the two recordings were compared point by point at 25 m
intervals.

| | separation between the two stewards' lines |
| --- | --- |
| median of the clan medians | **3 m** |
| median of the clan 90th percentiles | **12 m** |

For a boundary with nothing on the ground to follow, two people place it
within a few metres of each other almost everywhere. Any claim that these
lines are vague has to answer that number.

The exceptions are where the interest lies, because they are not spread
evenly — they are localised:

| clan | median | 90th percentile | maximum |
| --- | ---: | ---: | ---: |
| Deari — Zone 3 | 3 m | **2,832 m** | 3,260 m |
| Ginangi — Zone 7B | 3 m | 33 m | **1,847 m** |
| Nui — Zone 3 | 4 m | 20 m | 577 m |
| Wohukol — Zone 7B | 3 m | 10 m | 513 m |
| Manuvoora — Zone 6 | 4 m | 20 m | 338 m |
| Borori — Zone 7A | 3 m | 25 m | 280 m |

Two members of one clan agreeing to 3 m for most of a boundary and then
diverging by three kilometres on one stretch is worth far more than an
averaged uncertainty band. It says *where* the tradition is contested or
unclear. Average it away and the finding goes with it.

**A zero is not agreement.** Mariura's two stewards separate by 0 m across
634 sampled points. Identical geometry means one file was duplicated under
two names, not that two people walked. Check any clan whose pair agrees
perfectly.

---

## 2. The order to run the checks

Ordered by how much they changed the answer here, cheapest first within each
band. Run them in this order; several later checks are meaningless until the
earlier ones have been done.

### Band 1 — is the file what it claims to be?

Cheap, and everything downstream rests on it.

1. **Does the pair agree too well?** Separation of 0 m means a duplicated
   file. Mariura.
2. **Does the steward name match the file?** Four of Solomon Makanisa's
   tracks, 15.2 km, carry Lenard Urami's name in their attributes. Flag it;
   never reassign it yourself. It changes who is credited with the work and
   only the field can settle it.
3. **Does the filename parse?** `..._Zone_6_Aug_26` put the month into the
   steward field and produced a steward called "Aug" and a clan called
   "Lenard Urami Sahirut".
4. **Do two clans share a name?** Murai holds land in Zone 2 and Zone 7B,
   walked by different people in places far apart. Qualify the name or the
   two get joined into one impossible survey.
5. **Do the files share a schema?** `Name` and `name` from two apps; sixteen
   columns empty after the merge.

### Band 2 — is the geometry usable?

6. **Single-point parts and parts recording no line.** One steward's file
   held 43 of them; another had a feature that could not be recovered at all.
   Repair before measuring, and report what was dropped.
7. **Features outside the survey area.** One track clipped out here.

### Band 3 — is this one survey or two?

8. **A pair of stewards is one survey, not two.** Together they produce one
   outer boundary and, where the clan has them, the inner boundaries of its
   sacred sites. Setting one steward's walk against the other's and reporting
   the difference produces numbers that mean nothing: Manuvoora read
   "joining costs 1,236 ha" when neither half of the pair had an area to
   lose. Rondi is the honest version of the same comparison — Humphrey Poto's
   walk alone would need 11.5 km of straight line to close and Jefferson
   Amunisa's 15.8 km, while the two together close exactly, 1,569 ha, with
   nothing inferred.

### Band 4 — is each drawn line real?

A pipeline that bridges gaps will draw lines. Most of them here were wrong,
and three cheap tests find out which.

9. **Does the drawn line cross walked line?** A boundary cannot cross itself.
   Of 40 candidate joins generated naively on one clan, **18 crossed walked
   line** and were wrong on that ground alone. This is the cheapest test in
   the document and should be run on every line before it is drawn.
10. **Does the drawn line run alongside walked line?** If a "gap" lies within
    50 m of ground a steward walked, it is not a gap — the boundary is
    recorded there and only the ends need tying. **47.6 km of the 261.9 km
    the pipeline called "not walked" is of this kind, 18% of the total.**
    Kasaki was 100% of it: 1.34 km reported as unwalked with walked line
    beside every metre.
11. **Does the drawn line join two genuine open ends?** A break in a walk has
    an end of recorded line at each end of it. A line to a point mid-way
    along a piece is not spanning a break; it is the closing step's own
    scaffolding. This is the largest remaining fault in the dataset, and the
    most damaging: on Riribudeh it cut a chord across a boundary with no
    break in it, leaving 3.1 km of walked line — 16% of what the pair
    recorded — outside the clan's reported land, and taking in ground nobody
    had been near.

### Band 5 — what do the closed rings inside the boundary mean?

12. **A closed ring inside the outer boundary is a named place, not a hole.**
    To a clan, every named parcel inside the outer boundary has a boundary,
    and the boundary of a sacred site is a boundary. 284 such rings here.
    Treating them as holes cut **23.4 ha** out of land the clans hold and
    drew a ring on the map at exactly the spot whose location must not be
    shared.
13. **Read the descriptions.** Only three features in this entire dataset are
    tagged as a sacred site. The usual way one was recorded is as a
    `Land Boundary` walked around the place, with what it is written in the
    steward's own note — a secret site, a historical stone, an ancestors'
    cave. A redaction gate that reads `feature_type` will pass every one of
    them. **Geometry will not tell you what a ring is. The note will.**

### Band 6 — does the survey close?

14. **Ask whether the tracks enclose the ground, not how far anyone walked.**
    The test used here for a long time asked whether the main ring's
    perimeter was at least half the distance walked, and it punished thorough
    work: Rondi's steward walked 59 km in 62 pieces to map a 29.5 km
    boundary, the test wanted 29.49 km of ring, the ring was 29.47 km, and a
    survey enclosing 1,563 ha unaided was reported as inferred with 12.43 km
    of straight line drawn across it that changed the area by nothing.
    **It missed by twenty metres, and it missed because the steward had
    walked their own land.**

---

## 3. What the fixes were worth

Measured on this dataset, best first.

| fix | effect |
| --- | --- |
| Ask whether the tracks enclose ground (§14) | surveyed area 2,542 → **5,163 ha**; inferred share 92% → 85% |
| Order and orient the pieces before joining (2-opt) | Tuoko 3,282 → **3,676 ha**; Bimkol 0 → 158 ha; 36/36 polygons valid |
| Keep every parcel, not the largest | recovered an entire northern parcel for Wohukol |
| Fill interior rings (§12) | **24.6 ha** returned across 253 rings in 29 surveys; every sacred-site marking removed from the maps |
| Tie loose ends to the line beside them (§10) | Kasaki 1.34 km of false gap → **0**; closes on the walk |
| River routing where water cannot be walked | Manuvoora's four-waterfall stretch; 828 → 1,058 ha and closed |
| Count sacred sites from the linework, not the polygon | restored Rondi 5 and Juaiko 4 after filling destroyed the evidence |

**And one that was tried and rejected**, which is worth as much as the
others. Joining each loose end to its *nearest* open end more than halves the
bridging — 273.6 km down to 127.2 km — and destroys the survey doing it. It
encloses less ground on 48 of 49 surveys, and Egobeyas Kuarisi's walk goes
from 968 ha to nothing at all, because the nearest pair of ends is usually
the two ends of a single out-and-back leg. The function is kept in the
codebase, unused, with those numbers in its docstring. **A fix that shortens
the drawn line is not thereby a better fix. Measure the ground.**

---

## 4. Traps in the tooling itself

Faults that were not in the field data at all.

- **A replace rule that is too loose eats good data.** Adopting a derived
  segment replaced any stored segment within 50 m, so adopting one 25 m join
  silently deleted a different one 40 m away. Three of Kasaki's eight joins
  vanished and the polygon came out worse than before the fix. Sameness must
  mean near-identical geometry.
- **Derived line is not walked distance.** Counting it in `walked_km` made
  Manuvoora read 64.4 km against the 61.45 km its stewards actually walked.
- **Two reports built from two copies of the same rule will disagree.** The
  closure report and the polygon layer each had their own enclosure test and
  their own idea of what a gap was. One called Manuvoora open with an 11.4 km
  gap while the other called it closed.
- **A map can carry what a document redacts.** No steward's words about a
  sacred site reach any document — but the holes those circuits left were
  drawn on every clan map, which is the location itself.
- **A changelog is published.** An entry quoting a steward's wording about a
  sacred site put it straight into the report.
- **Fingerprint every issued version.** The pipeline will happily rebuild an
  already-issued version number under changed data.

---

## 5. Still open

- **The scaffolding chord (§11).** 214 km of drawn line that does not join
  two open ends. Riribudeh is the clearest case and the one with a known
  right answer. Removing the chord is easy; making the boundary follow the
  walk instead is not, and is not yet solved.
- **Clans with too little walked to infer anything.** Zambiko reports 513 ha
  from 5.7 km walked, 79% of its outline drawn by the pipeline. The
  `--max-gap` limit is measured against the bridged ring rather than against
  what was walked, which is how it passes a test designed to reject it.
- **Mariura's duplicated file** (§1).
- **Sahirut's steward attribution** (§2).
