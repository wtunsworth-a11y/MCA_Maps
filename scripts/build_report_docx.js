const fs = require('fs');
const path = require('path');
const d = require('docx');
const { Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow,
        TableCell, WidthType, ShadingType, AlignmentType, ImageRun, PageBreak,
        BorderStyle, TableOfContents, LevelFormat, PageOrientation } = d;

const S = process.argv[2];
const REPO = process.argv[3];
const sum = JSON.parse(fs.readFileSync(path.join(S,'summary.json'),'utf8'));
const clans = JSON.parse(fs.readFileSync(path.join(S,'clandata.json'),'utf8'));

const DXA = WidthType.DXA;
const FULL = 9360;                       // 6.5" content width
const HDR = "D9E2F3", ALT = "F2F2F2";

function p(text, opts={}) {
  return new Paragraph({ children:[new TextRun({ text, ...opts })], ...(opts.para||{}) });
}
function h(text, level){ return new Paragraph({ text, heading: level }); }
function note(text){
  return new Paragraph({ children:[new TextRun({ text, italics:true, size:19, color:"595959" })],
    spacing:{ before:60, after:120 } });
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
function img(rel, widthPx, heightPx){
  const f = path.join(REPO, rel);
  if (!fs.existsSync(f)) return p(`[map not available: ${rel}]`, {italics:true});
  return new Paragraph({ alignment: AlignmentType.CENTER,
    children:[ new ImageRun({ type:"png", data: fs.readFileSync(f),
      transformation:{ width:widthPx, height:heightPx } }) ] });
}
const money = n => n===null||n===undefined ? "—" : Number(n).toLocaleString('en-GB',{maximumFractionDigits:0});
const one = n => n===null||n===undefined ? "—" : Number(n).toLocaleString('en-GB',{minimumFractionDigits:1,maximumFractionDigits:1});

const body = [];

// ---------------- Title ----------------
body.push(new Paragraph({ text:"Managalas Clan Land Mapping", heading:HeadingLevel.TITLE }));
body.push(new Paragraph({ children:[new TextRun({ text:"Survey results, per-clan detail, and queries for the field",
  size:26, color:"404040" })], spacing:{ after:240 } }));
body.push(p("Clan land boundaries in the Managalas Conservation Area, Oro Province, Papua New Guinea. Mapped by Clan Stewards at the request of clan elders through the Clan Elder Workshops. Each community decides whether to map; where a boundary is disputed the community decides whether to resolve it or leave the area aside.", {size:21}));
body.push(note("Sacred site locations are not shared. They are reported by area and share of clan land only, and appear in no map or layer in this document."));
body.push(new Paragraph({ children:[new PageBreak()] }));

body.push(h("Contents", HeadingLevel.HEADING_1));
body.push(new TableOfContents("Contents", { hyperlink:true, headingStyleRange:"1-2" }));
body.push(new Paragraph({ children:[new PageBreak()] }));

// ---------------- 1. Summary ----------------
body.push(h("1. What has been mapped", HeadingLevel.HEADING_1));
body.push(table(["Measure","Value"], [
  ["Clans with data", money(sum.clans)],
  ["Custodians who walked", money(sum.custodians)],
  ["Individual surveys", money(sum.surveys)],
  ["Clan boundaries assessed (walkers joined)", money(sum.units)],
  ["Distance walked", one(sum.walked_km)+" km"],
  ["Boundary walked (excl. access legs and non-boundary)", one(sum.boundary_km)+" km"],
], [6,3]));
body.push(note("Boundary distance excludes surveys that are not land boundaries, and the legs walked in to reach a boundary and out again."));

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
body.push(p(`The mapped footprint is ${(sum.footprint_ha/sum.mca_ha*100).toFixed(1)}% of the conservation area.`, {size:21}));

body.push(h("By zone", HeadingLevel.HEADING_2));
body.push(table(["Zone","Clans","Custodians","Surveys","Walked (km)","Boundary (km)","Area (ha)"],
  sum.zones.map(z=>[z.zone, money(z.clans), money(z.custodians), money(z.surveys),
    one(z.walked_km), one(z.boundary_km), money(z.area_ha)]), [3,2,2,2,3,3,3]));

body.push(h("Overlap between clans", HeadingLevel.HEADING_2));
body.push(table(["Measure","Value"], [
  ["Clans with a mapped area", money(sum.clans_mapped)],
  ["Clans whose land overlaps another clan's", money(sum.clans_overlap)],
  ["Clans with no overlap", money(sum.clans_mapped - sum.clans_overlap)],
  ["Area claimed by more than one clan", money(sum.contested_ha)+" ha"],
], [6,3]));
body.push(p("This is the finding with the widest implications. The PNG Incorporated Land Group system rests on land being held by a single clan, undisputed. On this evidence that assumption does not describe the Managalas.", {size:21}));
body.push(note("Read with care: most boundaries rest on inferred closures, so some overlap is an artefact of straight-line bridging rather than a competing claim. It does not disappear when only walked boundaries are counted, but the headline share is inflated by the inferred ones."));
body.push(p("Overlaps are recorded as mapped. They are not reconciled, and clans are never merged.", {size:21}));

body.push(img("output/summary_map.png", 560, 520));
body.push(note("Blue: boundary walked and closed. Amber: closure inferred. Red: claimed by more than one clan. Purple: walked but too open to give an area."));

body.push(h("Sacred sites", HeadingLevel.HEADING_2));
body.push(p("Reported by area and share of clan land only; locations are not shared. Three sites across two mapped units, covering an estimated 313–456 ha, being 16–24% of the host clan's land. The range reflects that neither walk closed, so the area can only be bracketed.", {size:21}));
body.push(new Paragraph({ children:[new PageBreak()] }));

// ---------------- 2. How to read the clan entries ----------------
body.push(h("2. How to read the clan entries", HeadingLevel.HEADING_1));
body.push(p("Each clan is assessed as one boundary within one zone. Where several custodians walked, their tracks are joined into a single survey — walkers of one clan are joined; different clans never are.", {size:21}));
body.push(table(["Term","Meaning"], [
  ["Walked", "Distance recorded, after smoothing"],
  ["Access legs", "Dead-end walks in to the boundary and back out; excluded from boundary distance"],
  ["Pieces", "Disconnected runs of track; one means a single continuous boundary"],
  ["Gap to close", "Straight-line distance still needed to make the pieces one ring"],
  ["Walked and closed", "The tracks ring the land; area is measured, not assumed"],
  ["Inferred", "Open ends bridged with straight lines; area is an estimate"],
  ["No area", "Gap exceeds half the distance walked — too open to estimate honestly"],
], [3,7]));
body.push(note("A clan name that appears in more than one zone carries a zone code, for example Murai (Z2) and Murai (Z7B). This is expected — language spreads between zones and clans that split may keep an ancestral name — but the two are not the same landholding group and their land is never combined."));
body.push(new Paragraph({ children:[new PageBreak()] }));

// ---------------- 3. Clan entries ----------------
body.push(h("3. Clans", HeadingLevel.HEADING_1));

let currentZone = null;
for (const c of clans) {
  if (c.zone !== currentZone) {
    currentZone = c.zone;
    body.push(h(currentZone, HeadingLevel.HEADING_2));
  }
  body.push(h(`${c.clan}`, HeadingLevel.HEADING_3));

  body.push(table(["Walkers","Surveys","Walked (km)","Access legs (km)","Pieces","Gap to close (km)","Area (ha)","Basis"], [[
    money(c.n_walkers), money(c.walkers.length), one(c.walked_km), one(c.spur_km),
    money(c.chains), c.gap_km ? one(c.gap_km) : "—",
    c.area_ha===null ? "none" : money(c.area_ha),
    c.basis || "no area"
  ]], [2,2,3,3,2,3,3,3]));

  body.push(p("Custodians", {bold:true, size:21}));
  body.push(table(["Custodian","Tracks","Walked (km)","Type"],
    c.walkers.map(w=>[w.custodian || "—", money(w.tracks), one(w.km), w.type]), [5,2,2,3]));

  // problems
  const problems = [];
  if (c.area_ha === null) problems.push(`No area can be given. The tracks are in ${c.chains} disconnected piece${c.chains===1?"":"s"} and ${one(c.gap_km)} km of straight-line joining would be needed to make a ring${c.gap_pct?` — ${Math.round(c.gap_pct)}% of the distance walked`:""}. That is beyond the 50% limit, above which an area would be more assumption than survey.`);
  else if (c.basis === "inferred") problems.push(`The boundary does not close. ${one(c.gap_km)} km was bridged with straight lines${c.gap_pct?` (${Math.round(c.gap_pct)}% of the distance walked)`:""}, so ${money(c.area_ha)} ha is an estimate rather than a measured area.`);
  else problems.push(`The boundary closes on its own. ${money(c.area_ha)} ha is measured from the walk, with nothing inferred.`);

  if (c.n_walkers > 1 && c.join_sep_ha !== null) {
    const change = c.join_joined_ha - c.join_sep_ha;
    if (change < -1) problems.push(`Joining the ${c.n_walkers} walkers costs ${money(Math.abs(change))} ha: separately they give ${money(c.join_sep_ha)} ha, joined ${money(c.join_joined_ha)} ha. This happens where walkers each walked the same ring rather than different stretches — the two rings cross and the joined network encloses less than either walk did alone.`);
    else if (change > 1) problems.push(`Joining the ${c.n_walkers} walkers adds ${money(change)} ha: separately ${money(c.join_sep_ha)} ha, joined ${money(c.join_joined_ha)} ha. The walkers covered different stretches of one boundary.`);
  }
  if (c.overlaps.length) {
    const top = c.overlaps.slice(0,4).map(o=>`${o.with} (${money(o.ha)} ha, ${Math.round(o.pct)}% of this clan's land)`).join("; ");
    problems.push(`Overlaps ${c.overlaps.length} other clan${c.overlaps.length===1?"":"s"}: ${top}.`);
  }

  body.push(p("Problems", {bold:true, size:21}));
  problems.forEach(t=>body.push(new Paragraph({ children:[new TextRun({ text:t, size:20 })],
    bullet:{ level:0 }, spacing:{ after:60 } })));

  // queries
  const queries = [];
  if (c.area_ha === null) queries.push(`Can the missing stretches be walked so this boundary closes? If any gap is deliberate — a river, a road, an agreed open edge — please say what runs along it.`);
  else if (c.basis === "inferred" && c.gap_pct > 25) queries.push(`${Math.round(c.gap_pct)}% of this boundary was not walked. Can the remaining ${one(c.gap_km)} km be completed, so the area is measured rather than estimated?`);
  if (c.n_walkers > 1 && c.join_joined_ha < c.join_sep_ha - 1)
    queries.push(`Did the ${c.n_walkers} custodians walk the same boundary, or different parts of it? If they walked the same ring, their surveys should be treated as separate accounts rather than joined.`);
  if (c.overlaps.length)
    queries.push(`Is the ground shared with ${c.overlaps.slice(0,3).map(o=>o.with).join(", ")} disputed, shared by agreement, or recorded wrongly? No change will be made to either boundary without the community's decision.`);
  if (c.chains > 3 && c.area_ha !== null)
    queries.push(`This boundary is recorded in ${c.chains} separate pieces. Were the connecting stretches walked but not recorded, or not yet walked?`);
  if (!queries.length) queries.push("No outstanding queries. The boundary closes and does not overlap another clan.");

  body.push(p("Queries for the field", {bold:true, size:21}));
  queries.forEach(t=>body.push(new Paragraph({ children:[new TextRun({ text:t, size:20 })],
    bullet:{ level:0 }, spacing:{ after:60 } })));

  if (c.map) {
    body.push(p("Effect of joining the walkers", {bold:true, size:21, para:{ spacing:{ before:160 } }}));
    body.push(img(path.join("output/clans", c.map), 470, 390));
    body.push(note("Each walker's line and the area it gives alone (dashed); the joined survey outlined in black."));
  }
  body.push(new Paragraph({ text:"", spacing:{ after:120 } }));
}

const doc = new Document({
  creator: "MCA Maps",
  title: "Managalas Clan Land Mapping",
  description: "Survey results, per-clan detail and field queries",
  numbering: { config: [{ reference:"bullets", levels:[{ level:0, format:LevelFormat.BULLET,
    text:"•", alignment:AlignmentType.LEFT,
    style:{ paragraph:{ indent:{ left:360, hanging:180 } } } }] }] },
  styles: { paragraphStyles: [
    { id:"Normal", name:"Normal", run:{ size:21, font:"Calibri" },
      paragraph:{ spacing:{ line:276, after:120 } } } ] },
  sections: [{
    properties: { page: { size:{ width:12240, height:15840 }, margin:{ top:1080, bottom:1080, left:1080, right:1080 } } },
    children: body }]
});

Packer.toBuffer(doc).then(b=>{ fs.writeFileSync(process.argv[4], b);
  console.log("wrote", process.argv[4], (b.length/1e6).toFixed(1), "MB"); });
