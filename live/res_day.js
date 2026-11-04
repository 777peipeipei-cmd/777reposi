const { chromium } = require('playwright');const fs=require('fs');
const [pn,hd,out]=process.argv.slice(2);
(async()=>{const b=await chromium.launch();const p=await b.newPage();
for(let r=1;r<=12;r++){
 await p.goto(`https://kyoteibiyori.com/race_shusso.php?place_no=${pn}&race_no=${r}&hiduke=${hd}&slider=7`,{waitUntil:'networkidle',timeout:60000}).catch(()=>{});
 await p.waitForTimeout(2000);let t=(await p.evaluate(()=>document.body.innerText)).replace(/\n\s*\n/g,'\n');
 const i=t.indexOf('着\t枠');if(i<0){console.log(r,'未確定');break;}
 const rows=t.slice(i).split('\n').slice(1,7).map(l=>l.split('\t'));
 const k=(t.match(/\n(逃げ|差し|まくり差し|まくり|抜き|恵まれ)\t/)||[])[1]||'';
 const m=t.match(/3連単\t(\S+)\t([\d,]+)円\t(\d+)/);
 console.log(r, rows.map(x=>x[1]).slice(0,3).join('-'), m?m[2]+'円 '+m[3]+'番人気':'', k);
 await p.waitForTimeout(1000);}
await b.close();})();
