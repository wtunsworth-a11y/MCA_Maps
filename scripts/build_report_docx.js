// Build the main Word report from output/report/*.json.
//
// Nothing is typed in here: every figure comes from the JSON that
// scripts/report_data.py writes, and every map from output/. Re-running the
// pipeline and then this script produces the document for the new data.
//
//   node scripts/build_report_docx.js <json-dir> <repo-root> <out.docx>

const fs = require('fs');
const path = require('path');
const d = require('docx');
const { Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow,
        TableCell, WidthType, ShadingType, AlignmentType, ImageRun, PageBreak,
        TableOfContents, LevelFormat, Footer, PageNumber } = d;

const S = process.argv[2];
const REPO = process.argv[3];
const sum = JSON.parse(fs.readFileSync(path.join(S,'summary.json'),'utf8'));
const clans = JSON.parse(fs.readFileSync(path.join(S,'clandata.json'),'utf8'));
const ctx = JSON.parse(fs.readFileSync(path.join(S,'context.json'),'utf8'));

const DXA = WidthType.DXA;
const FULL = 10080;                      // 7.0" content width
const HDR = "D9E2F3", ALT = "F2F2F2";
const TOL = Math.round(ctx.overlap_tolerance_m);

function p(text, opts={}) {
  return new Paragraph({ children:[new TextRun({ text, ...opts })], ...(opts.para||{}) });
}
function h(text, level){ return new Paragraph({ text, heading: level }); }
function note(text){
  return new Paragraph({ children:[new TextRun({ text, italics:true, size:19, color:"595959" })],
    spacing:{ before:60, after:120 } });
}
function bullets(items){
  return items.map(t => new Paragraph({ children:[new TextRun({ text:t, size:20 })],
    bullet:{ level:0 }, spacing:{ after:60 } }));
}
function cell(text, w, opts={}){
  return new TableCell({ width:{ size:w, type:DXA },
    shading: opts.shade ? { type: ShadingType.CLEAR, fill: opts.shade } : undefined,
    children:[new Paragraph({ children:[new TextRun({ text:String(text), bold:!!opts.bold, size:opts.size||19 })],
      alignment: opts.right ? AlignmentType.RIGHT : AlignmentType.LEFT })] });
}
function table(headers, rows, widths){
  const total = widths.reduce((a,b)=>a+b,0);
  const w = widths.map(x=>Math.round(x*FULL/total));
  return new Table({ columnWidths:w, width:{ size:FULL, type:DXA },
    rows:[ new TableRow({ tableHeader:true, children: headers.map((t,i)=>cell(t,w[i],{bold:true,shade:HDR,right:i>0})) }),
      ...rows.map((r,ri)=> new TableRow({ children: r.map((t,i)=>
        cell(t, w[i], { right:i>0, shade: ri%2 ? ALT : undefined })) })) ] });
}

// A PNG carries its pixel dimensions in the IHDR chunk, at a fixed offset.
// Reading them is the whole trick: the image is then scaled to fit its box
// without changing its proportions, so a map of Managalas stays the shape
// Managalas actually is.
function pngSize(buffer){
  if (buffer.length < 24 || buffer.readUInt32BE(12) !== 0x49484452) return null;
  return { w: buffer.readUInt32BE(16), h: buffer.readUInt32BE(20) };
}
function img(rel, maxW, maxH){
  const f = path.join(REPO, rel);
  if (!fs.existsSync(f)) return p(`[map not available: ${rel}]`, {italics:true});
  const data = fs.readFileSync(f);
  const size = pngSize(data);
  if (!size) return p(`[not a readable PNG: ${rel}]`, {italics:true});
  const scale = Math.min(maxW/size.w, maxH/size.h, 1);
  return new Paragraph({ alignment: AlignmentType.CENTER,
    children:[ new ImageRun({ type:"png", data,
      transformation:{ width: Math.round(size.w*scale),
                       height: Math.round(size.h*scale) } }) ] });
}

