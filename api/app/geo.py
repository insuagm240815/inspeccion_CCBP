"""Georreferencia del plano: pasa coordenadas del plano (x, y) a lat/lon y al revés.

Modelo:
1. Proyección local en metros alrededor del country: E = (lon - lon0)·kx, N = (lat - lat0)·ky.
2. Ajuste afín por mínimos cuadrados con los puntos de control: E = A·(x, y, 1), N = B·(x, y, 1)
   (corrige escala, giro y deformación general del dibujo).
3. Corrección local opcional: lo que el ajuste afín no explica en cada punto de control (residuo, en metros)
   se interpola con distancia inversa al cuadrado; lejos de los puntos se desvanece a cero.
El mismo cálculo está en web/app.js (aGeo / aPlano) para que mapa y servidor coincidan.
"""
import json
import math

import numpy as np

LAT0, LON0 = -34.6, -58.86
KX, KY = 91631.5405, 110574.0           # metros por grado de longitud y de latitud a esa latitud
ALCANCE = 600.0                         # unidades del plano (~240 m): radio en el que se siente la corrección local

# calibración original (3 puntos, 30/09/2026) expresada como afín
_A, _B, _TX, _TY = 0.25210266, -0.31173198, 472.03627, 926.57710
DEFECTO = {"lat0": LAT0, "lon0": LON0, "kx": KX, "ky": KY, "A": [_A, _B, _TX], "B": [_B, -_A, _TY],
           "local": False, "res": [], "puntos": 3, "error_m": 15.0, "origen": "inicial (3 puntos)"}


def cargar(c, fila):
    r = fila(c, "SELECT valor FROM ajuste WHERE clave='calibracion'")
    if not r:
        return DEFECTO
    v = json.loads(r["valor"]) if isinstance(r["valor"], str) else r["valor"]
    return v or DEFECTO


def _corr(cal, x, y):
    if not cal.get("local") or not cal.get("res"):
        return 0.0, 0.0
    sw, se, sn = 1.0 / ALCANCE ** 2, 0.0, 0.0
    for px, py, de, dn in cal["res"]:
        d2 = (x - px) ** 2 + (y - py) ** 2
        if d2 < 1e-6:
            return de, dn
        w = 1.0 / d2
        sw += w
        se += w * de
        sn += w * dn
    return se / sw, sn / sw


def a_metros(cal, x, y):
    A, B = cal["A"], cal["B"]
    de, dn = _corr(cal, x, y)
    return A[0] * x + A[1] * y + A[2] + de, B[0] * x + B[1] * y + B[2] + dn


def a_geo(cal, x, y):
    e, n = a_metros(cal, x, y)
    return round(n / cal["ky"] + cal["lat0"], 6), round(e / cal["kx"] + cal["lon0"], 6)


def a_plano(cal, lat, lon):
    e, n = (lon - cal["lon0"]) * cal["kx"], (lat - cal["lat0"]) * cal["ky"]
    A, B = cal["A"], cal["B"]
    det = A[0] * B[1] - A[1] * B[0]

    def inv(e_, n_):
        e_, n_ = e_ - A[2], n_ - B[2]
        return (B[1] * e_ - A[1] * n_) / det, (-B[0] * e_ + A[0] * n_) / det
    x, y = inv(e, n)
    for _ in range(4):                      # la corrección local depende de (x, y): se ajusta por iteración
        de, dn = _corr(cal, x, y)
        x, y = inv(e - de, n - dn)
    return x, y


def m_por_unidad(cal):
    A, B = cal["A"], cal["B"]
    return math.sqrt(abs(A[0] * B[1] - A[1] * B[0]))


def _afin(P):
    """P: filas (x, y, E, N). Devuelve A, B por mínimos cuadrados."""
    M = np.c_[P[:, 0], P[:, 1], np.ones(len(P))]
    A = np.linalg.lstsq(M, P[:, 2], rcond=None)[0]
    B = np.linalg.lstsq(M, P[:, 3], rcond=None)[0]
    return A, B


def calcular(puntos, local):
    """puntos: [{id, x, y, lat, lon}]. Devuelve la calibración y, para cada punto, el error del ajuste y el error
    de validación cruzada (calculando sin ese punto), que es la precisión real esperable en esa zona."""
    if len(puntos) < 3:
        raise ValueError("Hacen falta al menos 3 puntos de control activos.")
    P = np.array([[p["x"], p["y"], (p["lon"] - LON0) * KX, (p["lat"] - LAT0) * KY] for p in puntos], float)
    if np.linalg.matrix_rank(np.c_[P[:, 0], P[:, 1], np.ones(len(P))]) < 3:
        raise ValueError("Los puntos están alineados: elegí puntos repartidos en distintas direcciones.")

    def armar(Q, usar_local):
        A, B = _afin(Q)
        cal = {"lat0": LAT0, "lon0": LON0, "kx": KX, "ky": KY, "A": [float(v) for v in A], "B": [float(v) for v in B],
               "local": bool(usar_local), "res": []}
        if usar_local:
            for x, y, e, n in Q:
                cal["res"].append([float(x), float(y), float(e - (A[0] * x + A[1] * y + A[2])), float(n - (B[0] * x + B[1] * y + B[2]))])
        return cal

    cal = armar(P, local and len(P) >= 6)
    det = []
    for k, (x, y, e, n) in enumerate(P):
        ea, na = a_metros(dict(cal, local=False), x, y)
        afin = math.hypot(ea - e, na - n)
        loo = None
        if len(P) >= 5:                                   # validación cruzada: sin este punto, ¿cuánto erra acá?
            c2 = armar(np.delete(P, k, axis=0), cal["local"])
            e2, n2 = a_metros(c2, x, y)
            loo = math.hypot(e2 - e, n2 - n)
        det.append({"id": puntos[k].get("id"), "error_afin_m": round(afin, 1), "error_m": round(loo, 1) if loo is not None else None})
    errs = [d["error_m"] for d in det if d["error_m"] is not None]
    cal["puntos"] = len(P)
    cal["error_m"] = round(float(np.sqrt(np.mean(np.square(errs)))), 1) if errs else None
    cal["error_max_m"] = round(max(errs), 1) if errs else None
    cal["escala_m"] = round(m_por_unidad(cal), 5)
    return cal, det
