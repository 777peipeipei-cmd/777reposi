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
        if (k=='全国' and seen[k]==1) or (k=='当地' and seen[k]==2) or k in('平均ST',) or (k=='2連対率' and seen[k]>=2) or k in ('得点率','順位') or (k=='直近1ヶ月' and seen[k]==3) or k=='SG/G1' and seen[k]==1:
            print(k,seen[k],'\t'.join(p[1:7]))
