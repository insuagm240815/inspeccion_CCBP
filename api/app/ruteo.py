"""Ruteo sobre la red de calles del plano: mejor orden de visitas para el itinerario diario.

1. Cada parada (U.F. o novedad) se ancla al punto más cercano de un tramo transitable.
2. Dijkstra (NetworkX) da la distancia real por calle entre cada par de paradas.
3. Orden: las paradas fijadas van primero, en el orden elegido; el resto se ordena para recorrer
   lo mínimo — exacto (programación dinámica de Held-Karp) hasta 11 paradas libres,
   vecino más cercano + 2-opt por encima.

Modos: 'vehiculo' usa calles y bordes respetando la mano; 'pie' suma los pasos peatonales y
camina en ambos sentidos. Los tramos 'cerrado' no se usan nunca.
"""
import json
import math
import threading

import networkx as nx
import numpy as np

M_POR_UNIDAD = 0.4007                       # metros por unidad del plano (calibración)
VELOCIDAD_KMH = {'vehiculo': 20.0, 'pie': 4.5}
TIPOS = {'vehiculo': ('calle', 'borde'), 'pie': ('calle', 'borde', 'peatonal')}
EXACTO_HASTA = 11
LEJOS_M = 60

_lock = threading.Lock()
_cache = {'ver': None, 'red': None}


class SinRuta(ValueError):
    pass


def invalidar():
    with _lock:
        _cache['ver'] = None


def _cargar(c, filas):
    with _lock:
        if _cache['ver'] is not None:
            return _cache['red']
    tramos = []
    for t in filas(c, "SELECT id_tramo, nodo_a, nodo_b, tipo, sentido, geometria, largo_m, revisado FROM red_tramo"):
        geo = json.loads(t['geometria']) if isinstance(t['geometria'], str) else t['geometria']
        p = np.array(geo, float)
        seg = np.hypot(*np.diff(p, axis=0).T) if len(p) > 1 else np.zeros(0)
        largo = float(t['largo_m'])
        esc = largo / max(seg.sum(), 1e-9)          # la geometría simplificada es apenas más corta que el tramo real
        tramos.append(dict(id=t['id_tramo'], a=t['nodo_a'], b=t['nodo_b'], tipo=t['tipo'], sentido=t['sentido'],
                           revisado=bool(t['revisado']), geo=p, cum=np.r_[0, np.cumsum(seg * esc)], largo=largo))
    red = {'tramos': {t['id']: t for t in tramos}}
    for modo, tipos in TIPOS.items():
        ok = [t for t in tramos if t['tipo'] in tipos and len(t['geo']) > 1]
        filas_seg = []
        for t in ok:
            for i in range(len(t['geo']) - 1):
                filas_seg.append((t['id'], i, *t['geo'][i], *t['geo'][i + 1], t['cum'][i], t['cum'][i + 1]))
        red[modo] = {'seg': np.array(filas_seg, float) if filas_seg else np.zeros((0, 8)), 'tramos': [t['id'] for t in ok]}
    with _lock:
        _cache.update(ver=1, red=red)
    return red


def _anclar(red, modo, x, y):
    S = red[modo]['seg']
    if not len(S):
        raise SinRuta('La red de calles está vacía.')
    x1, y1, x2, y2 = S[:, 2], S[:, 3], S[:, 4], S[:, 5]
    dx, dy = x2 - x1, y2 - y1
    l2 = np.maximum(dx * dx + dy * dy, 1e-9)
    u = np.clip(((x - x1) * dx + (y - y1) * dy) / l2, 0, 1)
    px, py = x1 + u * dx, y1 + u * dy
    d = np.hypot(px - x, py - y)
    i = int(d.argmin())
    tid = int(S[i, 0])
    s = float(S[i, 6] + u[i] * (S[i, 7] - S[i, 6]))
    return {'tramo': tid, 's': s, 'x': float(px[i]), 'y': float(py[i]), 'dist_m': float(d[i] * M_POR_UNIDAD)}


