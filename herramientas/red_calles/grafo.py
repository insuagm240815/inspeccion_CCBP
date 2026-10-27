import json, re, time, numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from skimage.morphology import skeletonize, binary_closing, disk, remove_small_objects
t0=time.time()
P=json.load(open('plano.json'))
W,H=3950,3350
M_U=(0.25210266**2+0.31173198**2)**0.5   # metros por unidad del plano
def polys(d):
    out=[]
    for seg in re.split(r'(?=M)',d):
        pts=[tuple(map(float,p.split(','))) for p in re.findall(r'-?[\d.]+,-?[\d.]+',seg)]
        if pts: out.append((pts, seg.strip().endswith('Z')))
    return out
obs=Image.new('L',(W,H),0); d=ImageDraw.Draw(obs)
for l in P['lots']:
    for pts,z in polys(l['d']): d.polygon(pts, fill=255, outline=255)
lots_only=np.array(obs)>0
for p in P['plazas']:
    for pts,z in polys(p): d.polygon(pts, fill=255)
for pts,z in polys(P['water']): d.line(pts, fill=255, width=4)
O=np.array(obs)>0
O=ndi.binary_dilation(O, iterations=1)           # cierra las rendijas de 1 px entre lotes vecinos
# zona del country: cierre grande de los lotes, con huecos rellenos
region=ndi.binary_fill_holes(binary_closing(ndi.binary_dilation(lots_only,iterations=3), disk(45)))
region=ndi.binary_erosion(region, iterations=8)
free=region & ~O
free=remove_small_objects(free, 400)
dt0=ndi.distance_transform_edt(free)
abierto=free & (dt0>35)                          # interior de golf/club: más de 14 m de cualquier lote
free=free & ~abierto                             # queda una franja de 14 m junto a los lotes
free=remove_small_objects(free, 400)
dt=ndi.distance_transform_edt(free)              # semiancho del pasillo en unidades
borde=ndi.binary_dilation(abierto, iterations=40)
sk=skeletonize(free)
print('raster', round(time.time()-t0,1),'s; skeleton px', sk.sum())
np.savez_compressed('sk.npz', sk=sk, dt=dt.astype(np.float32), free=free, region=region, borde=borde)