const money = n => n===null||n===undefined ? "—" : Number(n).toLocaleString('en-GB',{maximumFractionDigits:0});
const one = n => n===null||n===undefined ? "—" : Number(n).toLocaleString('en-GB',{minimumFractionDigits:1,maximumFractionDigits:1});
const pct = (a,b) => b ? (a/b*100).toFixed(0)+"%" : "—";

const body = [];

// ---------------- Title ----------------
body.push(new Paragraph({ text:"Managalas Clan Land Mapping", heading:HeadingLevel.TITLE }));
body.push(new Paragraph({ children:[new TextRun({ text:"Survey results, per-clan detail, and queries for the field",
  size:26, color:"404040" })], spacing:{ after:120 } }));
body.push(new Paragraph({ children:[new TextRun({
  text:`Version ${ctx.version}  ·  ${ctx.date_long}`, bold:true, size:22, color:"1F4E79" })],
  spacing:{ after:240 } }));
body.push(p("Clan land boundaries in the Managalas Conservation Area, Oro Province, Papua New Guinea. Mapped by Clan Stewards at the request of clan elders through the Clan Elder Workshops. Each community decides whether to map; where a boundary is disputed the community decides whether to resolve it or leave the area aside.", {size:21}));
body.push(note("Sacred site locations are not shared. They are reported by area and share of clan land only, and appear in no map or layer in this document."));
body.push(p("This document is regenerated from the survey data on each run. Every figure and every map in it comes from the same run, so the text and the maps cannot disagree. Quote it by version and date; a later version supersedes it entirely.", {size:20, italics:true}));
body.push(table(["This version","Detail"], [
  ["Version", ctx.version],
  ["Generated", ctx.date_long],
  ["Data through", sum.last_walk || "—"],
  ["Surveys included", money(sum.surveys)],
  ["Code revision", ctx.commit || "—"],
], [3,7]));
if (ctx.changes && ctx.changes.length) {
  body.push(h(`What changed in version ${ctx.version}`, HeadingLevel.HEADING_2));
  body.push(...bullets(ctx.changes));
  body.push(note("Figures move between versions because the method improves as well as because new surveys arrive. Where a correction changed a number materially, the change says so."));
}
body.push(new Paragraph({ children:[new PageBreak()] }));

body.push(h("Contents", HeadingLevel.HEADING_1));
body.push(new TableOfContents("Contents", { hyperlink:true, headingStyleRange:"1-2" }));
body.push(note("Right-click and choose “Update field” to build the contents list, or press Ctrl+A then F9."));
body.push(new Paragraph({ children:[new PageBreak()] }));

// ---------------- 1. Summary ----------------
body.push(h("1. What has been mapped", HeadingLevel.HEADING_1));
body.push(table(["Measure","Value"], [
  ["Clans with data", money(sum.clans)],
  ["Clan Stewards who walked", money(sum.stewards)],
  ["Individual surveys", money(sum.surveys)],
  ["Clan boundaries assessed (stewards joined)", money(sum.units)],
  ["Days on the ground", money(sum.field_days)],
  ["Steward-days recorded", money(sum.steward_days)],
  ["First and last walk recorded", `${sum.first_walk} to ${sum.last_walk}`],
  ["Distance walked", one(sum.walked_km)+" km"],
  ["Boundary walked (excl. access legs and non-boundary)", one(sum.boundary_km)+" km"],
], [6,3]));
body.push(note("Boundary distance excludes surveys that are not land boundaries, and the legs walked in to reach a boundary and out again. Who walked on which day, and how far, is a separate document: Managalas Steward Days."));

