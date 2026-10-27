"""Importación de la planilla completa de Construcciones ("Base de datos V1.0", .xlsx) — solo admin.

Hojas que se importan: Catálogo, Visitas, Hallazgos, Historial (de faltas y de marcas) y Marcas.
Las demás (Observaciones, Urgencias, Relevamientos, Fotos con links de Drive, Regularización…)
se informan como no importadas: esta app todavía no tiene esos módulos.

- Los números originales (V-0001, F-0001, M-0001) se conservan si están libres en esta base;
  si ya están ocupados se asigna uno nuevo y el historial guarda el original.
- Volver a subir el archivo (o una versión más nueva) no duplica: lo ya importado se actualiza
  con los valores de la planilla (estado, revisión, cierre, observación) y solo entran las filas nuevas.
- Todo corre en una transacción: la revisión previa es una pasada completa que se deshace al final.
"""
import datetime as dt
import hashlib
import io
import json
import re
import unicodedata

from .db import ejecutar, fila, filas, siguiente

MAX_BYTES = 15 * 1024 * 1024
MAX_ERRORES = 300

ESTADOS = ['Pendiente', 'Aviso verbal', 'Aviso por folleto', 'Derivado a Comisión',
           'Notificado/Intimado', 'En proceso de resolución', 'Resuelto', 'Verificado sin falta']
CERRADOS = ['Resuelto', 'Verificado sin falta']
ORIGENES = ['Recorrido de inspección', 'Reclamo de vecino', 'Reclamo del servicio de recolección', 'Revisión de caso']
CONTACTOS = ['Hablé con el residente', 'No había nadie', 'No había nadie, dejé aviso escrito',
             'Hablé con personal de poda, pasto, obra o limpieza', 'Pendiente de visita']
M_ESTADOS = ['Relevado', 'Informado a mantenimiento', 'En reparación', 'Reparado', 'No corresponde']
M_CERRADOS = ['Reparado', 'No corresponde']
M_LUGARES = ['Calle', 'Peatonal', 'Plaza', 'Espacio verde', 'Club / deportes', 'Perímetro', 'Otro']
M_FORMAS = {'punto': ('Punto', 1), 'linea': ('Línea', 2), 'area': ('Área', 3)}

NO_IMPORTA = {
    'Observaciones': 'la app todavía no tiene el módulo de observaciones',
    'Urgencias': 'la app todavía no tiene el módulo de urgencias',
    'Relevamientos': 'la app todavía no tiene el módulo de relevamientos',
    'Fotos': 'son links a Google Drive; las fotos no se descargan',
    'Faltas borradas': 'son faltas ya eliminadas',
    'Regularización': 'la app todavía no tiene el módulo de regularización',
    'Permisos de obra': 'la app todavía no tiene el módulo de permisos de obra',
    'Historial Regularización': 'la app todavía no tiene el módulo de regularización',
}

# calibración del plano (la misma de web/app.js): coordenada del plano → lat/lon
CAL = dict(lat0=-34.6, lon0=-58.86, kx=91631.5405, ky=110574, a=0.25210266, b=-0.31173198, tx=472.03627, ty=926.57710)


def a_geo(x, y):
    e, n = CAL['a'] * x + CAL['b'] * y, CAL['b'] * x - CAL['a'] * y
    return round((n + CAL['ty']) / CAL['ky'] + CAL['lat0'], 6), round((e + CAL['tx']) / CAL['kx'] + CAL['lon0'], 6)


class ErrorArchivo(Exception):
    pass


class FilaMala(ValueError):
    pass


