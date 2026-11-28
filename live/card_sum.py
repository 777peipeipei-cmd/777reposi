import sys,re
t=open(sys.argv[1]).read();L=t.split('\n')
i=[k for k,l in enumerate(L) if l.startswith('情報\t1号艇')][0]
print('名前',L[i+2]);print('級別',L[i+3])
want={'全国':0,'当地':1}
seen={}
for l in L:
    p=l.split('\t')
    if len(p)>=7:
        k=p[0];seen[k]=seen.get(k,0)+1
        if (k=='全国' and seen[k]==1) or (k=='当地' and seen[k]==2) or k in('平均ST',) or k in ('得点率','順位') or (k=='直近1ヶ月' and seen[k]==3) or k=='SG/G1' and seen[k]==1:
            print(k,seen[k],'\t'.join(p[1:7]))

# モーター・ボートの2連対率（見出し行の直後の「2連対率」）
for k,l in enumerate(L):
    if l.strip() in ('モーター','ボート') and k+1<len(L) and L[k+1].startswith('2連対率\t'):
        print(l.strip()+'2連', '\t'.join(L[k+1].split('\t')[1:7]))

# 事故率（期中の事故点/出走回数。0.70以上でB2降格）
for k,l in enumerate(L):
    if l.startswith('事故率\t') and len(l.split('\t'))>=7:
        print('事故率', '\t'.join(l.split('\t')[1:7])); break

# 選手の色（前付け・アウトに出る）: live/racer_style.csv（全24場1年分）
try:
    import csv, os
    st={r['名前']:r for r in csv.DictReader(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'racer_style.csv')))}
    i=[k for k,l in enumerate(L) if l.startswith('情報\t1号艇')][0]
    names=L[i+2].split('\t')[:6]
    marks=[]
    for n in names:
        r=st.get(n.replace(' ','').replace('\u3000',''))
        if not r: marks.append('-'); continue
        m=[]
        if float(r['前付け率'])>=30: m.append('前付け'+r['前付け率']+'%')
        if float(r['外に出る率'])>=10: m.append('外に出る'+r['外に出る率']+'%')
        w=len(marks)+1
        key={1:'c1_1着',2:'c2_1着',4:'c4_1着',5:'c5_3着内',6:'c6_3着内'}.get(w)
        lab={1:'イン',2:'2コース',4:'カド',5:'5コース3着',6:'6コース3着'}.get(w)
        if key and r.get(key) not in (None,''):
            d=float(r[key])
            if d>=5: m.append(lab+'得意+%.0f'%d)
            elif d<=-5: m.append(lab+'苦手%.0f'%d)
        if r.get('平均ST') not in (None,''):
            if float(r['平均ST'])<=0.13: m.append('ST早い')
            elif float(r['平均ST'])>=0.19: m.append('ST遅い')
        marks.append('/'.join(m) or '普通')
    print('選手の色', '\t'.join(marks))
except Exception as e:
    print('選手の色 読めず', e)