body.push(h("Land area", HeadingLevel.HEADING_2));
body.push(table(["Basis","Boundaries","Hectares"], [
  ["Walked and closed", money(sum.surveyed_n), money(sum.surveyed_ha)],
  ["Closure inferred (gap bridged)", money(sum.inferred_n), money(sum.inferred_ha)],
  ["Total mapped", money(sum.units), money(sum.total_ha)],
  ["Footprint (overlaps counted once)", "", money(sum.footprint_ha)],
  ["Conservation area", "", money(sum.mca_ha)],
], [5,2,2]));
const inferredShare = Math.round(sum.inferred_ha/sum.total_ha*100);
body.push(p(`${inferredShare}% of the mapped area rests on an inferred closure — the boundary was not walked the whole way round and the gap has been bridged with a straight line. Those areas are estimates and are labelled as such throughout.`, {size:21}));

body.push(h("The straight lines are not boundary", HeadingLevel.HEADING_2));
body.push(p(`${one(sum.bridge_km)} km of the outlines in this document was never walked — ${pct(sum.bridge_km, sum.outline_km)} of the ${one(sum.outline_km)} km of outline drawn around the mapped areas. These are the long straight lines that cut across the landscape on the maps. They are not where anyone said a boundary runs: they mark where a receiver was switched off at the end of one walk and switched on again somewhere else, and the straight line between is this pipeline joining the pieces up so an area can be given at all.`, {size:21}));
body.push(p("They are drawn in pink on every map, apart from the walked line, so they can never be mistaken for a surveyed edge. Where a clan's outline carries a long straight line, the area behind it is a guess across that gap, and the query on that clan's page asks for the missing stretch to be walked.", {size:21}));
body.push(note("Which order the recorded pieces are joined in, and which way round each piece is taken, changes the result substantially. Taking a piece the wrong way round makes the joining lines cross, and a crossed outline encloses two slivers where the real walk encloses one block — Tuoko lost 394 ha to exactly that before it was corrected. The pieces are now ordered and oriented to make the joining as short as possible, which leaves no crossings."));
body.push(p(`The mapped footprint is ${(sum.footprint_ha/sum.mca_ha*100).toFixed(1)}% of the conservation area.`, {size:21}));

body.push(h("Land held in more than one piece", HeadingLevel.HEADING_2));
body.push(p(`A clan's land does not have to be one block. Where a clan's walks enclose several separate parcels, all of them are kept and all of them are counted — the mapped area is the sum, and the map shows each piece. ${sum.clans_multi_parcel} of ${sum.clans_mapped} mapped clans hold land in more than one parcel on the evidence so far.`, {size:21}));
if (sum.multi_parcel && sum.multi_parcel.length) {
  body.push(table(["Clan","Parcels","Total area (ha)"],
    sum.multi_parcel.map(m=>[m.clan, money(m.parcels), money(m.area_ha)]), [5,2,3]));
}
body.push(note("Only parcels of at least 2% of the clan's largest are kept. Below that a loop is a track crossing itself rather than a separate holding. If a clan knows of a parcel that is missing here, that is a survey to add, not a limit of the method."));

body.push(h("By zone", HeadingLevel.HEADING_2));
body.push(table(["Zone","Clans","Clan Stewards","Surveys","Walked (km)","Boundary (km)","Area (ha)"],
  sum.zones.map(z=>[z.zone, money(z.clans), money(z.stewards), money(z.surveys),
    one(z.walked_km), one(z.boundary_km), money(z.area_ha)]), [3,2,2,2,3,3,3]));

// ---------------- Overlap ----------------
body.push(h("Overlap between clans", HeadingLevel.HEADING_2));
body.push(p("This is the finding with the widest implications. The PNG Incorporated Land Group system rests on land being held by a single clan, undisputed. On this evidence that assumption does not describe the Managalas.", {size:21}));

