// Build the steward-days Word document from output/stewards/stewards.json.
//
//   node scripts/build_stewards_docx.js <stewards-dir> <report-json-dir> <out.docx>

const fs = require('fs');
const path = require('path');
const d = require('docx');
const { Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow,
        TableCell, WidthType, ShadingType, AlignmentType, PageBreak,
        TableOfContents, LevelFormat, Footer, PageNumber } = d;

const W = process.argv[2];
const S = process.argv[3];
const data = JSON.parse(fs.readFileSync(path.join(W,'stewards.json'),'utf8'));
const ctx = JSON.parse(fs.readFileSync(path.join(S,'context.json'),'utf8'));
const stewards = data.stewards, days = data.days;

const DXA = WidthType.DXA;
const FULL = 10080;
const HDR = "D9E2F3", ALT = "F2F2F2";
const LONG_DAY_KM = 25;

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
const money = n => n===null||n===undefined ? "—" : Number(n).toLocaleString('en-GB',{maximumFractionDigits:0});
const one = n => n===null||n===undefined ? "—" : Number(n).toLocaleString('en-GB',{minimumFractionDigits:1,maximumFractionDigits:1});

const dated = days.filter(r=>r.date);
const fieldDays = new Set(dated.map(r=>r.date));
const totalKm = stewards.reduce((a,w)=>a+w.km, 0);
const undated = stewards.reduce((a,w)=>a+w.undated_tracks, 0);
const longDays = dated.filter(r=>r.km > LONG_DAY_KM).sort((a,b)=>b.km-a.km);
const firstDate = dated.map(r=>r.date).sort()[0];
const lastDate = dated.map(r=>r.date).sort().slice(-1)[0];

const byZone = {};
for (const r of dated) {
  const z = byZone[r.zone] || (byZone[r.zone] = { stewards:new Set(), days:new Set(), stewardDays:0, km:0 });
  z.stewards.add(r.steward); z.days.add(r.date); z.stewardDays++; z.km += r.km;
}

const body = [];

body.push(new Paragraph({ text:"Managalas Steward Days", heading:HeadingLevel.TITLE }));
body.push(new Paragraph({ children:[new TextRun({ text:"Who walked, on which days, and how far",
  size:26, color:"404040" })], spacing:{ after:120 } }));
body.push(new Paragraph({ children:[new TextRun({
  text:`Version ${ctx.version}  ·  ${ctx.date_long}`, bold:true, size:22, color:"1F4E79" })],
  spacing:{ after:240 } }));
body.push(p("The record of the work, kept separate from the record of the land. Clan Stewards walked these boundaries at the request of clan elders through the Clan Elder Workshops. This document accounts for their time on the ground.", {size:21}));
body.push(note("Every date here comes from the GPS record inside each track, not from a file name. The file-name date is the date the archive was collated and delivered — the field team confirmed this — and every file in a delivery carries the same one, so it says nothing about when a boundary was walked."));

if (ctx.changes && ctx.changes.length) {
  body.push(h(`What changed in version ${ctx.version}`, HeadingLevel.HEADING_2));
  body.push(...bullets(ctx.changes));
  body.push(note("Figures move between versions because the method improves as well as because new surveys arrive. Where a correction changed a number materially, the change says so."));
}

body.push(h("In total", HeadingLevel.HEADING_1));
body.push(table(["Measure","Value"], [
  ["Clan Stewards who walked", money(stewards.length)],
  ["Steward-days recorded", money(dated.length)],
  ["Distinct days on the ground", money(fieldDays.size)],
  ["First walk recorded", firstDate],
  ["Last walk recorded", lastDate],
  ["Distance walked", one(totalKm)+" km"],
  ["Average per steward-day", one(totalKm/dated.length)+" km"],
  ["Tracks with no recoverable date", money(undated)],
], [6,3]));
body.push(note("A steward-day is one steward recording on one day. Two stewards out together on the same day count as two steward-days and one day on the ground."));

body.push(h("By zone", HeadingLevel.HEADING_1));
body.push(table(["Zone","Clan Stewards","Days on the ground","Steward-days","Distance (km)"],
  Object.keys(byZone).sort().map(z=>[z, money(byZone[z].stewards.size),
    money(byZone[z].days.size), money(byZone[z].stewardDays), one(byZone[z].km)]),
  [3,2,3,2,3]));

