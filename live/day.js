const { chromium } = require('playwright');const fs=require('fs');
const [pn,hd,out]=process.argv.slice(2);
(async()=>{const b=await chromium.launch();const p=await b.newPage();
for(let r=1;r<=12;r++){for(const sl of ['0','4']){
 await p.goto(`https://kyoteibiyori.com/race_shusso.php?place_no=${pn}&race_no=${r}&hiduke=${hd}&slider=${sl}`,{waitUntil:'networkidle',timeout:60000}).catch(e=>console.log('ERR',r,sl));
 await p.waitForFunction(()=>document.body.innerText.includes('1号艇'),{timeout:20000}).catch(()=>{});
 await p.waitForTimeout(1500);
 fs.writeFileSync(`${out}/r${r}_s${sl}.txt`,(await p.evaluate(()=>document.body.innerText)).replace(/\n\s*\n/g,'\n'));
 await p.waitForTimeout(1000);}}
await b.close();})();