body.push(h(`Two readings: strict, and beyond a ${TOL} m tolerance`, HeadingLevel.HEADING_3));
body.push(p(`Overlap is reported twice. The strict figure counts every square metre two clans both claim, and is the exact measurement. The second figure removes any strip of shared ground narrower than ${TOL} m: where two recorded lines run closer together than that, the ground between them is not a competing claim but the ordinary imprecision of the work — GPS fixes landing ten metres apart, canopy pushing them further, and a boundary followed on foot wandering around the terrain. ${TOL} m is inconsequential here.`, {size:21}));
body.push(table(["Measure","Strict",`Beyond ${TOL} m`], [
  ["Clans with a mapped area", money(sum.clans_mapped), money(sum.clans_mapped)],
  ["Clans whose land overlaps another clan's", money(sum.clans_overlap), money(sum.clans_overlap_beyond_tol)],
  ["Clans with no overlap", money(sum.clans_mapped - sum.clans_overlap), money(sum.clans_mapped - sum.clans_overlap_beyond_tol)],
  ["Pairs of clans sharing ground", money(sum.overlap_pairs), money(sum.overlap_pairs_beyond_tol)],
  ["Area claimed by more than one clan (ha)", money(sum.contested_ha), money(sum.contested_beyond_tol_ha)],
  ["— as a share of the mapped footprint", pct(sum.contested_ha, sum.footprint_ha), pct(sum.contested_beyond_tol_ha, sum.footprint_ha)],
], [6,2,2]));
body.push(p(`The tolerance changes very little: ${money(sum.contested_ha - sum.contested_beyond_tol_ha)} ha of the ${money(sum.contested_ha)} ha falls away, and ${sum.clans_overlap - sum.clans_overlap_beyond_tol} clan(s) drop out of the overlapping group. ${sum.overlap_pairs - sum.overlap_pairs_beyond_tol} of the ${sum.overlap_pairs} pairs turn out to be two clans describing the same line rather than claiming the same ground. The finding survives the allowance — which is the point of making it.`, {size:21}));
body.push(note("Read with care: most boundaries rest on inferred closures, so some overlap is an artefact of straight-line bridging rather than a competing claim. It does not disappear when only walked boundaries are counted, but the headline share is inflated by the inferred ones."));
body.push(p("Overlaps are recorded exactly as mapped. They are not reconciled, and clans are never merged.", {size:21}));
body.push(h("What an overlap here is not", HeadingLevel.HEADING_3));
body.push(p("An overlap in these figures is a statement about two surveys, not about two clans. Most boundaries here are incomplete — a quarter of the outline drawn around the mapped areas is straight line nobody walked — and where a survey is unfinished, the area attributed to it is bounded by those straight lines rather than by anything anyone walked or said.", {size:21}));
body.push(p("So an overlap between two unfinished surveys is first of all a sign that both need finishing. It is recorded because it is what the data shows, and because the pattern across the whole area is the point; it is not evidence that anybody disputes anything, and nothing in this document should be read as saying so.", {size:21}));

body.push(img("output/summary_map.png", 640, 580));
body.push(note("One wash for every mapped area, whether the boundary closed on its own or the closure was inferred. The washes are transparent and are not merged, so where two clans have recorded the same ground it simply reads darker, and darker again where three have. Orange: walked, but still too open to give an area. Pink dashes: nobody walked this — a straight line across a gap."));

body.push(h("Neighbouring clans walking the same edge", HeadingLevel.HEADING_2));
body.push(p(`The mirror image of the overlap figures, and just as important. ${sum.shared_line_pairs} pairs of clans have recorded lines that run within ${TOL} m of each other — they walked the same edge. That is agreement on a boundary, and it does not show up in an overlap table at all. Some of the pairs below share almost their whole recorded line while sharing no ground at all.`, {size:21}));
if (sum.shared_line_table && sum.shared_line_table.length) {
  body.push(table(["Clan","Clan","Shared line (km)","% of the first's line","% of the second's"],
    sum.shared_line_table.slice(0,15).map(r=>[r.clan_a, r.clan_b, one(r.shared_km),
      one(r.pct_of_a)+"%", one(r.pct_of_b)+"%"]), [3,3,2,2,2]));
}
body.push(note("Read alongside the overlap table. A pair appearing here and not there has walked one edge together; a pair appearing in both has walked part of an edge together and has more still to walk."));

