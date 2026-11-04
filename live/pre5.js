// usage: node pre5.js place race date outfile  -> exhibition + odds(3連単 grid, 単勝) text
const { chromium } = require('playwright');const fs=require('fs');
const [pn,r,hd,out]=process.argv.slice(2);
(async()=>{const b=await chromium.launch();const p=await b.newPage();let o='';
await p.goto(`https://kyoteibiyori.com/race_shusso.php?place_no=${pn}&race_no=${r}&hiduke=${hd}&slider=4`,{waitUntil:'networkidle',timeout:60000});
await p.waitForFunction(()=>document.body.innerText.includes('1号艇'),{timeout:20000}).catch(()=>{});await p.waitForTimeout(1500);
let t=(await p.evaluate(()=>document.body.innerText)).replace(/\n\s*\n/g,'\n');
const a=t.indexOf('コメント\t'),e=t.indexOf('展示STと本番ST');o+=t.slice(a,e)+'\n';
const w=t.indexOf('気温');o+=t.slice(w,w+60)+'\n';
await p.evaluate(()=>document.getElementById('modalMenu6').click());await p.waitForTimeout(3500);
t=(await p.evaluate(()=>document.body.innerText)).replace(/\n\s*\n/g,'\n');
let j=t.indexOf('発売票数履歴');o+='===3連単\n'+t.slice(j+6,t.indexOf('【ADVERTISEMENT】',j))+'\n';
await p.evaluate(()=>{const el=[...document.querySelectorAll('a,li,span,div,button')].find(e=>e.textContent.trim()==='単勝・複勝'&&e.offsetParent!==null);if(el)el.click();});
await p.waitForTimeout(2500);t=(await p.evaluate(()=>document.body.innerText)).replace(/\n\s*\n/g,'\n');
j=t.indexOf('C\t名称\t単勝');o+='===単勝\n'+t.slice(j,j+200)+'\n';
fs.writeFileSync(out,o);await b.close();})();
