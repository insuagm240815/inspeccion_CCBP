import json, math, pickle, random, time, re, numpy as np, networkx as nx
from scipy.spatial import cKDTree
from PIL import Image, ImageDraw
R=pickle.load(open('red.pkl','rb')); E,xs,ys=R['E'],R['xs'],R['ys']; M=0.4007
P=json.load(open('plano.json')); lots=P['lots']
for e in E:
    p=e['pix']; d=np.hypot(np.diff(xs[p]),np.diff(ys[p]))*M; e['cum']=np.r_[0,np.cumsum(d)]
PERMITIDO={'auto':{'calle','borde'},'pie':{'calle','borde','peatonal'}}
def red(modo):
    G=nx.MultiGraph()
    for i,e in enumerate(E):
        if e['tipo'] in PERMITIDO[modo]: G.add_edge(e['u'],e['v'],key=i,w=e['cum'][-1])
    big=max(nx.connected_components(G),key=len); G=G.subgraph(big).copy()
    ids=[k for _,_,k in G.edges(keys=True)]
    pix=np.array([(k,j) for k in ids for j in range(len(E[k]['pix']))])
    tree=cKDTree(np.c_[xs[[E[k]['pix'][j] for k,j in pix]], ys[[E[k]['pix'][j] for k,j in pix]]])
    return G,pix,tree
def anclar(G,pix,tree,xy,nombre):
    dd,i=tree.query(xy); k,j=pix[i]; e=E[k]
    G.add_edge(nombre,e['u'],key=('a',k),w=e['cum'][j],via=(k,j,0))
    G.add_edge(nombre,e['v'],key=('b',k),w=e['cum'][-1]-e['cum'][j],via=(k,j,1))
    return dd*M
def plan(modo, ufs, inicio_xy):
    G,pix,tree=red(modo)
    uf2lot={n:i for i,l in enumerate(lots) for n in l['n']}
    stops=['I']+[f'U{u}' for u in ufs]; dist={}
    dist['I']=anclar(G,pix,tree,inicio_xy,'I')
    for u in ufs: dist[f'U{u}']=anclar(G,pix,tree,lots[uf2lot[u]]['c'],f'U{u}')
    t=time.time(); D={}; paths={}
    for s in stops:
        L,Pt=nx.single_source_dijkstra(G,s,weight='w')
        for q in stops: D[s,q]=L[q]; paths[s,q]=Pt[q]
    n=len(stops); orden=[0]; rest=set(range(1,n))
    while rest: j=min(rest,key=lambda j:D[stops[orden[-1]],stops[j]]); orden.append(j); rest.remove(j)
    cost=lambda o: sum(D[stops[a],stops[b]] for a,b in zip(o,o[1:]))
    mejora=True
    while mejora:
        mejora=False
        for i in range(1,n-1):
            for k in range(i+1,n):
                o=orden[:i]+orden[i:k+1][::-1]+orden[k+1:]
                if cost(o)<cost(orden)-1e-6: orden=o; mejora=True
    base=sum(D[stops[a],stops[b]] for a,b in zip(range(n-1),range(1,n)))
    return dict(G=G,stops=stops,orden=[stops[i] for i in orden],km=cost(orden)/1000,km_sin=base/1000,paths=paths,ms=(time.time()-t)*1000,anc=dist)
def trazo(G,path):
    pts=[]
    for a,b in zip(path,path[1:]):
        d=min(G[a][b].values(),key=lambda d:d['w'])
        if 'via' in d:
            k,j,lado=d['via']; p=E[k]['pix']; seg=p[:j+1][::-1] if lado==0 else p[j:]
            if a!=path[0] or True:
                seg=seg if (a in ('I',) or str(a).startswith('U')) else seg[::-1]
        else:
            k=[kk for kk in G[a][b] if G[a][b][kk] is d][0]; p=E[k]['pix']; seg=p if E[k]['u']==a else p[::-1]
        pts+= [(xs[q],ys[q]) for q in seg]
    return pts
uf2lot={n:i for i,l in enumerate(lots) for n in l['n']}
Ga,pa,ta=red('auto'); C=np.array([l['c'] for l in lots]); dm=ta.query(C)[0]*M
print('acceso lote→red vehicular: mediana %.1f m, p95 %.1f m, lotes a >40 m: %d de %d'%(np.median(dm),np.percentile(dm,95),(dm>40).sum(),len(lots)))
random.seed(11)
ufs=sorted(random.sample([u for u in uf2lot if dm[uf2lot[u]]<40],15))
inicio=(1620,40)
ra=plan('auto',ufs,inicio); rp=plan('pie',ufs,inicio)
print('UF:',ufs)
print('vehículo: %.2f km optimizado vs %.2f km en orden de U.F. (%.0f%% menos) · cálculo %.0f ms'%(ra['km'],ra['km_sin'],100*(1-ra['km']/ra['km_sin']),ra['ms']))
print('a pie:    %.2f km optimizado vs %.2f km en orden de U.F. (%.0f%% menos)'%(rp['km'],rp['km_sin'],100*(1-rp['km']/rp['km_sin'])))
print('orden vehículo:',' → '.join(s.lstrip('U') for s in ra['orden']))
S=0.5
def base():
    im=Image.new('RGB',(1975,1675),'white'); d=ImageDraw.Draw(im)
    def polys(dd):
        for seg in re.split(r'(?=M)',dd):
            pts=[tuple(map(float,p.split(','))) for p in re.findall(r'-?[\d.]+,-?[\d.]+',seg)]
            if pts: yield pts
    for l in lots:
        for pts in polys(l['d']): d.polygon([(x*S,y*S) for x,y in pts], fill=(232,232,232), outline=(212,212,212))
    col={'calle':(50,110,215),'peatonal':(240,140,0),'borde':(150,70,190)}
    for e in E:
        p=e['pix']; d.line([(xs[q]*S,ys[q]*S) for q in p[::3]]+[(xs[p[-1]]*S,ys[p[-1]]*S)], fill=col[e['tipo']], width=3 if e['tipo']!='peatonal' else 2)
    return im,d
im,d=base(); im.save('red.png')
for nom,r in (('ruta_auto.png',ra),('ruta_pie.png',rp)):
    im,d=base(); G=r['G']
    for a,b in zip(r['orden'],r['orden'][1:]):
        pts=trazo(G,r['paths'][a,b]); d.line([(x*S,y*S) for x,y in pts[::2]], fill=(220,30,30), width=6)
    for k,s in enumerate(r['orden']):
        x,y=(inicio if s=='I' else lots[uf2lot[int(s[1:])]]['c']); x,y=x*S,y*S
        d.ellipse((x-12,y-12,x+12,y+12),fill=(25,25,25) if s=='I' else (220,30,30)); d.text((x-4 if k<10 else x-7,y-6),'I' if s=='I' else str(k),fill='white')
    im.save(nom)