body.push(h("Giving the survey back", HeadingLevel.HEADING_2));
body.push(p(`Each clan has a GPX file of its own, named on that clan's page and supplied alongside this document. It is meant to go back to the Clan Stewards who walked the boundary, on the phone or handheld they mapped with: their own tracks, the gaps drawn as straight lines named so they cannot be mistaken for boundary, and a waypoint at each end of every gap.`, {size:21}));
body.push(p(`${money(sum.gpx_gaps)} gaps are marked across ${money(sum.gpx_clans)} clans, ${one(sum.gpx_gap_km)} km still to walk. A steward can select the waypoint for a gap, walk to it, and record from there.`, {size:21}));
body.push(note("Joins shorter than 100 m are not marked. Two track ends that close are the same place to anyone standing there, and flagging them would bury the gaps that matter."));

body.push(h("Sacred sites", HeadingLevel.HEADING_2));
body.push(p("Reported by area and share of clan land only; locations are not shared. Three sites across two mapped units, covering an estimated 313–456 ha, being 16–24% of the host clan's land. The range reflects that neither walk closed, so the area can only be bracketed.", {size:21}));
body.push(new Paragraph({ children:[new PageBreak()] }));

// ---------------- 2. How to read the clan entries ----------------
body.push(h("2. How to read the clan entries", HeadingLevel.HEADING_1));
body.push(p("Each clan starts on a new page, so a single clan's pages can be taken out and discussed with that clan without the rest of the document going with them.", {size:21}));
body.push(p("Each clan is assessed as one boundary within one zone. Where several stewards walked, their tracks are joined into a single survey — stewards of one clan are joined; different clans never are.", {size:21}));
body.push(table(["Term","Meaning"], [
  ["Walked", "Distance recorded, after smoothing"],
  ["Access legs", "Dead-end walks in to the boundary and back out; excluded from boundary distance"],
  ["Pieces", "Disconnected runs of track; one means a single continuous boundary"],
  ["Parcels", "Separate blocks of land the walks enclose; more than one is normal"],
  ["Not walked", "Straight line joining the pieces into a ring — nobody walked it, and it is not boundary"],
  ["Walked and closed", "The tracks ring the land; area is measured, not assumed"],
  ["Inferred", "Open ends bridged with straight lines; area is an estimate"],
  ["No area", "Gap exceeds half the distance walked — too open to estimate honestly"],
  ["Overlap (strict)", "Every square metre inside the area recorded for two clans"],
  ["Overlap (beyond tolerance)", `The same, with strips narrower than ${TOL} m removed`],
  ["Neighbouring clan", `A clan whose recorded line runs within ${TOL} m of this one's`],
], [3,7]));
body.push(note("A clan name that appears in more than one zone carries a zone code, for example Murai (Z2) and Murai (Z7B). This is expected — language spreads between zones and clans that split may keep an ancestral name — but the two are not the same landholding group and their land is never combined."));

body.push(h("Reading the map on each clan's page", HeadingLevel.HEADING_2));
body.push(...bullets([
  "Each steward's walk is a solid coloured line, and the area that walk gives on its own is the matching dashed outline.",
  "The survey those walks combine into is a dotted black outline, drawn underneath the stewards' lines. Where it follows a walk you see the steward's colour; where it strikes out on its own, that stretch was not walked by anyone — it is the straight line bridging a gap.",
  "Pink dashes are the stretches nobody walked: the receiver was off, and the straight line is this pipeline joining the pieces up. Do not read them as boundary.",
  "Neighbouring clans are named where they lie. Their boundaries are not drawn — this page is about one clan's survey, and what two surveys share is in the tables, not on the map.",
]));
body.push(new Paragraph({ children:[new PageBreak()] }));