def _norm(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode().lower()
    return ' '.join(''.join(ch if ch.isalnum() else ' ' for ch in s).split())


def _txt(v, largo=2000):
    if v is None:
        return ''
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()[:largo]


def _fecha(v, obligatoria=False, nombre='fecha'):
    if v in (None, ''):
        if obligatoria:
            raise FilaMala(f'falta la {nombre}')
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    s = str(v).strip()
    for f in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y'):
        try:
            return dt.datetime.strptime(s[:10], f).date()
        except ValueError:
            pass
    raise FilaMala(f'{nombre} «{s}» no válida')


def _entero(v, nombre='U.F.'):
    try:
        return int(float(str(v).split('/')[0].split(' y ')[0]))
    except (TypeError, ValueError):
        raise FilaMala(f'{nombre} «{_txt(v)}» no válida')


def _si(v):
    return _norm(v).startswith('si')


def _de_lista(v, opciones, defecto=None):
    """'A / B' o 'A; B' → la primera parte que coincida con una opción válida."""
    for parte in [_txt(v)] + re.split(r'\s*[/;]\s*', _txt(v)):
        for o in opciones:
            if _norm(o) == _norm(parte):
                return o
    return defecto


def _iso(v):
    return v.isoformat() if hasattr(v, 'isoformat') else v


def _num(n):
    m = re.fullmatch(r'([A-Z])-(\d{1,6})', _txt(n).upper())
    return (m.group(1), int(m.group(2))) if m else (None, None)


def _clave(*partes):
    return hashlib.sha256('base|'.join(str(p) for p in partes).encode()).hexdigest()


def leer(raw: bytes):
    """bytes del .xlsx → {hoja: [dict por fila]} con los encabezados tal cual."""
    if len(raw) > MAX_BYTES:
        raise ErrorArchivo('El archivo supera los 15 MB.')
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception:
        raise ErrorArchivo('No se pudo abrir el Excel. Guardalo como .xlsx y probá de nuevo.')
    hojas = {}
    for ws in wb.worksheets:
        it = ws.iter_rows(values_only=True)
        try:
            enc = [_txt(h) for h in next(it)]
        except StopIteration:
            continue
        datos = []
        for i, r in enumerate(it, start=2):
            if any(c not in (None, '') for c in r):
                d = {h: v for h, v in zip(enc, r) if h}
                d['_fila'] = i
                datos.append(d)
        hojas[ws.title] = datos
    wb.close()
    if not {'Visitas', 'Hallazgos'} <= set(hojas):
        raise ErrorArchivo('No es la planilla de Construcciones: faltan las hojas Visitas y Hallazgos.')
    return hojas


class _Ctx:
    def __init__(self, c, admin_id):
        self.c, self.uid = c, admin_id
        self.res, self.errores, self.avisos = {}, [], []

    def cuenta(self, hoja, k):
        r = self.res.setdefault(hoja, {'hoja': hoja, 'total': 0, 'nuevas': 0, 'actualizadas': 0, 'sin_cambios': 0, 'errores': 0})
        r[k] += 1

    def error(self, hoja, d, ref, motivo):
        self.cuenta(hoja, 'errores')
        if len(self.errores) < MAX_ERRORES:
            self.errores.append({'hoja': hoja, 'fila': d.get('_fila'), 'ref': ref, 'motivo': motivo[:200]})

    def aviso(self, hoja, d, ref, txt):
        if len(self.avisos) < MAX_ERRORES:
            self.avisos.append({'hoja': hoja, 'fila': d.get('_fila'), 'ref': ref, 'motivo': txt})

    def mapeado(self, hoja, n):
        r = fila(self.c, 'SELECT nro_registro FROM importacion_item WHERE clave=%s', (_clave(hoja, n),))
        return r['nro_registro'] if r else None

    def numero(self, prefijo, original, tabla, col):
        """Conserva el número original si está libre; si no, el siguiente de la secuencia."""
        p, _ = _num(original)
        if p == prefijo and not fila(self.c, f'SELECT 1 x FROM {tabla} WHERE {col}=%s', (original,)):
            return original
        return siguiente(self.c, prefijo)


def _subir_secuencias(x, hojas):
    for hoja, col, pref in (('Visitas', 'N° visita', 'V'), ('Hallazgos', 'N° hallazgo', 'F'), ('Marcas', 'N° marca', 'M')):
        mx = max((_num(d.get(col))[1] or 0 for d in hojas.get(hoja, []) if _num(d.get(col))[0] == pref), default=0)
        if mx:
            ejecutar(x.c, 'UPDATE secuencia SET ultimo = GREATEST(ultimo, %s) WHERE prefijo=%s', (mx, pref))


def _catalogo(x, hojas):
    rubros = {_norm(r['nombre']): r['id_rubro'] for r in filas(x.c, 'SELECT id_rubro, nombre FROM rubro')}
    for d in hojas.get('Catálogo', []):
        x.cuenta('Catálogo', 'total')
        cod = _txt(d.get('Código'), 10).upper()
        try:
            if not cod or not _txt(d.get('Falta')):
                raise FilaMala('falta el código o la descripción')
            if fila(x.c, 'SELECT 1 x FROM catalogo_falta WHERE codigo=%s', (cod,)):
                x.cuenta('Catálogo', 'sin_cambios')
                continue
            rub = _txt(d.get('Rubro'), 80) or 'Sin rubro'
            if _norm(rub) not in rubros:
                ejecutar(x.c, 'INSERT INTO rubro (nombre) VALUES (%s)', (rub,))
                rubros[_norm(rub)] = fila(x.c, 'SELECT LAST_INSERT_ID() id')['id']
            ejecutar(x.c, """INSERT INTO catalogo_falta (codigo, id_rubro, falta, que_observar, norma, articulo, penalidad,
                             visible_recorrido, activo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                     (cod, rubros[_norm(rub)], _txt(d.get('Falta'), 250), _txt(d.get('Qué observar')) or None,
                      _txt(d.get('Norma'), 150) or None, _txt(d.get('Artículo'), 40) or None, _txt(d.get('Penalidad'), 150) or None,
                      d.get('Visible en recorrido') is None or _si(d.get('Visible en recorrido')),
                      d.get('Activo') is None or _si(d.get('Activo'))))
            x.cuenta('Catálogo', 'nuevas')
        except FilaMala as e:
            x.error('Catálogo', d, cod, str(e))


def _ufs(x):
    return {r['nro_uf'] for r in filas(x.c, 'SELECT nro_uf FROM unidad_funcional')}


def _fechas_estimadas(hojas):
    """Algunas filas migradas del Registro V14 no tienen fecha. Se estima con el primer movimiento
    fechado del historial de sus faltas o, si no hay, con la fecha de revisión."""
    por_falta = {}
    for d in hojas.get('Historial', []):
        try:
            f = _fecha(d.get('Fecha'))
        except FilaMala:
            f = None
        n = _txt(d.get('N° hallazgo'), 10)
        if f and (n not in por_falta or f < por_falta[n]):
            por_falta[n] = f
    por_visita = {}
    for d in hojas.get('Hallazgos', []):
        n, v = _txt(d.get('N° hallazgo'), 10), _txt(d.get('N° visita'), 10)
        cand = []
        for k in ('Fecha', 'Fecha de revisión', 'Fecha de cierre'):
            try:
                if _fecha(d.get(k)):
                    cand.append(_fecha(d.get(k)))
            except FilaMala:
                pass
        if n in por_falta:
            cand.append(por_falta[n])
        if cand:
            por_visita[v] = min([por_visita[v]] + cand) if v in por_visita else min(cand)
    return por_visita


def _visitas(x, hojas, ufs):
    mapa = {}
    estimadas, anterior = _fechas_estimadas(hojas), None
    for d in hojas.get('Visitas', []):
        x.cuenta('Visitas', 'total')
        n = _txt(d.get('N° visita'), 10)
        try:
            if _num(n)[0] != 'V':
                raise FilaMala('número de visita no válido')
            ya = x.mapeado('V', n)
            if ya:
                mapa[n] = ya
                x.cuenta('Visitas', 'sin_cambios')
                continue
            fecha, obs = _fecha(d.get('Fecha')), _txt(d.get('Observación'))
            if not fecha:
                fecha, como = estimadas.get(n), 'por sus faltas'
                if not fecha:
                    fecha, como = anterior, 'igual a la visita anterior de la planilla'
                if not fecha:
                    raise FilaMala('falta la fecha y no se puede estimar')
                obs = (obs + ' · ' if obs else '') + 'Fecha estimada en la importación (la planilla no la tenía)'
                x.aviso('Visitas', d, n, f'sin fecha: se usó {fecha:%d/%m/%Y} ({como})')
            anterior = fecha
            uf = _entero(d.get('U.F.'))
            if uf not in ufs:
                raise FilaMala(f'la U.F. {uf} no existe')
            sn = _fecha(d.get('Sin novedad'), nombre='fecha de sin novedad')
            if sn:
                obs = (obs + ' · ' if obs else '') + f'Sin novedad el {sn:%d/%m/%Y}'
            nv = x.numero('V', n, 'visita', 'nro_visita')
            ejecutar(x.c, """INSERT INTO visita (nro_visita, fecha, nro_uf, origen, contacto, observacion, id_usuario)
                             VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                     (nv, fecha, uf, _de_lista(d.get('Origen'), ORIGENES, 'Recorrido de inspección'),
                      _de_lista(d.get('Contacto'), CONTACTOS), obs or None, x.uid))
            ejecutar(x.c, 'INSERT INTO importacion_item (clave, id_importacion, nro_origen, nro_registro) VALUES (%s,%s,%s,%s)',
                     (_clave('V', n), x.imp, n, nv))
            mapa[n] = nv
            x.cuenta('Visitas', 'nuevas')
        except FilaMala as e:
            x.error('Visitas', d, n, str(e))
    return mapa


def _hallazgos(x, hojas, vis, ufs):
    mapa, nuevos = {}, set()
    codigos = {r['codigo'] for r in filas(x.c, 'SELECT codigo FROM catalogo_falta')}
    for d in hojas.get('Hallazgos', []):
        x.cuenta('Hallazgos', 'total')
        n = _txt(d.get('N° hallazgo'), 10)
        try:
            if _num(n)[0] != 'F':
                raise FilaMala('número de falta no válido')
            nv = vis.get(_txt(d.get('N° visita'), 10))
            if not nv:
                raise FilaMala(f"la visita {_txt(d.get('N° visita')) or '(vacía)'} no está en la hoja Visitas o tiene error")
            fecha = _fecha(d.get('Fecha'))
            if not fecha:
                fecha = _fecha(fila(x.c, 'SELECT fecha FROM visita WHERE nro_visita=%s', (nv,))['fecha'])
                x.aviso('Hallazgos', d, n, f'sin fecha: se usó la de la visita ({fecha:%d/%m/%Y})')
            cod = _txt(d.get('Código'), 10).upper()
            if cod not in codigos:
                raise FilaMala(f'el código {cod or "(vacío)"} no está en Tipos de faltas ni en la hoja Catálogo')
            estado = _de_lista(d.get('Estado'), ESTADOS)
            if not estado:
                raise FilaMala(f"estado «{_txt(d.get('Estado'))}» no válido")
            cerr = estado in CERRADOS
            rev = _fecha(d.get('Fecha de revisión'), nombre='fecha de revisión')
            cierre = _fecha(d.get('Fecha de cierre'), nombre='fecha de cierre')
            v = dict(estado=estado, fecha_revision=None if cerr else rev,
                     fecha_cierre=(cierre or rev or fecha) if cerr else None,
                     observacion=_txt(d.get('Observación')) or None,
                     reiterancia=max(0, min(_entero(d.get('Reiterancia') or 0, 'reiterancia'), 999)),
                     foto_tomada=_si(d.get('Foto tomada')), derivado_comision=_si(d.get('Derivado a Comisión')))
            ya = x.mapeado('F', n)
            if ya:
                h = fila(x.c, 'SELECT * FROM hallazgo WHERE nro_hallazgo=%s FOR UPDATE', (ya,))
                mapa[n] = ya
                if not h:            # se borró en esta base después de importarla: no se recrea
                    x.cuenta('Hallazgos', 'sin_cambios')
                    continue
                actual = lambda k: bool(h[k]) if k in ('foto_tomada', 'derivado_comision') else _iso(h[k])
                dif = {k: val for k, val in v.items() if actual(k) != _iso(val)}
                if dif:
                    ejecutar(x.c, f"UPDATE hallazgo SET {', '.join(k + '=%s' for k in dif)} WHERE nro_hallazgo=%s", list(dif.values()) + [ya])
                    x.cuenta('Hallazgos', 'actualizadas')
                else:
                    x.cuenta('Hallazgos', 'sin_cambios')
                continue
            uf_v = fila(x.c, 'SELECT nro_uf FROM visita WHERE nro_visita=%s', (nv,))['nro_uf']
            if d.get('U.F.') not in (None, '') and _entero(d.get('U.F.')) != uf_v:
                raise FilaMala(f"la U.F. {_entero(d.get('U.F.'))} no coincide con la de la visita ({uf_v})")
            nf = x.numero('F', n, 'registro', 'nro_registro')
            ejecutar(x.c, "INSERT INTO registro (nro_registro, tipo) VALUES (%s,'F')", (nf,))
            ejecutar(x.c, """INSERT INTO hallazgo (nro_hallazgo, nro_visita, codigo, fecha, estado, fecha_revision, foto_tomada,
                             derivado_comision, observacion, reiterancia, fecha_cierre, id_usuario)
                             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                     (nf, nv, cod, fecha, v['estado'], v['fecha_revision'], v['foto_tomada'], v['derivado_comision'],
                      v['observacion'], v['reiterancia'], v['fecha_cierre'], x.uid))
            ejecutar(x.c, 'INSERT INTO importacion_item (clave, id_importacion, nro_origen, nro_registro) VALUES (%s,%s,%s,%s)',
                     (_clave('F', n), x.imp, n, nf))
            mapa[n] = nf
            nuevos.add(nf)
            x.cuenta('Hallazgos', 'nuevas')
        except FilaMala as e:
            x.error('Hallazgos', d, n, str(e))
    return mapa, nuevos


def _marcas(x, hojas):
    mapa, nuevos = {}, set()
    sectores = {_norm(r['nombre']): r['id_sector'] for r in filas(x.c, 'SELECT id_sector, nombre FROM sector')}
    for d in hojas.get('Marcas', []):
        x.cuenta('Marcas', 'total')
        n = _txt(d.get('N° marca'), 10)
        try:
            if _num(n)[0] != 'M':
                raise FilaMala('número de marca no válido')
            forma = M_FORMAS.get(_norm(d.get('Forma')))
            if not forma:
                raise FilaMala(f"forma «{_txt(d.get('Forma'))}» no válida")
            try:
                pts = [[round(float(a), 1), round(float(b), 1)] for a, b in json.loads(_txt(d.get('Geometría'), 100000))]
            except (ValueError, TypeError):
                raise FilaMala('la geometría no se puede leer')
            if len(pts) < forma[1] or any(not (-500 <= a <= 4500 and -500 <= b <= 4000) for a, b in pts):
                raise FilaMala('la geometría no tiene puntos suficientes dentro del plano')
            estado = _de_lista(d.get('Estado'), M_ESTADOS, 'Relevado')
            cerr = estado in M_CERRADOS
            fecha = _fecha(d.get('Fecha'), True)
            rev = _fecha(d.get('Fecha de revisión'), nombre='fecha de revisión')
            cierre = _fecha(d.get('Fecha de cierre'), nombre='fecha de cierre')
            tipo = _txt(d.get('Tipo'), 60) or _txt(d.get('Falta'), 60) or 'Otro'
            falta, obs = _txt(d.get('Falta'), 500), _txt(d.get('Observación'), 500)
            desc = obs or falta or tipo
            extra = falta if falta and _norm(falta) not in (_norm(tipo), _norm(desc)) else None
            v = dict(estado=estado, fecha_revision=None if cerr else rev, fecha_cierre=(cierre or rev or fecha) if cerr else None,
                     descripcion=desc)
            ya = x.mapeado('M', n)
            if ya:
                m = fila(x.c, 'SELECT * FROM marca WHERE nro_marca=%s FOR UPDATE', (ya,))
                mapa[n] = ya
                dif = {k: val for k, val in v.items() if m and _iso(m[k]) != _iso(val)}
                if dif:
                    ejecutar(x.c, f"UPDATE marca SET {', '.join(k + '=%s' for k in dif)} WHERE nro_marca=%s", list(dif.values()) + [ya])
                    x.cuenta('Marcas', 'actualizadas')
                else:
                    x.cuenta('Marcas', 'sin_cambios')
                continue
            cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
            lat, lon = a_geo(cx, cy)
            nm = x.numero('M', n, 'registro', 'nro_registro')
            ejecutar(x.c, "INSERT INTO registro (nro_registro, tipo) VALUES (%s,'M')", (nm,))
            ejecutar(x.c, """INSERT INTO marca (nro_marca, fecha, tipo, descripcion, forma, geometria, lugar, id_sector, estado,
                             fecha_revision, observacion, fecha_cierre, lat, lon, ubicacion, id_usuario)
                             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Plano',%s)""",
                     (nm, fecha, tipo, desc, forma[0], json.dumps(pts), _de_lista(d.get('Lugar'), M_LUGARES, 'Otro'),
                      sectores.get(_norm(d.get('Sector'))), estado, v['fecha_revision'], extra, v['fecha_cierre'], lat, lon, x.uid))
            ejecutar(x.c, 'INSERT INTO importacion_item (clave, id_importacion, nro_origen, nro_registro) VALUES (%s,%s,%s,%s)',
                     (_clave('M', n), x.imp, n, nm))
            mapa[n] = nm
            nuevos.add(nm)
            x.cuenta('Marcas', 'nuevas')
        except FilaMala as e:
            x.error('Marcas', d, n, str(e))
    return mapa, nuevos


def _historial(x, hojas, faltas, marcas, vis):
    """Historial de faltas y marcas. Cada movimiento entra una sola vez (clave por contenido y orden)."""
    vistos, con_hist, omit = {}, set(), 0
    for d in hojas.get('Historial', []):
        n = _txt(d.get('N° hallazgo'), 10)
        pref = _num(n)[0]
        if pref not in ('F', 'M'):
            omit += 1           # O- y R-: módulos que la app todavía no tiene
            continue
        x.cuenta('Historial', 'total')
        try:
            reg = (faltas if pref == 'F' else marcas).get(n)
            if not reg:
                raise FilaMala(f'{n} no se importó (no está en su hoja o tiene error)')
            fecha = _fecha(d.get('Fecha'))
            if not fecha:
                r = fila(x.c, 'SELECT fecha FROM hallazgo WHERE nro_hallazgo=%s UNION ALL SELECT fecha FROM marca WHERE nro_marca=%s', (reg, reg))
                fecha = _fecha(r['fecha'])
            cambio, nota = _txt(d.get('Cambio'), 500), _txt(d.get('Nota'))
            if not cambio:
                raise FilaMala('el cambio está vacío')
            base = (n, _iso(_fecha(d.get('Fecha'))) or '', cambio, nota)
            k = vistos[base] = vistos.get(base, 0) + 1
            clave = _clave('H', *base, k)
            con_hist.add(reg)
            if fila(x.c, 'SELECT 1 x FROM importacion_item WHERE clave=%s', (clave,)):
                x.cuenta('Historial', 'sin_cambios')
                continue
            if reg != n:
                cambio = (cambio + f' (era {n})')[:500]
            creado = d.get('Fecha') if isinstance(d.get('Fecha'), dt.datetime) else dt.datetime.combine(fecha, dt.time(12))
            ejecutar(x.c, """INSERT INTO historial (nro_registro, nro_visita, fecha, cambio, nota, id_usuario, creado)
                             VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                     (reg, vis.get(_txt(d.get('N° visita'), 10)), fecha, cambio, nota or None, x.uid, creado))
            ejecutar(x.c, 'INSERT INTO importacion_item (clave, id_importacion, nro_origen, nro_registro) VALUES (%s,%s,%s,%s)',
                     (clave, x.imp, n, reg))
            x.cuenta('Historial', 'nuevas')
        except FilaMala as e:
            x.error('Historial', d, n, str(e))
    return con_hist, omit


def procesar(c, hojas, archivo, admin_id):
    x = _Ctx(c, admin_id)
    ejecutar(c, "INSERT INTO importacion (archivo, filas, creadas, omitidas, errores, id_usuario) VALUES (%s,0,0,0,0,%s)",
             (archivo[:120], admin_id))
    x.imp = fila(c, 'SELECT LAST_INSERT_ID() id')['id']
    _subir_secuencias(x, hojas)
    _catalogo(x, hojas)
    ufs = _ufs(x)
    vis = _visitas(x, hojas, ufs)
    faltas, f_nuevas = _hallazgos(x, hojas, vis, ufs)
    marcas, m_nuevas = _marcas(x, hojas)
    con_hist, omit_hist = _historial(x, hojas, faltas, marcas, vis)
    # las faltas y marcas nuevas sin ningún movimiento en la planilla reciben su alta
    origen = {v: k for k, v in list(faltas.items()) + list(marcas.items())}
    for reg in sorted((f_nuevas | m_nuevas) - con_hist):
        r = fila(c, """SELECT h.fecha, h.estado, h.nro_visita FROM hallazgo h WHERE h.nro_hallazgo=%s
                       UNION ALL SELECT m.fecha, m.estado, NULL FROM marca m WHERE m.nro_marca=%s""", (reg, reg))
        era = f' (era {origen[reg]})' if origen.get(reg, reg) != reg else ''
        ejecutar(c, 'INSERT INTO historial (nro_registro, nro_visita, fecha, cambio, id_usuario) VALUES (%s,%s,%s,%s,%s)',
                 (reg, r['nro_visita'], r['fecha'], f"Alta por importación de la planilla{era}. Estado: {r['estado']}", admin_id))
    no = [{'hoja': h, 'filas': len(hojas[h]), 'motivo': m} for h, m in NO_IMPORTA.items() if hojas.get(h)]
    if omit_hist:
        no.append({'hoja': 'Historial', 'filas': omit_hist, 'motivo': 'movimientos de observaciones y relevamientos (módulos que la app todavía no tiene)'})
    orden = ['Catálogo', 'Visitas', 'Hallazgos', 'Marcas', 'Historial']
    res = [x.res[h] for h in orden if h in x.res]
    tot = {k: sum(r[k] for r in res) for k in ('total', 'nuevas', 'actualizadas', 'sin_cambios', 'errores')}
    ejecutar(c, 'UPDATE importacion SET filas=%s, creadas=%s, omitidas=%s, errores=%s WHERE id_importacion=%s',
             (tot['total'], tot['nuevas'], tot['actualizadas'] + tot['sin_cambios'], tot['errores'], x.imp))
    return {'tipo': 'base', 'archivo': archivo, 'hojas': res, 'totales': tot, 'errores': x.errores, 'avisos': x.avisos, 'no_importa': no,
            'importacion': x.imp, 'hay_cambios': bool(tot['nuevas'] or tot['actualizadas'])}
