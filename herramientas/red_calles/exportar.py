"""red.pkl (salida de red.py) → SQL con la red de calles para la base (db/init/03_red_calles.sql y la migración 008).
Simplifica cada tramo (Ramer-Douglas-Peucker, 1,5 unidades ≈ 0,6 m) y numera nodos y tramos desde 1."""
import json, math, pickle, sys
import numpy as np

M = 0.4007          # metros por unidad del plano


def rdp(pts, tol):
    if len(pts) < 3:
        return pts
    a, b = np.array(pts[0], float), np.array(pts[-1], float)
    ab = b - a
    n = np.hypot(*ab) or 1e-9
    P = np.array(pts, float)
    d = np.abs(ab[0] * (P[:, 1] - a[1]) - ab[1] * (P[:, 0] - a[0])) / n
    i = int(d.argmax())
    if d[i] > tol:
        return rdp(pts[:i + 1], tol)[:-1] + rdp(pts[i:], tol)
    return [pts[0], pts[-1]]


R = pickle.load(open(sys.argv[1] if len(sys.argv) > 1 else 'red.pkl', 'rb'))
E, xs, ys = R['E'], R['xs'], R['ys']
ids = {}
def nid(p):
    if p not in ids:
        ids[p] = len(ids) + 1
    return ids[p]
nodos, tramos = [], []
for e in E:
    p = e['pix']
    if e['u'] == e['v'] and len(p) < 30:
        continue
    pts = [(int(xs[q]), int(ys[q])) for q in p]
    largo = sum(math.hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(pts, pts[1:])) * M
    geo = rdp(pts, 1.5)
    tramos.append((nid(e['u']), nid(e['v']), e['tipo'], geo, round(largo, 1)))
for p, i in sorted(ids.items(), key=lambda t: t[1]):
    nodos.append((i, int(xs[p]), int(ys[p])))

out = ["SET NAMES utf8mb4;",
       "-- Red de calles extraída del plano (herramientas/red_calles). INSERT IGNORE: no pisa lo que el admin ya corrigió.",
       """CREATE TABLE IF NOT EXISTS red_nodo (
  id_nodo  INT UNSIGNED PRIMARY KEY,
  x        DECIMAL(7,1) NOT NULL,
  y        DECIMAL(7,1) NOT NULL
) ENGINE=InnoDB;""",
       """CREATE TABLE IF NOT EXISTS red_tramo (
  id_tramo   INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nodo_a     INT UNSIGNED NOT NULL,
  nodo_b     INT UNSIGNED NOT NULL,
  tipo       ENUM('calle','peatonal','borde','cerrado') NOT NULL,   -- borde: junto a golf/club, a confirmar
  sentido    ENUM('doble','a_b','b_a') NOT NULL DEFAULT 'doble',    -- a_b: solo en el sentido del dibujo (de nodo_a a nodo_b)
  geometria  JSON NOT NULL,                                          -- [[x,y],...] en unidades del plano, de nodo_a a nodo_b
  largo_m    DECIMAL(8,1) NOT NULL,
  revisado   BOOLEAN NOT NULL DEFAULT FALSE,
  modificado DATETIME NULL,
  id_usuario INT UNSIGNED NULL,
  FOREIGN KEY (nodo_a) REFERENCES red_nodo(id_nodo),
  FOREIGN KEY (nodo_b) REFERENCES red_nodo(id_nodo),
  FOREIGN KEY (id_usuario) REFERENCES usuario(id_usuario),
  CHECK (JSON_VALID(geometria))
) ENGINE=InnoDB;"""]
for i in range(0, len(nodos), 100):
    out.append("INSERT IGNORE INTO red_nodo (id_nodo, x, y) VALUES " + ",".join(f"({a},{b},{c})" for a, b, c in nodos[i:i + 100]) + ";")
for i in range(0, len(tramos), 40):
    out.append("INSERT IGNORE INTO red_tramo (id_tramo, nodo_a, nodo_b, tipo, geometria, largo_m) VALUES " + ",".join(
        f"({i + k + 1},{a},{b},'{t}','{json.dumps(g, separators=(',', ':'))}',{l})" for k, (a, b, t, g, l) in enumerate(tramos[i:i + 40])) + ";")
sql = "\n".join(out) + "\n"
print(sql, end='')
sys.stderr.write(f"{len(nodos)} nodos, {len(tramos)} tramos, {sum(len(t[3]) for t in tramos)} puntos\n")