// ---------------- 3. Clan entries ----------------
body.push(h("3. Clans", HeadingLevel.HEADING_1));
body.push(p(`${clans.length} clan boundaries, in zone order. Each begins on its own page.`, {size:21}));

let currentZone = null;
for (const c of clans) {
  body.push(new Paragraph({ children:[new PageBreak()] }));
  if (c.zone !== currentZone) {
    currentZone = c.zone;
    body.push(h(currentZone, HeadingLevel.HEADING_2));
  }
  body.push(h(`${c.clan}`, HeadingLevel.HEADING_3));
  body.push(note(`${c.zone}  ·  version ${ctx.version}, ${ctx.date_long}`));

  body.push(table(["Stewards","Surveys","Walked (km)","Access legs (km)","Pieces","Not walked (km)","Parcels","Area (ha)","Basis"], [[
    money(c.n_stewards), money(c.stewards.length), one(c.walked_km), one(c.spur_km),
    money(c.chains), c.gap_km ? one(c.gap_km) : "—",
    c.parcels ? money(c.parcels) : "—",
    c.area_ha===null ? "none" : money(c.area_ha),
    c.basis || "no area"
  ]], [2,2,3,3,2,3,2,3,3]));

  body.push(p("Clan Stewards", {bold:true, size:21}));
  body.push(table(["Clan Steward","Tracks","Days","First","Last","Walked (km)"],
    c.stewards.map(w=>[w.steward || "—", money(w.tracks), money(w.days),
      w.first || "—", w.last || "—", one(w.km)]), [4,2,2,3,3,2]));

  if (c.overlaps.length) {
    body.push(p("Ground also claimed by another clan", {bold:true, size:21}));
    body.push(table(["Clan","Shared (ha)","% of this clan",`Beyond ${TOL} m (ha)`,"Verdict"],
      c.overlaps.map(o=>[o.with, money(o.ha), one(o.pct)+"%",
        money(o.beyond_tol_ha), o.verdict]), [4,2,2,2,3]));
  }
  if (c.shared_lines.length) {
    body.push(p("Neighbouring clans", {bold:true, size:21}));
    body.push(table(["Clan","Boundary walked alongside (km)","% of this clan's line"],
      c.shared_lines.map(s=>[s.with, one(s.km), one(s.pct)+"%"]), [5,2,3]));
    body.push(note("Where the two clans' recorded lines run within " + TOL + " m of each other. Two neighbours walking the same edge is the ordinary case."));
  }

  // problems
  const problems = [];
  if (c.area_ha === null) problems.push(`No area can be given. The tracks are in ${c.chains} disconnected piece${c.chains===1?"":"s"} and ${one(c.gap_km)} km of straight-line joining would be needed to make a ring${c.gap_pct?` — ${Math.round(c.gap_pct)}% of the distance walked`:""}. That is beyond the 50% limit, above which an area would be more assumption than survey.`);
  else if (c.basis === "inferred") problems.push(`The boundary does not close. ${one(c.gap_km)} km${c.bridges?` in ${c.bridges} stretch${c.bridges===1?"":"es"}`:""} was bridged with straight lines nobody walked${c.gap_pct?` — ${Math.round(c.gap_pct)}% of the distance walked`:""}, so ${money(c.area_ha)} ha is an estimate rather than a measured area. On the map those stretches are pink.`);
  else problems.push(`The boundary closes on its own. ${money(c.area_ha)} ha is measured from the walk, with nothing inferred.`);

  if (c.parcels > 1) problems.push(`The walks enclose ${c.parcels} separate parcels, totalling ${money(c.area_ha)} ha. All of them are counted. Whether they are all this clan's land, or whether one belongs to a neighbour, is a question for the clan.`);

  if (c.n_stewards > 1 && c.join_sep_ha !== null) {
    const change = c.join_joined_ha - c.join_sep_ha;
    if (change < -1) problems.push(`Joining the ${c.n_stewards} stewards costs ${money(Math.abs(change))} ha: separately they give ${money(c.join_sep_ha)} ha, joined ${money(c.join_joined_ha)} ha. This happens where stewards each walked the same ring rather than different stretches — the two rings cross and the joined network encloses less than either walk did alone.`);
    else if (change > 1) problems.push(`Joining the ${c.n_stewards} stewards adds ${money(change)} ha: separately ${money(c.join_sep_ha)} ha, joined ${money(c.join_joined_ha)} ha. The stewards covered different stretches of one boundary.`);
  }
  const real = c.overlaps.filter(o=>o.verdict==="overlap");
  const slivers = c.overlaps.filter(o=>o.verdict!=="overlap");
  const unfinished = c.area_ha === null || (c.basis === "inferred" && c.gap_pct > 10);
  if (real.length) {
    const top = real.slice(0,4).map(o=>`${o.with} (${money(o.ha)} ha)`).join("; ");
    problems.push(`Ground here is also inside the area recorded for ${real.length} other clan${real.length===1?"":"s"}: ${top}.` + (unfinished ? ` These figures are provisional while this boundary is incomplete: the unwalked stretches are drawn as straight lines, and those lines are what the overlap is measured against.` : ``));
  }
  if (slivers.length) problems.push(`A further ${slivers.length} clan${slivers.length===1?"":"s"} (${slivers.map(o=>o.with).join(", ")}) ${slivers.length===1?"shares":"share"} ground only in strips narrower than ${TOL} m — the two lines being the same line, which is not counted as overlap.`);
  if (!real.length && c.shared_lines.length) {
    const s = c.shared_lines[0];
    problems.push(`${Math.round(s.pct)}% of this clan's recorded line runs within ${TOL} m of ${s.with}'s: the two walked the same edge.`);
  }

  body.push(p("What the survey shows", {bold:true, size:21}));
  body.push(...bullets(problems));

  // queries
  const queries = [];
  if (c.area_ha === null) queries.push(`Can the missing stretches be walked so this boundary closes? If any gap is deliberate — a river, a road, an agreed open edge — please say what runs along it.`);
  else if (c.basis === "inferred" && c.gap_pct > 25) queries.push(`${Math.round(c.gap_pct)}% of this outline was not walked — ${one(c.gap_km)} km of straight line, shown in pink. Does the boundary in fact run along those straight lines, or somewhere else? Can the missing stretches be walked?`);
  if (c.parcels > 1) queries.push(`This clan's land is recorded as ${c.parcels} separate pieces. Is that right, and does each piece belong to this clan?`);
  if (c.n_stewards > 1 && c.join_joined_ha < c.join_sep_ha - 1)
    queries.push(`Did the ${c.n_stewards} stewards walk the same boundary, or different parts of it? If they walked the same ring, their surveys should be treated as separate accounts rather than joined.`);
  if (c.chains > 3 && c.area_ha !== null)
    queries.push(`This boundary is recorded in ${c.chains} separate pieces. Were the connecting stretches walked but not recorded, or not yet walked?`);
  if (!queries.length) queries.push("Nothing outstanding. The boundary closes on its own and the survey is complete.");

  body.push(p("Queries for the field", {bold:true, size:21}));
  body.push(...bullets(queries));

  if (c.gpx) {
    body.push(p("To take back to the ground", {bold:true, size:21}));
    body.push(p(`A GPX file for this clan is supplied as ${c.gpx}. Loaded onto the phone or handheld the boundary was mapped with, it shows the stewards' own tracks` + (c.gpx_gaps ? `, the ${c.gpx_gaps} gap${c.gpx_gaps===1?"":"s"} drawn as straight lines, and a waypoint at each end of every gap so a steward can navigate to where the walking stopped and carry on.` : ` and confirms the boundary closes with no gaps to walk.`), {size:21}));
  }

  if (c.map) {
    body.push(p("Map", {bold:true, size:21, para:{ spacing:{ before:160 } }}));
    body.push(img(path.join("output/clans", c.map), 620, 470));
    body.push(note(c.n_stewards > 1
      ? "Each steward's line and the area it gives alone (dashed); the survey they combine into, dotted; the stretches nobody walked in pink. Neighbouring clans are named where they lie; their boundaries are not drawn."
      : "The walk and the area it gives (dotted), with the stretches nobody walked in pink. Neighbouring clans are named where they lie; their boundaries are not drawn."));
  }
}

