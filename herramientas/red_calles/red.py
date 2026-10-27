import json, math, time, numpy as np, networkx as nx
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
t0=time.time()
z=np.load('sk.npz'); sk,dt,borde=z['sk'],z['dt'],z['borde']
M=0.4007
ys,xs=np.nonzero(sk); idx=-np.ones(sk.shape,np.int64); idx[ys,xs]=np.arange(len(xs))
G=nx.Graph()
for dy,dx in ((0,1),(1,0),(1,1),(1,-1)):
    w=math.hypot(dx,dy)
    y2,x2=ys+dy,xs+dx; ok=(y2>=0)&(y2<sk.shape[0])&(x2>=0)&(x2<sk.shape[1])
    a=idx[ys[ok],xs[ok]]; b=idx[y2[ok],x2[ok]]; m=b>=0
    G.add_weighted_edges_from(zip(a[m].tolist(),b[m].tolist(),[w]*int(m.sum())))
# quitar diagonales redundantes (triángulos) para que los nodos de grado 2 sean cadenas limpias
for u,v,d in list(G.edges(data=True)):
    if d['weight']>1 and len(set(G[u])&set(G[v]))>0: G.remove_edge(u,v)
print('pixel graph',G.number_of_nodes(),G.number_of_edges(), round(time.time()-t0,1))
# contraer cadenas en aristas
nodos={n for n in G if G.degree(n)!=2}
aristas=[]; visto=set()
for s in nodos:
    for nb in G[s]:
        if (s,nb) in visto: continue
        path=[s,nb]; prev,cur=s,nb
        while cur not in nodos:
            nxt=[x for x in G[cur] if x!=prev]
            if not nxt: break
            prev,cur=cur,nxt[0]; path.append(cur)
        visto.add((path[-1],path[-2])); visto.add((s,nb))
        aristas.append(path)
# ciclos aislados sin nodos (anillos) — ignorar
E=[]
for p in aristas:
    L=sum(G[a][b]['weight'] for a,b in zip(p,p[1:]))
    core=p[6:-6] if len(p)>14 else p
    wmed=2*float(np.median(dt[ys[core],xs[core]]))*M
    E.append(dict(u=p[0],v=p[-1],pix=p,len_m=L*M,ancho=wmed,borde=float(borde[ys[p],xs[p]].mean())))
def tipo(e):
    if e['borde']>0.5: return 'borde'          # junto a golf/club: puede ser calle o el fondo de los lotes; a confirmar
    return 'peatonal' if e['ancho']<6.5 else 'calle'
for e in E: e['tipo']=tipo(e)
# angostamientos cortos entre calles (puentes, esquinas) → calle
for _ in range(2):
    tipos={}
    for e in E: tipos.setdefault(e['u'],set()).add(e['tipo']); tipos.setdefault(e['v'],set()).add(e['tipo'])
    for e in E:
        if e['tipo']=='peatonal' and e['len_m']<25 and 'calle' in tipos[e['u']] and 'calle' in tipos[e['v']]: e['tipo']='calle'
# podar espolones cortos
for _ in range(4):
    deg={}
    for e in E: deg[e['u']]=deg.get(e['u'],0)+1; deg[e['v']]=deg.get(e['v'],0)+1
    E=[e for e in E if not ((deg[e['u']]==1 or deg[e['v']]==1) and e['len_m']<12)]
N=nx.MultiGraph()
for i,e in enumerate(E): N.add_edge(e['u'],e['v'],key=i,len=e['len_m'],tipo=e['tipo'])
comps=sorted(nx.connected_components(N),key=len,reverse=True)
print('aristas',len(E),'nodos',N.number_of_nodes(),'componentes',len(comps),[len(c) for c in comps[:8]])
N2=nx.MultiGraph()
for i,e in enumerate(E): N2.add_edge(e['u'],e['v'],key=i,len=e['len_m'])
keep=set()
for c in nx.connected_components(N2):
    if sum(d['len'] for _,_,d in N2.subgraph(c).edges(data=True))>150: keep|=c
E=[e for e in E if e['u'] in keep]
print('tras limpiar componentes chicas:',len(E))
for t in ('calle','peatonal','borde'):
    print(t, round(sum(e['len_m'] for e in E if e['tipo']==t)/1000,2),'km', sum(1 for e in E if e['tipo']==t),'tramos')
import pickle; pickle.dump(dict(E=E,xs=xs,ys=ys),open('red.pkl','wb'))
