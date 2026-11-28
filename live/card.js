const { chromium } = require('playwright');const fs=require('fs');
const [pn,r,hd,out]=process.argv.slice(2);
(async()=>{const b=await chromium.launch();const p=await b.newPage();
await p.goto(`https://kyoteibiyori.com/race_shusso.php?place_no=${pn}&race_no=${r}&hiduke=${hd}&slider=0`,{waitUntil:'networkidle',timeout:60000});
await p.waitForFunction(()=>document.body.innerText.includes('1号艇'),{timeout:20000}).catch(()=>{});await p.waitForTimeout(1200);
fs.writeFileSync(out,(await p.evaluate(()=>document.body.innerText)).replace(/\n\s*\n/g,'\n'));await b.close();})();