def _sentidos(t, modo):
    if modo == 'pie':
        return True, True
    return t['sentido'] in ('doble', 'a_b'), t['sentido'] in ('doble', 'b_a')


def _grafo(red, modo, anclas):
    G = nx.MultiDiGraph()
    for tid in red[modo]['tramos']:
        t = red['tramos'][tid]
        ida, vuelta = _sentidos(t, modo)
        if ida:
            G.add_edge(('n', t['a']), ('n', t['b']), w=t['largo'], via=(tid, 0.0, t['largo']))
        if vuelta:
            G.add_edge(('n', t['b']), ('n', t['a']), w=t['largo'], via=(tid, t['largo'], 0.0))
    por_tramo = {}
    for k, an in anclas.items():
        t = red['tramos'][an['tramo']]
        ida, vuelta = _sentidos(t, modo)
        s, L, P = an['s'], t['largo'], ('p', k)
        G.add_node(P)
        if ida:
            G.add_edge(('n', t['a']), P, w=s, via=(t['id'], 0.0, s))
            G.add_edge(P, ('n', t['b']), w=L - s, via=(t['id'], s, L))
        if vuelta:
            G.add_edge(('n', t['b']), P, w=L - s, via=(t['id'], L, s))
            G.add_edge(P, ('n', t['a']), w=s, via=(t['id'], s, 0.0))
        por_tramo.setdefault(t['id'], []).append(k)
    for tid, ks in por_tramo.items():             # dos paradas sobre el mismo tramo: se conectan directo
        t = red['tramos'][tid]
        ida, vuelta = _sentidos(t, modo)
        for i in ks:
            for j in ks:
                si, sj = anclas[i]['s'], anclas[j]['s']
                if i != j and ((sj >= si and ida) or (sj < si and vuelta)):
                    G.add_edge(('p', i), ('p', j), w=abs(sj - si), via=(tid, si, sj))
    return G


def _sub(t, s1, s2):
    """Puntos del tramo entre las distancias s1 y s2 (en ese sentido)."""
    a, b = min(s1, s2), max(s1, s2)
    cum, geo = t['cum'], t['geo']

    def punto(s):
        i = int(np.clip(np.searchsorted(cum, s) - 1, 0, len(cum) - 2))
        f = 0 if cum[i + 1] == cum[i] else (s - cum[i]) / (cum[i + 1] - cum[i])
        return list(geo[i] + f * (geo[i + 1] - geo[i]))
    pts = [punto(a)] + [list(geo[i]) for i in range(len(cum)) if a < cum[i] < b] + [punto(b)]
    return pts if s1 <= s2 else pts[::-1]


def _orden(D, n, fijas, libres, volver):
    """D[i][j] distancias; 0 = inicio. Devuelve la secuencia de índices."""
    seq = [0] + fijas
    if not libres:
        return seq + ([0] if volver else [])
    u0 = seq[-1]
    fin = (lambda j: D[j][0]) if volver else (lambda j: 0.0)
    if len(libres) <= EXACTO_HASTA:                   # Held-Karp
        L = libres
        dp = {(1 << i, i): (D[u0][L[i]], None) for i in range(len(L))}
        for mask in range(1, 1 << len(L)):
            for i in range(len(L)):
                if not mask & (1 << i) or (mask, i) not in dp:
                    continue
                c, _ = dp[(mask, i)]
                for j in range(len(L)):
                    if mask & (1 << j):
                        continue
                    nm = mask | (1 << j)
                    nc = c + D[L[i]][L[j]]
                    if (nm, j) not in dp or nc < dp[(nm, j)][0]:
                        dp[(nm, j)] = (nc, i)
        full = (1 << len(L)) - 1
        j = min(range(len(L)), key=lambda j: dp[(full, j)][0] + fin(L[j]))
        camino, mask = [], full
        while j is not None:
            camino.append(L[j])
            _, p = dp[(mask, j)]
            mask &= ~(1 << j)
            j = p
        orden = camino[::-1]
    else:                                             # vecino más cercano + 2-opt
        orden, resto, u = [], set(libres), u0
        while resto:
            v = min(resto, key=lambda v: D[u][v])
            orden.append(v)
            resto.remove(v)
            u = v

        def costo(o):
            return D[u0][o[0]] + sum(D[a][b] for a, b in zip(o, o[1:])) + fin(o[-1])
        mejor = True
        while mejor:
            mejor = False
            for i in range(len(orden) - 1):
                for k in range(i + 1, len(orden)):
                    o = orden[:i] + orden[i:k + 1][::-1] + orden[k + 1:]
                    if costo(o) < costo(orden) - 1e-6:
                        orden, mejor = o, True
    return seq + orden + ([0] if volver else [])


