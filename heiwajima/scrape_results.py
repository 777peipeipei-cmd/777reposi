import json,os,time,subprocess
days=json.load(open('/tmp/hw_year/days.json'))
out='/tmp/hw_year/results'; os.makedirs(out,exist_ok=True)
KEEP=['race_name','race_no','course','race_rank','grade','rank','player_no','player_name','shinnyuu','start','kimete','wind','wind_speed','wave','weather','shimekiri']
def post(ep,body):
    for a in range(4):
        r=subprocess.run(['curl','-sS','-m','30','-X','POST','https://kyoteibiyori.com/'+ep,'--data-urlencode','data='+json.dumps(body)],capture_output=True,text=True)
        try: return json.loads(r.stdout)
        except Exception: time.sleep(2**(a+1))
    return None
for d in sorted(k for k,v in days.items() if v):
    for r in range(1,days[d]+1):
        f=f'{out}/{d}_{r}.json'
        if os.path.exists(f): continue
        b={'place_no':'4','race_no':str(r),'hiduke':d}
        k=post('request_race_kekka.php',b); time.sleep(1)
        t=post('request_rentan_three.php',b); time.sleep(1)
        if k is None: print('FAIL',d,r,flush=True); continue
        json.dump({'date':d,'race':r,'boats':[{x:e.get(x) for x in KEEP} for e in k],'trifecta':t},open(f,'w'),ensure_ascii=False)
    print('done',d,flush=True)