body.push(h("Every steward", HeadingLevel.HEADING_1));
body.push(p("Sorted by zone, then by name. Distance is measured along the smoothed track, so it is the distance along the ground the receiver recorded, not the distance the steward's legs covered.", {size:21}));
body.push(table(["Clan Steward","Zone","Clan(s)","Tracks","Days","First","Last","Distance (km)","Per day (km)"],
  stewards.map(w=>[w.steward, w.zones, w.clans || "—", money(w.tracks), money(w.days),
    w.first || "—", w.last || "—", one(w.km), w.km_per_day===null?"—":one(w.km_per_day)]),
  [4,2,4,2,2,3,3,2,2]));

body.push(new Paragraph({ children:[new PageBreak()] }));
body.push(h("Every steward-day", HeadingLevel.HEADING_1));
body.push(p("One row per steward per day, in date order within each steward. This is the full record; the totals above are its sums.", {size:21}));

const bySteward = {};
for (const r of days) (bySteward[r.steward] || (bySteward[r.steward] = [])).push(r);
for (const name of Object.keys(bySteward).sort()) {
  const rows = bySteward[name].slice().sort((a,b)=>String(a.date).localeCompare(String(b.date)));
  const km = rows.reduce((a,r)=>a+r.km,0);
  body.push(h(name, HeadingLevel.HEADING_3));
  body.push(table(["Date","Zone","Clan","Tracks","Distance (km)"],
    rows.map(r=>[r.date || "undated", r.zone, r.clan || "—", money(r.tracks), one(r.km)])
      .concat([["Total","","", money(rows.reduce((a,r)=>a+r.tracks,0)), one(km)]]),
    [3,3,4,2,2]));
}

body.push(new Paragraph({ children:[new PageBreak()] }));
body.push(h("What to check", HeadingLevel.HEADING_1));

body.push(h("Days recording an unusually long distance", HeadingLevel.HEADING_2));
body.push(p(`${longDays.length} steward-days record more than ${LONG_DAY_KM} km. In this terrain that is a long way for one day on foot, and there are two ordinary explanations worth ruling out: the receiver left running during travel by vehicle, or a single track recorded across more than one day and saved once. A track is dated by when it was created, so a walk spanning two days is counted on the first.`, {size:21}));
if (longDays.length) {
  body.push(table(["Clan Steward","Date","Zone","Clan","Tracks","Distance (km)"],
    longDays.map(r=>[r.steward, r.date, r.zone, r.clan || "—", money(r.tracks), one(r.km)]),
    [4,3,3,4,2,2]));
}
body.push(p("Query for the field: for each of these days, was the whole distance walked, and was it walked on that day?", {size:21, bold:true}));

if (undated) {
  body.push(h("Tracks with no date", HeadingLevel.HEADING_2));
  body.push(p(`${undated} track(s) carry no timestamp the pipeline can read, and no date in their name. They are counted in every distance figure but not in any day count.`, {size:21}));
  body.push(table(["Clan Steward","Zone","Clan(s)","Undated tracks"],
    stewards.filter(w=>w.undated_tracks).map(w=>[w.steward, w.zones, w.clans || "—",
      money(w.undated_tracks)]), [4,3,4,2]));
}

body.push(h("How to read these figures", HeadingLevel.HEADING_2));
body.push(...bullets([
  "Distance is measured in UTM zone 55S, along the track after smoothing to one point every 20 m. Smoothing removes GPS scatter, so these distances are slightly shorter than the raw recording and closer to the ground truth.",
  "Distance includes the legs walked in to reach a boundary and out again. The boundary-only figure, which excludes those, is in the main report.",
  "A day here is the day the track was created on the device. Where a walk ran past midnight, the whole walk is counted on the day it began.",
  "A steward who appears under more than one clan walked for each of them; the days are counted once, under the clan of each track.",
]));

const doc = new Document({
  creator: "MCA Maps",
  title: `Managalas Steward Days v${ctx.version}`,
  description: `Who walked, when, and how far — version ${ctx.version}, ${ctx.date_long}`,
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
      children:[ new TextRun({ text:`Managalas Steward Days — version ${ctx.version}, ${ctx.date_long}  ·  page `,
        size:16, color:"808080" }),
        new TextRun({ children:[PageNumber.CURRENT], size:16, color:"808080" }) ] }) ] }) },
    children: body }]
});

Packer.toBuffer(doc).then(b=>{ fs.writeFileSync(process.argv[4], b);
  console.log("wrote", process.argv[4], (b.length/1e6).toFixed(2), "MB"); });