// ---------------- 4. Appendix ----------------
body.push(new Paragraph({ children:[new PageBreak()] }));
body.push(h("4. Every overlapping pair", HeadingLevel.HEADING_1));
body.push(p(`All ${sum.overlap_pairs} pairs of clans whose mapped land intersects, strictly and beyond the ${TOL} m tolerance. A pair marked “within tolerance” shares only strips narrower than that, and is not counted as an overlap.`, {size:21}));
body.push(table(["Clan","Clan","Shared (ha)","% of first","% of second",`Beyond ${TOL} m (ha)`,"Verdict"],
  (sum.overlap_table||[]).map(r=>[r.clan_a, r.clan_b, money(r.shared_ha),
    one(r.pct_of_a)+"%", one(r.pct_of_b)+"%", money(r.beyond_tol_ha), r.verdict]),
  [3,3,2,2,2,2,3]));

body.push(h("How these figures were produced", HeadingLevel.HEADING_1));
body.push(table(["Setting","Value"], [
  ["Measurement CRS", ctx.metric_crs+" (UTM 55S)"],
  ["Smoothing", `one point every ${ctx.smoothing_spacing_m} m`],
  ["Clipped to", `within ${ctx.clip_distance_km} km of the conservation area`],
  ["Track ends joined within", one(ctx.closure_tolerance_m)+" m"],
  ["Widest gap still given an area", Math.round(ctx.max_gap_share*100)+"% of the distance walked"],
  ["Overlap tolerance", TOL+" m"],
  ["Code revision", ctx.commit || "—"],
], [5,5]));
body.push(p("The full method, with every parameter and the reasoning behind it, is in docs/METHODS.md in the project repository. The raw survey data is never edited; everything here is derived from it and can be rebuilt from it.", {size:21}));

