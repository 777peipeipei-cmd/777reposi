import json,os,time,subprocess,datetime
out='/tmp/hw_year/days.json'
days=json.load(open(out)) if os.path.exists(out) else {}
d=datetime.date(2025,11,1)
while d<=datetime.date(2026,10,31):
    k=d.strftime('%Y%m%d')
    if k not in days:
        r=subprocess.run(['curl','-sS','-m','20','-X','POST','https://kyoteibiyori.com/request_place_seiseki.php','--data-urlencode','data={"place_no":"4","hiduke":"%s"}'%k],capture_output=True,text=True)
        try: days[k]=json.loads(r.stdout).get('race_count',0)
        except Exception: days[k]=None
        json.dump(days,open(out,'w')); time.sleep(1)
    d+=datetime.timedelta(days=1)
print(sum(1 for v in days.values() if v), 'race days;', sum(v or 0 for v in days.values()),'races; errors',sum(1 for v in days.values() if v is None))
