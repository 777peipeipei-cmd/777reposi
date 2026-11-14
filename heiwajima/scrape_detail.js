// usage: node scrape.js dates.txt  (one YYYYMMDD per line); caches to /tmp/hw_year/races/<date>_<r>.json
const { chromium } = require('playwright');const fs=require('fs');
const dir='/tmp/hw_year/races';fs.mkdirSync(dir,{recursive:true});
const days=JSON.parse(fs.readFileSync('/tmp/hw_year/days.json'));
const dates=fs.readFileSync(process.argv[2],'utf8').split('\n').filter(x=>x);
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const KEEP=new Set(['race_name','race_no','course','race_rank','grade','rank','player_no','player_name','age','taiju','kyubetsu','zenkoku_shoritsu','zenkoku_niren','zenkoku_sanren','touchi_shoritsu','touchi_niren','touchi_sanren','motor_niren','motor_sanren','boat_niren','boat_sanren','motor','boat','display','shinnyuu','start','flying','ave_start','start_ave','kimete','wind_speed','wave','weather','zenken_time','saikin_shoritsu','seibetsu','konki_nouryoku_shisuu',
...[1,2,3,4,5,6].flatMap(c=>[`course${c}_1_ave`,`course${c}_2_ave`,`course${c}_3_ave`,`start${c}_ave`,`course${c}_shinnyu`])]);
function scal(o){const r={};for(const[k,v]of Object.entries(o)){if(KEEP.has(k))r[k]=v;}return r;}
(async()=>{const b=await chromium.launch();const ctx=await b.newContext();
await ctx.route('**/*',rt=>{const u=rt.request().url(),t=rt.request().resourceType();
 if(!u.startsWith('https://kyoteibiyori.com')||['image','font','media','stylesheet'].includes(t))return rt.abort();return rt.continue();});
const p=await ctx.newPage();
for(const d of dates){const n=days[d]||0;
 for(let r=1;r<=n;r++){const f=`${dir}/${d}_${r}.json`;if(fs.existsSync(f))continue;
  const t0=Date.now();let detail=null;
  const h=async resp=>{if(resp.url().includes('request_race_shusso_detail')){try{detail=JSON.parse(await resp.text())}catch(e){}}};
  p.on('response',h);
  try{await p.goto(`https://kyoteibiyori.com/race_shusso.php?place_no=4&race_no=${r}&hiduke=${d}&slider=0`,{waitUntil:'domcontentloaded',timeout:60000});
   for(let i=0;i<40&&!detail;i++)await sleep(250);}catch(e){console.log('ERR',d,r,e.message)}
  p.off('response',h);
  if(!detail){console.log('NODETAIL',d,r);await sleep(3000);continue;}
  const post=async ep=>{await sleep(1000);return await p.evaluate(async([ep,body])=>{const res=await fetch('/'+ep,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'data='+encodeURIComponent(body)});return JSON.parse(await res.text());},[ep,JSON.stringify({place_no:'4',race_no:String(r),hiduke:d})]);};
  let ch=null,tri=null;try{ch=await post('request_chokuzen_info_v2.php');tri=await post('request_rentan_three.php');}catch(e){console.log('POSTERR',d,r,e.message)}
  fs.writeFileSync(f,JSON.stringify({date:d,race:r,boats:detail.race_list.map(scal),chokuzen:(ch||[]).map(x=>{const{comment,image,name_kana,...rest}=x;return rest}),trifecta:tri}));
  console.log(d,r,((Date.now()-t0)/1000).toFixed(1)+'s');await sleep(1000);}}
await b.close();})();
