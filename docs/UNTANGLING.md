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

## 3. Ring order: the method that does most of the work

Everything in Band 4 above is a test — it tells you a drawn line is wrong
without telling you what to draw instead. This is the part that produces an
answer, and it came out of asking a simple question: can the pieces be put in
order around the boundary and all turned the same way, so that combining them
stops being a choice?

**The method.**

1. **Merge the pieces without noding them.** `linemerge` on the recorded
   pieces, *not* on their union. Unioning first splits every trace at every
   crossing — Riribudeh's two walks became 290 fragments that way, and the
   method produced 12 km of joining and nonsense.
2. **Orient each chain so it advances clockwise** about the survey's centre:
   take it in the stored direction if the bearing of its end is clockwise of
   the bearing of its start, reversed otherwise.
3. **Sort by the bearing of the start point.**
4. **The join is then the distance from each chain's end to the next chain's
   start.** No pairing decision, no nearest-neighbour search, nothing to get
   wrong about which end meets which.

**Do this per steward, never per pair.** A pair walking the same line
interleaves when ordered together — Riribudeh taken as a pair gives 17 joins
over 150 m and 7.94 km of joining, because going round the ring takes the two
parallel traces alternately. Run it on each steward separately and use their
agreement as the check on the result instead.

**What it gives on a compact clan.** Riribudeh:

| steward | chains | walked | joins under 50 m | 50–150 m | over 150 m |
| --- | ---: | ---: | --- | --- | --- |
| Prut Buitari | 12 | 10.37 km | 10 joins, 153 m | one, 83 m | **one, 387 m** |
| Unido Ose | 34 | 10.01 km | 31 joins, 310 m | two, 142 m | **one, 204 m** |

One real gap each, in the same place, everything else a recording restart.
The joins separate without anyone choosing a threshold. **397 ha from Prut's
ring and 398 ha from Unido's, computed independently** — against 372 ha from
the chord the pipeline drew and 403 ha from a buffer envelope. Two people who
never saw each other's files landing within 1 ha is a far better check on the
answer than any internal test.

### Its limit, and the fix

Ordering by bearing works only where the boundary is roughly **star-shaped
about its centre**. Manuvoora is a long sinuous strip, and there pieces at
opposite ends share a bearing and interleave — the same failure as ordering a
pair together, for the same reason:

| | joins under 50 m | over 150 m |
| --- | --- | --- |
| Riribudeh, a blob | 10, totalling 153 m | **1** |
| Manuvoora, a long strip | 3, totalling 20 m | **14** |

Egobeyas Kuarisi's fourteen "gaps" run 4,652 m, 3,914 m, 2,862 m — noise, not
a shortlist.

Note what still worked, though: the **area** came out at 1,087 ha from
Egobeyas and 1,054 ha from Granville Nepo, independently, against the
1,058 ha reached by a long detour through river routing and four hand joins.
The polygon is right even where the gap classification is not, because a
mis-ordered join between two pieces that are close together costs little
ground.

**The fix is to change the sort key**: order pieces by position along a
reference ring rather than by bearing. The buffer envelope of the walk
provides one for any shape, convex or not. Bearing can stay as the cheap case
where it works.

### What it does not do

It will not tell you that the river has four waterfalls on it, cannot be
walked, and is the boundary anyway. That came from the field, and it is what
made Manuvoora correct rather than merely closed. **Ring order gets to a
defensible area and a short list of real gaps. The conversation is still
where the boundary comes from.**

---

## 4. What the fixes were worth

Measured on this dataset, best first.

| fix | effect |
| --- | --- |
| Ring order, per steward (§3) | Riribudeh **397 and 398 ha** from two independent recordings, one real gap found, no chord; Manuvoora's area in one step |
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

## 5. Traps in the tooling itself

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

## 6. Still open

- **The scaffolding chord (§11).** 214 km of drawn line that does not join
  two open ends. Ring order (§3) solves it for compact clans and is not yet
  wired into the pipeline; the sort key still has to be generalised before it
  can be run on strip-shaped clans like Manuvoora.
- **Clans with too little walked to infer anything.** Zambiko reports 513 ha
  from 5.7 km walked, 79% of its outline drawn by the pipeline. The
  `--max-gap` limit is measured against the bridged ring rather than against
  what was walked, which is how it passes a test designed to reject it.
- **Mariura's duplicated file** (§1).
- **Sahirut's steward attribution** (§2).
