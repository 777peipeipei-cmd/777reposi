// usage: node live/schedule.js YYYYMMDD [place...]  -> prints "place race deadline name" for each race
// place: 4=平和島 1=桐生 24=大村 15=丸亀 12=住之江 (default all five)
const { chromium } = require('playwright');
const [hd, ...ps] = process.argv.slice(2);
const places = ps.length ? ps.map(Number) : [4, 1, 24, 15, 12];
(async () => {
  const b = await chromium.launch(); const p = await b.newPage();
  for (const pn of places) {
    await p.goto(`https://kyoteibiyori.com/race_ichiran.php?place_no=${pn}&race_no=1&hiduke=${hd}`, { waitUntil: 'networkidle', timeout: 60000 }).catch(() => {});
    await p.waitForFunction(() => document.body.innerText.includes('締切時刻'), { timeout: 20000 }).catch(() => {});
    await p.waitForTimeout(1500);
    const t = await p.evaluate(() => document.body.innerText);
    const re = /(\d+)R (\S*?)締切時刻：(\d+:\d+)(\S*)/g; let m, n = 0;
    while ((m = re.exec(t))) { console.log(pn, m[1], m[3], m[2] + (m[4] || '')); n++; }
    if (!n) console.log(pn, 'none');
    await p.waitForTimeout(1500);
  }
  await b.close();
})();
