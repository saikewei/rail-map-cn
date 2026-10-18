import json, math, collections, statistics
base='data/raw/'
net=json.load(open(base+'rp_web/data/network.json'))
names=net['names']; q=net['q']
edges=[]
for e in net['edges']:
    n=(len(e)-3)//2
    edges.append({'cls':e[0],'name':names[e[1]],'traffic':e[2],'n':n,'len':None})
st=json.load(open(base+'rp_web/data/stations.json'))
F={k:i for i,k in enumerate(st['fields'])}
stations=[]
for r in st['rows']:
    stations.append({'name':r[F['name']],'lon':r[F['x']]/1e5,'lat':r[F['y']]/1e5,'rank':r[F['rank']]})
tr=json.load(open(base+'rp_web/data/trains.json'))
TF={k:i for i,k in enumerate(tr['fields'])}
paths=json.load(open(base+'rp_web/data/paths.json'))
def decode_path(p):
    if p[0]==-1: return p
    out=[p[0],p[1],p[2]]; prev=abs(p[2])
    for v in p[3:]:
        neg=v&1; z=v>>1
        d=-((z+1)//2) if z&1 else z//2
        prev+=d
        out.append(-prev if neg else prev)
    return out
segs=[decode_path(p) for p in paths['segs']]
# edge length calc
def haversine(a,b,c,d):
    R=6371008.8; rad=math.pi/180
    dlat=(d-b)*rad; dlon=(c-a)*rad
    x=math.sin(dlat/2)**2+math.cos(b*rad)*math.cos(d*rad)*math.sin(dlon/2)**2
    return 2*R*math.asin(min(1,math.sqrt(x)))
for i,e in enumerate(net['edges']):
    n=(len(e)-3)//2
    x=y=0; lon0=lat0=None; L=0
    for k in range(n):
        x+=e[3+2*k]; y+=e[4+2*k]
        lon=x/q; lat=y/q
        if k: L+=haversine(lon0,lat0,lon,lat)
        lon0,lat0=lon,lat
    edges[i]['len']=L
# line observations
obs=collections.defaultdict(list)
# each train's stops; segment duration and distance
for row in tr['rows']:
    stops=row[TF['stops']]
    ns=len(stops)//5
    for k in range(ns-1):
        s0=stops[5*k:5*k+5]; s1=stops[5*k+5:5*k+10]
        segidx=abs(s0[4])-1
        if segidx<0 or segidx>=len(segs): continue
        dur=s1[1]-s0[2]
        dist=(s1[3]-s0[3])*10  # m
        if dur<=0 or dist<=0: continue
        avg=dist/dur*60/1000  # km/h
        p=segs[segidx]
        if p[0]==-1: continue
        es=p[3:]
        # record segment-level obs for every line in path
        lnames=set()
        for se in es:
            e=abs(se)-1
            nm=edges[e]['name']
            if nm: lnames.add(nm)
        for nm in lnames:
            obs[nm].append((avg,dist/1000,dur,row[TF['no']]))
# summarize
summary=[]
for nm,arr in obs.items():
    # long segments for stable
    long=[a for a in arr if a[1]>=60]
    if not long: long=[a for a in arr if a[1]>=30]
    if not long: continue
    avgs=sorted(a[0] for a in long)
    p95=avgs[int(len(avgs)*0.95)-1]
    mx=avgs[-1]
    med=statistics.median(avgs)
    summary.append((p95,mx,med,len(arr),nm))
print('unique observed lines',len(summary))
for p95,mx,med,n,nm in sorted(summary,reverse=True)[:250]:
    print(f'{p95:6.1f} p95  max {mx:6.1f} med {med:6.1f} n={n:4d} {nm}')