def planificar(c, filas, modo, inicio, paradas, volver):
    """inicio = {x, y}; paradas = [{tipo, ref, x, y, fijada}]. Devuelve el recorrido ordenado con su trazo."""
    if modo not in TIPOS:
        raise SinRuta('Modo no válido.')
    red = _cargar(c, filas)
    puntos = [inicio] + paradas
    anclas = {i: _anclar(red, modo, float(p['x']), float(p['y'])) for i, p in enumerate(puntos)}
    G = _grafo(red, modo, anclas)
    n = len(puntos)
    D, caminos = [[math.inf] * n for _ in range(n)], {}
    for i in range(n):
        L, P = nx.single_source_dijkstra(G, ('p', i), weight='w')
        for j in range(n):
            if ('p', j) in L:
                D[i][j] = L[('p', j)]
                caminos[i, j] = P[('p', j)]
    malos = [paradas[j - 1]['ref'] for j in range(1, n) if D[0][j] == math.inf or (volver and D[j][0] == math.inf)]
    if malos:
        raise SinRuta(f"No hay camino {'en vehículo ' if modo == 'vehiculo' else 'a pie '}hasta: {', '.join(malos)}. "
                      "Revisá la red de calles o probá el otro modo.")
    fijas = [i for i in range(1, n) if paradas[i - 1].get('fijada')]
    libres = [i for i in range(1, n) if not paradas[i - 1].get('fijada')]
    seq = _orden(D, n, fijas, libres, volver)
    tramos_usados, piernas = set(), []
    for a, b in zip(seq, seq[1:]):
        pts = [[anclas[a]['x'], anclas[a]['y']]]
        nodos = caminos[a, b]
        for u, v in zip(nodos, nodos[1:]):
            e = min(G[u][v].values(), key=lambda d: d['w'])
            tid, s1, s2 = e['via']
            tramos_usados.add(tid)
            pts += _sub(red['tramos'][tid], s1, s2)[1:]
        km = D[a][b] / 1000
        piernas.append({'desde': a, 'hasta': b, 'km': round(km, 3), 'min': round(km / VELOCIDAD_KMH[modo] * 60, 1),
                        'geo': [[round(x, 1), round(y, 1)] for x, y in pts]})
    km = sum(p['km'] for p in piernas)
    avisos = []
    sin_rev = [t for t in tramos_usados if red['tramos'][t]['tipo'] == 'borde' and not red['tramos'][t]['revisado']]
    if sin_rev:
        avisos.append(f"El recorrido usa {len(sin_rev)} tramo(s) junto al golf o al club que todavía no se confirmaron como calle.")
    for i, an in anclas.items():
        if i and an['dist_m'] > LEJOS_M:
            avisos.append(f"{paradas[i - 1]['ref']} queda a {round(an['dist_m'])} m de la calle más cercana.")
    orden = [{**paradas[i - 1], 'idx': i - 1} for i in seq if i]
    return {'modo': modo, 'volver': volver, 'secuencia': seq, 'paradas': orden,
            'piernas': piernas, 'km': round(km, 2), 'minutos': round(km / VELOCIDAD_KMH[modo] * 60),
            'avisos': avisos, 'inicio': {**inicio, 'xs': anclas[0]['x'], 'ys': anclas[0]['y']}}
