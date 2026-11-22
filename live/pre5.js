// usage: node pre5.js place race date outfile  -> exhibition + odds(3連単 grid, 単勝) text
// 「展示情報」の表の列は進入順（前付けがあると枠番順でない）。===進入順の枠番 と ===欠場の疑い の行で確認する。
const { chromium } = require('playwright');const fs=require('fs');
const [pn,r,hd,out]=process.argv.slice(2);
(async()=>{const b=await chromium.launch();const p=await b.newPage();let o='';
await p.goto(`https://kyoteibiyori.com/race_shusso.php?place_no=${pn}&race_no=${r}&hiduke=${hd}&slider=4`,{waitUntil:'networkidle',timeout:60000});
await p.waitForFunction(()=>document.body.innerText.includes('1号艇'),{timeout:20000}).catch(()=>{});await p.waitForTimeout(1500);
let t=(await p.evaluate(()=>document.body.innerText)).replace(/\n\s*\n/g,'\n');
let a=t.indexOf('コメント\t');if(a<0)a=t.indexOf('今節展示情報');if(a<0)a=t.indexOf('展示情報');const e=t.indexOf('展示STと本番ST');o+=t.slice(a,e)+'\n';
const tide=(t.match(/(干潮時間[^\n]*|満潮時間[^\n]*)/)||[''])[0];o+='===潮 '+tide+'\n';
const sd0=t.indexOf('スタート展示'),sd1=t.indexOf('展示リプレイ',sd0);if(sd0>=0)o+='===並び(S=スロー,D=ダッシュ)\n'+t.slice(sd0,sd1>sd0?sd1:sd0+200).replace(/\n\t/g,'\t')+'\n';
{let blk=sd0>=0?t.slice(sd0,sd1>sd0?sd1:sd0+200).replace(/\n\t/g,'\t'):'';const wq=blk.indexOf('気温');if(wq>0)blk=blk.slice(0,wq);const ord=[...blk.matchAll(/^([1-6])\t[^\t\n]*\t[F.0-9L]/gm)].map(m=>m[1]);
if(ord.length){const miss=['1','2','3','4','5','6'].filter(x=>!ord.includes(x));const nari=ord.join('')==='123456'.slice(0,ord.length)&&!miss.length;
o+='===進入順の枠番: '+ord.join(' ')+(nari?'（枠なり）':'（枠なりでない。上の「展示情報」の表の列はこの進入順で、枠番順ではない）')+'\n';
if(miss.length)o+='===欠場の疑い: 枠'+miss.join('・')+'（スタート展示にいない）\n';}}
const w=t.indexOf('気温');o+=t.slice(w,w+60)+'\n';
await p.evaluate(()=>document.getElementById('modalMenu6').click());await p.waitForTimeout(3500);
t=(await p.evaluate(()=>document.body.innerText)).replace(/\n\s*\n/g,'\n');
let j=t.indexOf('発売票数履歴');o+='===3連単\n'+t.slice(j+6,t.indexOf('【ADVERTISEMENT】',j))+'\n';
await p.evaluate(()=>{const el=[...document.querySelectorAll('a,li,span,div,button')].find(e=>e.textContent.trim()==='単勝・複勝'&&e.offsetParent!==null);if(el)el.click();});
await p.waitForTimeout(2500);t=(await p.evaluate(()=>document.body.innerText)).replace(/\n\s*\n/g,'\n');
j=t.indexOf('C\t名称\t単勝');o+='===単勝\n'+t.slice(j,j+200)+'\n';
fs.writeFileSync(out,o);await b.close();})();
