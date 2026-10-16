// Build the short report: only the clans whose boundary closes on its own.
//
// The large report carries all 49 clans and the 2 Land Settlement blocks,
// most of them unfinished, and the
// finished ones are hard to find inside it. This is the other document: the
// clans who have completed their map, with nothing in their area figure that
// the Clan Stewards did not walk.
//
//   node scripts/build_finished_docx.js <json-dir> <repo-root> <out.docx>

const fs = require('fs');
const path = require('path');
const d = require('docx');
const { Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow,
        TableCell, WidthType, ShadingType, AlignmentType, ImageRun, PageBreak,
        Footer, PageNumber } = d;

const S = process.argv[2];
const REPO = process.argv[3];
const sum = JSON.parse(fs.readFileSync(path.join(S,'summary.json'),'utf8'));
const clans = JSON.parse(fs.readFileSync(path.join(S,'clandata.json'),'utf8'));
const ctx = JSON.parse(fs.readFileSync(path.join(S,'context.json'),'utf8'));

const DXA = WidthType.DXA;
const FULL = 10080;
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
    shading: opts.shade ? { type:ShadingType.CLEAR, fill:opts.shade } : undefined,
    margins:{ top:60, bottom:60, left:90, right:90 },
    children:[ new Paragraph({ children:[new TextRun({ text:String(text),
      bold:!!opts.bold, size:20 })] }) ] });
}
function table(head, rows, widths){
  const total = widths.reduce((a,b)=>a+b,0);
  const w = widths.map(x => Math.round(FULL * x / total));
  return new Table({ width:{ size:FULL, type:DXA },
    rows:[ new TableRow({ tableHeader:true,
             children: head.map((t,i)=>cell(t, w[i], {bold:true, shade:HDR})) }),
      ...rows.map((r,ri)=> new TableRow({ children: r.map((t,i)=>
        cell(t, w[i], ri%2 ? {shade:ALT} : {})) })) ] });
}
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

const done = clans.filter(c => c.basis === "walked" && c.area_ha);
done.sort((a,b)=> b.area_ha - a.area_ha);

const body = [];
body.push(new Paragraph({ text:"Managalas Clan Land Mapping", heading:HeadingLevel.TITLE }));
body.push(new Paragraph({ children:[new TextRun({ text:"The completed boundaries",
  size:26, color:"404040" })], spacing:{ after:120 } }));
body.push(new Paragraph({ children:[new TextRun({
  text:`Version ${ctx.version}  ·  ${ctx.date_long}`, bold:true, size:22, color:"1F4E79" })],
  spacing:{ after:240 } }));

const totalHa = done.reduce((a,c)=>a+c.area_ha,0);
const totalKm = done.reduce((a,c)=>a+c.walked_km,0);
body.push(p(`${done.length} of ${sum.clans} clans have a boundary that closes on the ground the Clan Stewards walked. Their maps are finished: the area is measured from the walk, with no straight line anywhere in it that nobody walked.`, {size:21}));
body.push(p(`Together they hold ${money(totalHa)} ha, walked over ${money(totalKm)} km.`, {size:21}));
body.push(note(`This is the short companion to the full report, which carries all ${sum.clans} clans and ${sum.blocks} Land Settlement blocks, including the ${clans.length-done.length} whose maps are not yet finished. Nothing here is estimated, so nothing here needs the cautions that document carries.`));

body.push(h("The completed boundaries", HeadingLevel.HEADING_1));
body.push(table(["Clan","Zone","Clan Stewards","Walked (km)","Area (ha)","Sacred sites"],
  done.map(c=>[c.clan, c.zone, c.stewards.map(w=>w.steward).join(", "),
               one(c.walked_km), money(c.area_ha),
               ((c.sacred&&(c.sacred.tagged+c.sacred.internal)) || 0) ? money(c.sacred.tagged+c.sacred.internal) : "none"]),
  [3,2,6,2,2,2]));
body.push(note("Sacred sites are reported by number only here, and by area on each clan's page. Locations are not shared and appear on no map in this document."));

for (const c of done) {
  body.push(new Paragraph({ children:[new PageBreak()] }));
  body.push(h(`${c.clan}`, HeadingLevel.HEADING_1));
  body.push(note(`${c.zone}  ·  version ${ctx.version}, ${ctx.date_long}`));
  body.push(table(["Clan Stewards","Walked (km)","Pieces","Parcels","Area (ha)"],
    [[money(c.n_stewards), one(c.walked_km), money(c.chains),
      c.parcels ? money(c.parcels) : "—", money(c.area_ha)]], [3,2,2,2,2]));

  body.push(p("Clan Stewards", {bold:true, size:21}));
  body.push(table(["Clan Steward","Tracks","Days","First","Last","Walked (km)"],
    c.stewards.map(w=>[w.steward || "—", money(w.tracks), money(w.days),
      w.first || "—", w.last || "—", one(w.km)]), [4,2,2,3,3,2]));

  const sc = c.sacred || {tagged:0, internal:0, internal_ha:0};
  const n = (sc.tagged||0) + (sc.internal||0);
  body.push(p("Sacred sites", {bold:true, size:21}));
  if (!n) body.push(p("None recorded.", {size:21}));
  else {
    const share = (sc.internal_ha && c.area_ha)
      ? `, covering ${one(sc.internal_ha)} ha — ${one(sc.internal_ha/c.area_ha*100)}% of this clan's land` : "";
    body.push(p(`${money(n)} recorded${share}. Locations are not shared.`, {size:21}));
  }

  if (c.map) body.push(img(`output/clans/${c.map}`, 560, 660));
  body.push(p(`${money(c.area_ha)} ha, measured from ${one(c.walked_km)} km walked. Nothing in this boundary was inferred.`, {size:21}));
}

const doc = new Document({
  creator: "MCA Maps",
  title: `Managalas — the completed boundaries v${ctx.version}`,
  description: `The clans whose boundary closes on the walk — version ${ctx.version}, ${ctx.date_long}`,
  styles: { paragraphStyles: [
    { id:"Normal", name:"Normal", run:{ size:21, font:"Calibri" },
      paragraph:{ spacing:{ line:276, after:120 } } } ] },
  sections: [{
    properties: { page: { size:{ width:12240, height:15840 }, margin:{ top:1080, bottom:1080, left:1080, right:1080 } } },
    footers: { default: new Footer({ children:[ new Paragraph({
      alignment: AlignmentType.CENTER,
      children:[ new TextRun({ text:`Managalas — the completed boundaries, version ${ctx.version}, ${ctx.date_long}  ·  page `,
        size:16, color:"808080" }),
        new TextRun({ children:[PageNumber.CURRENT], size:16, color:"808080" }) ] }) ] }) },
    children: body }]
});

Packer.toBuffer(doc).then(b=>{ fs.writeFileSync(process.argv[4], b);
  console.log("wrote", process.argv[4], (b.length/1e6).toFixed(1), "MB"); });