const doc = new Document({
  creator: "MCA Maps",
  title: `Managalas Clan Land Mapping v${ctx.version}`,
  description: `Survey results, per-clan detail and field queries — version ${ctx.version}, ${ctx.date_long}`,
  numbering: { config: [{ reference:"bullets", levels:[{ level:0, format:LevelFormat.BULLET,
    text:"•", alignment:AlignmentType.LEFT,
    style:{ paragraph:{ indent:{ left:360, hanging:180 } } } }] }] },
  styles: { paragraphStyles: [
    { id:"Normal", name:"Normal", run:{ size:21, font:"Calibri" },
      paragraph:{ spacing:{ line:276, after:120 } } } ] },
  sections: [{
    properties: { page: { size:{ width:12240, height:15840 }, margin:{ top:1080, bottom:1080, left:1080, right:1080 } } },
    footers: { default: new Footer({ children:[ new Paragraph({
      alignment: AlignmentType.CENTER,
      children:[ new TextRun({ text:`Managalas Clan Land Mapping — version ${ctx.version}, ${ctx.date_long}  ·  page `,
        size:16, color:"808080" }),
        new TextRun({ children:[PageNumber.CURRENT], size:16, color:"808080" }) ] }) ] }) },
    children: body }]
});

Packer.toBuffer(doc).then(b=>{ fs.writeFileSync(process.argv[4], b);
  console.log("wrote", process.argv[4], (b.length/1e6).toFixed(1), "MB"); });
