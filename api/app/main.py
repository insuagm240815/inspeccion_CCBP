"""API de la Base de Inspección CCBP."""
import asyncio
import re
import datetime as dt
import json
import os
import threading

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse

from . import arranque
from . import fotos as F
from . import importar as IMP
from . import importar_base as IMPB
from . import ruteo as RUT
from . import ficha_pdf as FICHA
from .db import conexion, ejecutar, fila, filas, hoy, siguiente
from .seguridad import COOKIE, COOKIE_SECURE, PH, SESION_HORAS, _sha, exigir, hash_clave, ip_de, login, logout, usuario_de

app = FastAPI(title="Inspección CCBP", docs_url=None, redoc_url=None, openapi_url=None)


@app.on_event("startup")
def _al_arrancar():
    arranque.iniciar()

ESTADOS = ['Pendiente', 'Aviso verbal', 'Aviso por folleto', 'Derivado a Comisión',
           'Notificado/Intimado', 'En proceso de resolución', 'Resuelto', 'Verificado sin falta']
CERRADOS = ['Resuelto', 'Verificado sin falta']
ESTADOS_GESTION = ['Notificado/Intimado', 'En proceso de resolución']   # lo que puede marcar el usuario de consulta
ORIGENES = ['Recorrido de inspección', 'Reclamo de vecino', 'Reclamo del servicio de recolección', 'Revisión de caso']
CONTACTOS = ['Hablé con el residente', 'No había nadie', 'No había nadie, dejé aviso escrito',
             'Hablé con personal de poda, pasto, obra o limpieza', 'Pendiente de visita']

# ───────── versión de datos para el aviso en vivo ─────────
_version = 0
_vlock = threading.Lock()


def cambio():
    global _version
    with _vlock:
        _version += 1


# ───────── utilidades ─────────
def _fecha(s, nombre, permitir_vacia=False):
    if not s:
        if permitir_vacia:
            return None
        raise HTTPException(400, f"Falta la {nombre}.")
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        raise HTTPException(400, f"La {nombre} no es válida.")


def _texto(s, largo=2000):
    return (str(s).strip() if s is not None else "")[:largo]


def _coord(v, lo, hi):
    try:
        x = float(v)
        return x if lo <= x <= hi else None
    except (TypeError, ValueError):
        return None


async def _form(req: Request):
    """Lee multipart: campo 'datos' (JSON) y archivos en campos 'f_<grupo>'. Devuelve (datos, {grupo: [jpeg,...]})."""
    form = await req.form()
    try:
        datos = json.loads(form.get("datos") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "Datos mal formados.")
    grupos, total = {}, 0
    for k, v in form.multi_items():
        if k.startswith("f_") and hasattr(v, "read"):
            total += 1
            if total > F.MAX_POR_ENVIO:
                raise HTTPException(413, f"Máximo {F.MAX_POR_ENVIO} fotos por envío.")
            raw = await v.read()
            grupos.setdefault(k[2:], []).append(await run_in_threadpool(F.procesar, raw))
    return datos, grupos


def _insertar_fotos(c, jpegs, reg, visita, fecha, momento, uid, escritos):
    for j in jpegs:
        n = siguiente(c, "P")
        rel = F.guardar(n, fecha.isoformat(), j)
        escritos.append(rel)
        ejecutar(c, """INSERT INTO foto (nro_foto,nro_registro,nro_visita,fecha,momento,archivo,bytes,id_usuario)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", (n, reg, visita, fecha, momento, rel, len(j), uid))


def _hist(c, reg, visita, cambio_txt, nota, uid):
    ejecutar(c, "INSERT INTO historial (nro_registro,nro_visita,fecha,cambio,nota,id_usuario) VALUES (%s,%s,%s,%s,%s,%s)",
             (reg, visita, hoy(), cambio_txt[:500], _texto(nota), uid))


def _con_fotos(fn):
    """Si la transacción falla, se borran los archivos de foto que ya se habían escrito."""
    escritos = []
    try:
        return fn(escritos)
    except Exception:
        for rel in escritos:
            F.borrar(rel)
        raise


# ───────── sesión ─────────
@app.post("/api/login")
async def api_login(req: Request, resp: Response):
    if req.headers.get("x-ccbp") != "1":
        raise HTTPException(403, "Solicitud no permitida.")
    b = await req.json()
    token = await run_in_threadpool(login, b.get("usuario"), b.get("clave"), ip_de(req))
    resp.set_cookie(COOKIE, token, max_age=SESION_HORAS * 3600, httponly=True, secure=COOKIE_SECURE,
                    samesite="strict", path="/")
    return {"ok": True}


@app.post("/api/logout")
def api_logout(req: Request, resp: Response):
    logout(req.cookies.get(COOKIE))
    resp.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/api/yo")
def api_yo(req: Request):
    u = usuario_de(req)
    return {"id": u["id_usuario"], "usuario": u["usuario"], "nombre": u["nombre"], "rol": u["rol"]}


@app.get("/api/salud")
def salud():
    with conexion() as c:
        fila(c, "SELECT 1 AS ok")
    return {"ok": True}


# ───────── lectura ─────────
@app.get("/api/estado")
def api_estado(req: Request):
    exigir(req, "consulta")
    with conexion() as c:
        out = {
            "version": _version,
            "hoy": hoy().isoformat(),
            "visitas": filas(c, """SELECT nro_visita n, fecha, nro_uf uf, origen, contacto, observacion obs,
                                   lat, lon, precision_m prec, id_usuario autor FROM visita"""),
            "hallazgos": filas(c, """SELECT h.nro_hallazgo n, h.nro_visita visita, h.fecha, v.nro_uf uf, h.codigo, h.estado,
                                     h.fecha_revision revision, h.foto_tomada fotoTomada, h.observacion obs,
                                     h.reiterancia reit, h.fecha_cierre cierre, h.id_usuario autor
                                     FROM hallazgo h JOIN visita v ON v.nro_visita = h.nro_visita"""),
            "historial": filas(c, """SELECT x.id_historial id, x.nro_registro reg, x.nro_visita visita, x.fecha, x.cambio,
                                     x.nota, x.id_usuario autor, x.creado ts, v.nro_uf uf
                                     FROM historial x LEFT JOIN hallazgo h ON h.nro_hallazgo = x.nro_registro
                                     LEFT JOIN visita v ON v.nro_visita = h.nro_visita ORDER BY x.id_historial"""),
            "fotos": filas(c, "SELECT nro_foto n, nro_registro reg, nro_visita visita, fecha, momento FROM foto"),
            "catalogo": filas(c, """SELECT c.codigo, r.nombre rubro, c.falta, c.que_observar, c.norma, c.articulo, c.penalidad,
                                    c.visible_recorrido visible, c.activo,
                                    (SELECT COUNT(*) FROM hallazgo h WHERE h.codigo = c.codigo) usos
                                    FROM catalogo_falta c JOIN rubro r ON r.id_rubro = c.id_rubro"""),
            "usuarios": filas(c, "SELECT id_usuario id, nombre FROM usuario"),
            "pendientes_visita": _pendientes_visita(c),
            "marcas": filas(c, """SELECT m.nro_marca n, m.fecha, m.tipo, m.descripcion, m.forma, m.geometria geo, m.lugar,
                                  s.nombre sector, m.estado, m.fecha_revision revision, m.fecha_cierre cierre, m.observacion obs,
                                  m.lat, m.lon, m.precision_m prec, m.ubicacion ubic, m.id_usuario autor FROM marca m LEFT JOIN sector s ON s.id_sector = m.id_sector"""),
            "grupos": filas(c, """SELECT a.nro_uf uf, GROUP_CONCAT(DISTINCT b.nro_uf) ufs FROM uf_pilar a
                                  JOIN uf_pilar b ON b.nro_pilar = a.nro_pilar GROUP BY a.nro_uf
                                  HAVING COUNT(DISTINCT b.nro_uf) > 1"""),
        }
    for m in out["marcas"]:
        m["geo"] = json.loads(m["geo"]) if isinstance(m["geo"], str) else m["geo"]
    return out


@app.get("/api/fotos/{nro}")
def api_foto(nro: str, req: Request):
    exigir(req, "consulta")
    with conexion() as c:
        f = fila(c, "SELECT archivo FROM foto WHERE nro_foto=%s", (nro[:10],))
    if not f:
        raise HTTPException(404, "No existe esa foto.")
    return FileResponse(F.ruta(f["archivo"]), media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/faltas/{n}/pdf")
def api_falta_pdf(n: str, req: Request):
    """Ficha de la falta en PDF, con las fotos adjuntas."""
    exigir(req, "consulta")
    with conexion() as c:
        h = FICHA.datos(c, n[:10])
    if not h:
        raise HTTPException(404, f"No encontré la falta {n}.")
    host = req.headers.get("x-forwarded-host") or req.headers.get("host") or "localhost"
    esquema = "http" if host.split(":")[0] in ("localhost", "127.0.0.1") else "https"
    pdf = FICHA.generar(h, f"{esquema}://{host}")
    nombre = f"Falta {h['nro_hallazgo']} UF {h['uf']}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"', "Cache-Control": "no-store"})


@app.get("/api/eventos")
async def api_eventos(req: Request):
    """Server-Sent Events: avisa a cada navegador cuando cambian los datos, para que recargue."""
    await run_in_threadpool(exigir, req, "consulta")

    async def flujo():
        visto, quieto = -1, 0
        while not await req.is_disconnected():
            if _version != visto:
                visto = _version
                yield f"data: {visto}\n\n"
                quieto = 0
            elif quieto >= 20:
                yield ": ping\n\n"
                quieto = 0
            await asyncio.sleep(1)
            quieto += 1

    return StreamingResponse(flujo(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# ───────── visitas ─────────
@app.post("/api/visitas")
async def api_visita(req: Request):
    u = await run_in_threadpool(exigir, req, "inspector", True)
    d, fotos = await _form(req)

    def tx(escritos):
        uf = int(d.get("uf") or 0)
        fecha = _fecha(d.get("fecha"), "fecha de la visita")
        if fecha > hoy():
            raise HTTPException(400, "La fecha de la visita no puede ser futura.")
        origen = d.get("origen") if d.get("origen") in ORIGENES else ORIGENES[0]
        contacto = d.get("contacto") if d.get("contacto") in CONTACTOS else None
        lat, lon = _coord(d.get("lat"), -35.5, -33.5), _coord(d.get("lon"), -59.8, -57.8)
        prec = int(d["prec"]) if lat is not None and lon is not None and str(d.get("prec", "")).isdigit() else None
        faltas = d.get("faltas") or []
        if len(faltas) > 20:
            raise HTTPException(400, "Demasiadas faltas en una sola visita.")
        with conexion() as c:
            if not fila(c, "SELECT 1 x FROM unidad_funcional WHERE nro_uf=%s", (uf,)):
                raise HTTPException(400, "La U.F. no existe.")
            nv = siguiente(c, "V")
            ejecutar(c, """INSERT INTO visita (nro_visita,fecha,nro_uf,origen,contacto,observacion,lat,lon,precision_m,id_usuario)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                     (nv, fecha, uf, origen, contacto, _texto(d.get("obs")), lat if lon is not None else None,
                      lon if lat is not None else None, prec, u["id_usuario"]))
            _insertar_fotos(c, fotos.get("visita", []), None, nv, fecha, "Visita", u["id_usuario"], escritos)
            creadas = []
            for i, fa in enumerate(faltas):
                cat = fila(c, "SELECT codigo FROM catalogo_falta WHERE codigo=%s AND activo", (str(fa.get("codigo"))[:10],))
                if not cat:
                    raise HTTPException(400, f"El código {fa.get('codigo')} no existe o está dado de baja.")
                estado = fa.get("estado") if fa.get("estado") in ESTADOS else "Pendiente"
                cerr = estado in CERRADOS
                rev = None if cerr else _fecha(fa.get("revision"), "fecha de revisión", True)
                reit = fila(c, """SELECT COUNT(DISTINCT h.nro_hallazgo) n FROM hallazgo h
                                  JOIN visita v ON v.nro_visita = h.nro_visita
                                  JOIN uf_pilar a ON a.nro_uf = v.nro_uf
                                  WHERE h.codigo=%s AND a.nro_pilar IN (SELECT nro_pilar FROM uf_pilar WHERE nro_uf=%s)""",
                            (cat["codigo"], uf))["n"]
                nf = siguiente(c, "F")
                ejecutar(c, "INSERT INTO registro (nro_registro,tipo) VALUES (%s,'F')", (nf,))
                jp = fotos.get(str(i), [])
                ejecutar(c, """INSERT INTO hallazgo (nro_hallazgo,nro_visita,codigo,fecha,estado,fecha_revision,foto_tomada,
                               derivado_comision,observacion,reiterancia,fecha_cierre,id_usuario)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                         (nf, nv, cat["codigo"], fecha, estado, rev, bool(jp),
                          estado in ('Derivado a Comisión', 'Notificado/Intimado'), _texto(fa.get("obs")), reit,
                          fecha if cerr else None, u["id_usuario"]))
                _hist(c, nf, nv, "Alta. Estado: " + estado, "", u["id_usuario"])
                _insertar_fotos(c, jp, nf, nv, fecha, "Antes", u["id_usuario"], escritos)
                creadas.append(nf)
        return {"ok": True, "visita": nv, "faltas": creadas}

    r = await run_in_threadpool(_con_fotos, tx)
    cambio()
    return r


# ───────── faltas ─────────
def _falta(c, n):
    h = fila(c, """SELECT h.*, v.nro_uf FROM hallazgo h JOIN visita v ON v.nro_visita = h.nro_visita
                   WHERE h.nro_hallazgo=%s FOR UPDATE""", (n[:10],))
    if not h:
        raise HTTPException(404, f"No encontré la falta {n}.")
    return h


@app.post("/api/faltas/{n}/estado")
async def api_estado_falta(n: str, req: Request):
    u = await run_in_threadpool(exigir, req, "consulta", True)
    gestion = u["rol"] == "consulta"          # gestión administrativa: sin visita a campo ni fotos
    d, fotos = await _form(req)

    def tx(escritos):
        estado = d.get("estado")
        if estado not in ESTADOS:
            raise HTTPException(400, "Estado no válido.")
        if gestion and estado not in ESTADOS_GESTION:
            raise HTTPException(403, "Tu usuario solo puede marcar la falta como notificada o en proceso de resolución.")
        if gestion and fotos:
            raise HTTPException(403, "Tu usuario no puede subir fotos.")
        t = hoy()
        with conexion() as c:
            h = _falta(c, n)
            if gestion and h["estado"] in CERRADOS:
                raise HTTPException(403, "La falta está cerrada; solo un inspector puede reabrirla.")
            cerr = estado in CERRADOS
            nv = None
            if not gestion:
                v = fila(c, "SELECT nro_visita FROM visita WHERE nro_uf=%s AND fecha=%s ORDER BY nro_visita DESC LIMIT 1",
                         (h["nro_uf"], t))
                nv = v["nro_visita"] if v else None
            if not nv and not gestion:
                nv = siguiente(c, "V")
                lat, lon = _coord(d.get("lat"), -35.5, -33.5), _coord(d.get("lon"), -59.8, -57.8)
                ejecutar(c, """INSERT INTO visita (nro_visita,fecha,nro_uf,origen,contacto,observacion,lat,lon,precision_m,id_usuario)
                               VALUES (%s,%s,%s,'Revisión de caso',%s,'',%s,%s,%s,%s)""",
                         (nv, t, h["nro_uf"], 'No había nadie, dejé aviso escrito' if estado == 'Aviso por folleto' else None,
                          lat if lon is not None else None, lon if lat is not None else None,
                          int(d["prec"]) if lat is not None and str(d.get("prec", "")).isdigit() else None, u["id_usuario"]))
            rev = None if cerr else (_fecha(d.get("revision"), "fecha de revisión", True) or h["fecha_revision"])
            jp = fotos.get("estado", [])
            ejecutar(c, """UPDATE hallazgo SET estado=%s, fecha_cierre=%s, fecha_revision=%s,
                           derivado_comision = derivado_comision OR %s, foto_tomada = foto_tomada OR %s
                           WHERE nro_hallazgo=%s""",
                     (estado, t if cerr else None, rev, estado in ('Derivado a Comisión', 'Notificado/Intimado'), bool(jp), h["nro_hallazgo"]))
            _hist(c, h["nro_hallazgo"], nv, f"{h['estado']} → {estado}", d.get("nota"), u["id_usuario"])
            _insertar_fotos(c, jp, h["nro_hallazgo"], nv, t, "Después" if cerr else "Seguimiento", u["id_usuario"], escritos)
        return {"ok": True}

    r = await run_in_threadpool(_con_fotos, tx)
    cambio()
    return r


@app.post("/api/faltas/{n}/reprogramar")
async def api_reprogramar(n: str, req: Request):
    u = await run_in_threadpool(exigir, req, "inspector", True)
    d = await req.json()

    def tx():
        nueva = _fecha(d.get("fecha"), "nueva fecha")
        if nueva < hoy():
            raise HTTPException(400, "La nueva fecha no puede ser anterior a hoy.")
        with conexion() as c:
            h = _falta(c, n)
            if h["estado"] in CERRADOS:
                raise HTTPException(400, "La falta está cerrada.")
            antes = h["fecha_revision"]
            ejecutar(c, "UPDATE hallazgo SET fecha_revision=%s WHERE nro_hallazgo=%s", (nueva, h["nro_hallazgo"]))
            fmt = lambda x: dt.date.fromisoformat(str(x)).strftime("%d/%m/%Y") if x else "sin fecha"
            _hist(c, h["nro_hallazgo"], None, f"Revisión reprogramada: {fmt(antes)} → {fmt(nueva)}", d.get("nota"), u["id_usuario"])
        return {"ok": True}

    r = await run_in_threadpool(tx)
    cambio()
    return r


@app.post("/api/faltas/{n}/borrar")
async def api_borrar(n: str, req: Request):
    u = await run_in_threadpool(exigir, req, "supervisor", True)
    d = await req.json()
    motivo = _texto(d.get("motivo"))
    if len(motivo) < 5:
        raise HTTPException(400, "Escribí el motivo del borrado.")

    def tx():
        with conexion() as c:
            h = _falta(c, n)
            cat = fila(c, "SELECT falta FROM catalogo_falta WHERE codigo=%s", (h["codigo"],))
            fs = filas(c, "SELECT archivo FROM foto WHERE nro_registro=%s", (h["nro_hallazgo"],))
            ejecutar(c, """INSERT INTO registro_borrado (nro_registro,nro_uf,descripcion,estado,fecha,observacion,motivo,
                           fotos_eliminadas,id_usuario) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                     (h["nro_hallazgo"], h["nro_uf"], f"{h['codigo']} {cat['falta'] if cat else ''}"[:300], h["estado"],
                      h["fecha"], h["observacion"], motivo, len(fs), u["id_usuario"]))
            ejecutar(c, "DELETE FROM registro WHERE nro_registro=%s", (h["nro_hallazgo"],))   # cascada: falta, historial, fotos
        for f in fs:
            F.a_papelera(f["archivo"])
        return {"ok": True}

    r = await run_in_threadpool(tx)
    cambio()
    return r


# ───────── Novedades en espacios comunes (marcas en el plano) ─────────
M_ESTADOS = ['Relevado', 'Informado a mantenimiento', 'En reparación', 'Reparado', 'No corresponde']
M_CERRADOS = ['Reparado', 'No corresponde']
M_GESTION = ['Informado a mantenimiento', 'En reparación']          # lo que puede marcar el usuario de consulta
M_LUGARES = ['Calle', 'Peatonal', 'Plaza', 'Espacio verde', 'Club / deportes', 'Perímetro', 'Otro']
M_FORMAS = {'P': ('Punto', 1, 1), 'L': ('Línea', 2, 400), 'A': ('Área', 3, 400)}
SECTORES = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'Golf': 6}


def _geo(d):
    forma = M_FORMAS.get(d.get("forma"))
    if not forma:
        raise HTTPException(400, "Forma no válida.")
    try:
        pts = [[round(float(x), 1), round(float(y), 1)] for x, y in (d.get("geo") or [])]
    except (TypeError, ValueError):
        raise HTTPException(400, "El dibujo no es válido.")
    if not (forma[1] <= len(pts) <= forma[2]) or any(not (-500 <= x <= 4500 and -500 <= y <= 4000) for x, y in pts):
        raise HTTPException(400, f"Un/a {forma[0].lower()} necesita al menos {forma[1]} punto(s) dentro del plano.")
    return forma[0], json.dumps(pts)


def _ubic(d):
    """Coordenadas de la novedad (centro del dibujo) y cómo se ubicó: con el GPS del celular o a mano en el plano."""
    lat, lon = _coord(d.get("lat"), -35.5, -33.5), _coord(d.get("lon"), -59.8, -57.8)
    if lat is None or lon is None:
        return None, None, None, "Plano"
    gps = d.get("ubicacion") == "GPS"
    try:
        prec = min(max(int(float(d.get("prec"))), 0), 65000) if gps and d.get("prec") not in (None, "") else None
    except (TypeError, ValueError):
        prec = None
    return lat, lon, prec, "GPS" if gps else "Plano"


def _marca(c, n):
    m = fila(c, "SELECT * FROM marca WHERE nro_marca=%s FOR UPDATE", (n[:10],))
    if not m:
        raise HTTPException(404, f"No encontré la novedad {n}.")
    return m


@app.post("/api/marcas")
async def api_marca_alta(req: Request):
    u = await run_in_threadpool(exigir, req, "inspector", True)
    d, fotos = await _form(req)

    def tx(escritos):
        forma, geo = _geo(d)
        tipo, desc = _texto(d.get("tipo"), 60), _texto(d.get("descripcion"), 500)
        if not tipo or not desc:
            raise HTTPException(400, "Elegí el tipo de novedad y describila.")
        lugar = d.get("lugar") if d.get("lugar") in M_LUGARES else "Otro"
        estado = d.get("estado") if d.get("estado") in M_ESTADOS else "Relevado"
        cerr, t = estado in M_CERRADOS, hoy()
        lat, lon, prec, ubic = _ubic(d)
        with conexion() as c:
            n = siguiente(c, "M")
            ejecutar(c, "INSERT INTO registro (nro_registro,tipo) VALUES (%s,'M')", (n,))
            ejecutar(c, """INSERT INTO marca (nro_marca,fecha,tipo,descripcion,forma,geometria,lugar,id_sector,estado,fecha_revision,
                           observacion,fecha_cierre,lat,lon,precision_m,ubicacion,id_usuario) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                     (n, t, tipo, desc, forma, geo, lugar, SECTORES.get(d.get("sector")), estado,
                      None if cerr else _fecha(d.get("revision"), "fecha de revisión", True), _texto(d.get("obs")),
                      t if cerr else None, lat, lon, prec, ubic, u["id_usuario"]))
            _hist(c, n, None, f"Alta en {lugar.lower()} ({forma.lower()}). Estado: {estado}", "", u["id_usuario"])
            _insertar_fotos(c, fotos.get("marca", []), n, None, t, "Antes", u["id_usuario"], escritos)
        return {"ok": True, "n": n}

    r = await run_in_threadpool(_con_fotos, tx)
    cambio()
    return r


@app.put("/api/marcas/{n}")
async def api_marca_modif(n: str, req: Request):
    u = await run_in_threadpool(exigir, req, "inspector", True)
    d = await req.json()

    def tx():
        with conexion() as c:
            m = _marca(c, n)
            cambios, sets, args = [], [], []
            for campo, largo, etiqueta in (("tipo", 60, "tipo"), ("descripcion", 500, "descripción"), ("observacion", 2000, "observación")):
                if d.get(campo) is not None and _texto(d[campo], largo) != (m[campo] or ""):
                    if campo != "observacion" and not _texto(d[campo], largo):
                        raise HTTPException(400, f"El campo {etiqueta} no puede quedar vacío.")
                    sets.append(f"{campo}=%s"); args.append(_texto(d[campo], largo)); cambios.append(etiqueta)
            if d.get("lugar") in M_LUGARES and d["lugar"] != m["lugar"]:
                sets.append("lugar=%s"); args.append(d["lugar"]); cambios.append("lugar: " + d["lugar"])
            if d.get("geo") is not None:
                forma, geo = _geo(d)
                lat, lon, prec, ubic = _ubic(d)
                sets += ["forma=%s", "geometria=%s", "id_sector=%s", "lat=%s", "lon=%s", "precision_m=%s", "ubicacion=%s"]
                args += [forma, geo, SECTORES.get(d.get("sector"), m["id_sector"]), lat, lon, prec, ubic]
                cambios.append("dibujo")
            if sets:
                ejecutar(c, f"UPDATE marca SET {', '.join(sets)} WHERE nro_marca=%s", args + [m["nro_marca"]])
                _hist(c, m["nro_marca"], None, "Editada: " + ", ".join(cambios), d.get("nota"), u["id_usuario"])
        return {"ok": True}

    r = await run_in_threadpool(tx)
    cambio()
    return r


@app.post("/api/marcas/{n}/estado")
async def api_marca_estado(n: str, req: Request):
    u = await run_in_threadpool(exigir, req, "consulta", True)
    gestion = u["rol"] == "consulta"
    d, fotos = await _form(req)

    def tx(escritos):
        estado = d.get("estado")
        if estado not in M_ESTADOS:
            raise HTTPException(400, "Estado no válido.")
        if gestion and (estado not in M_GESTION or fotos):
            raise HTTPException(403, "Tu usuario solo puede marcar la novedad como informada a mantenimiento o en reparación.")
        t = hoy()
        with conexion() as c:
            m = _marca(c, n)
            if gestion and m["estado"] in M_CERRADOS:
                raise HTTPException(403, "La novedad está cerrada; solo un inspector puede reabrirla.")
            cerr = estado in M_CERRADOS
            rev = None if cerr else (_fecha(d.get("revision"), "fecha de revisión", True) or m["fecha_revision"])
            ejecutar(c, "UPDATE marca SET estado=%s, fecha_cierre=%s, fecha_revision=%s WHERE nro_marca=%s",
                     (estado, t if cerr else None, rev, m["nro_marca"]))
            _hist(c, m["nro_marca"], None, f"{m['estado']} → {estado}", d.get("nota"), u["id_usuario"])
            _insertar_fotos(c, fotos.get("estado", []), m["nro_marca"], None, t, "Después" if cerr else "Seguimiento", u["id_usuario"], escritos)
        return {"ok": True}

    r = await run_in_threadpool(_con_fotos, tx)
    cambio()
    return r


@app.post("/api/marcas/{n}/borrar")
async def api_marca_borrar(n: str, req: Request):
    u = await run_in_threadpool(exigir, req, "supervisor", True)
    d = await req.json()
    motivo = _texto(d.get("motivo"))
    if len(motivo) < 5:
        raise HTTPException(400, "Escribí el motivo del borrado.")

    def tx():
        with conexion() as c:
            m = _marca(c, n)
            fs = filas(c, "SELECT archivo FROM foto WHERE nro_registro=%s", (m["nro_marca"],))
            ejecutar(c, """INSERT INTO registro_borrado (nro_registro,nro_uf,descripcion,estado,fecha,observacion,motivo,fotos_eliminadas,id_usuario)
                           VALUES (%s,NULL,%s,%s,%s,%s,%s,%s,%s)""",
                     (m["nro_marca"], f"{m['lugar']} · {m['tipo']} · {m['descripcion']}"[:300], m["estado"], m["fecha"], m["observacion"],
                      motivo, len(fs), u["id_usuario"]))
            ejecutar(c, "DELETE FROM registro WHERE nro_registro=%s", (m["nro_marca"],))
        for f in fs:
            F.a_papelera(f["archivo"])
        return {"ok": True}

    r = await run_in_threadpool(tx)
    cambio()
    return r


# ───────── red de calles e itinerario diario ─────────
def _ajuste(c, clave, defecto=None):
    r = fila(c, "SELECT valor FROM ajuste WHERE clave=%s", (clave,))
    if not r:
        return defecto
    return json.loads(r["valor"]) if isinstance(r["valor"], str) else r["valor"]


def _xy(p, nombre="punto"):
    try:
        x, y = float(p["x"]), float(p["y"])
    except (TypeError, ValueError, KeyError):
        raise HTTPException(400, f"El {nombre} no tiene coordenadas válidas.")
    if not (-500 <= x <= 4500 and -500 <= y <= 4000):
        raise HTTPException(400, f"El {nombre} está fuera del plano.")
    return x, y


@app.get("/api/red")
def api_red(req: Request):
    exigir(req, "inspector")
    with conexion() as c:
        tramos = filas(c, """SELECT id_tramo id, nodo_a a, nodo_b b, tipo, sentido, geometria geo, largo_m largo, revisado,
                             modificado FROM red_tramo ORDER BY id_tramo""")
        for t in tramos:
            t["geo"] = json.loads(t["geo"]) if isinstance(t["geo"], str) else t["geo"]
            t["revisado"] = bool(t["revisado"])
        return {"tramos": tramos, "inicio": _ajuste(c, "inicio_recorrido", {"x": 1620, "y": 45, "nombre": "Acceso principal"})}


@app.put("/api/red/tramos/{tid}")
async def api_red_tramo(tid: int, req: Request):
    u = await run_in_threadpool(exigir, req, "admin", True)
    d = await req.json()

    def tx():
        with conexion() as c:
            t = fila(c, "SELECT * FROM red_tramo WHERE id_tramo=%s FOR UPDATE", (tid,))
            if not t:
                raise HTTPException(404, "No existe ese tramo.")
            tipo = d.get("tipo", t["tipo"])
            sentido = d.get("sentido", t["sentido"])
            if tipo not in ("calle", "peatonal", "borde", "cerrado") or sentido not in ("doble", "a_b", "b_a"):
                raise HTTPException(400, "Tipo o sentido no válido.")
            ejecutar(c, """UPDATE red_tramo SET tipo=%s, sentido=%s, revisado=%s, modificado=NOW(), id_usuario=%s
                           WHERE id_tramo=%s""", (tipo, sentido, tipo != "borde", u["id_usuario"], tid))
        RUT.invalidar()
        return {"ok": True}
    return await run_in_threadpool(tx)


@app.put("/api/red/inicio")
async def api_red_inicio(req: Request):
    await run_in_threadpool(exigir, req, "admin", True)
    d = await req.json()
    x, y = _xy(d, "punto de inicio")
    v = {"x": round(x, 1), "y": round(y, 1), "nombre": _texto(d.get("nombre"), 60) or "Punto de inicio"}

    def tx():
        with conexion() as c:
            ejecutar(c, "REPLACE INTO ajuste (clave, valor) VALUES ('inicio_recorrido', %s)", (json.dumps(v),))
        return {"ok": True, "inicio": v}
    return await run_in_threadpool(tx)


def _pedido_ruta(c, d):
    modo = d.get("modo") if d.get("modo") in ("vehiculo", "pie") else "vehiculo"
    ini = d.get("inicio") or _ajuste(c, "inicio_recorrido", {"x": 1620, "y": 45, "nombre": "Acceso principal"})
    x, y = _xy(ini, "punto de inicio")
    inicio = {"x": x, "y": y, "nombre": _texto(ini.get("nombre"), 60) or "Inicio"}
    paradas, vistas = [], set()
    for p in (d.get("paradas") or [])[:60]:
        tipo = p.get("tipo") if p.get("tipo") in ("uf", "marca") else None
        ref = _texto(p.get("ref"), 20)
        if not tipo or not ref or (tipo, ref) in vistas:
            continue
        vistas.add((tipo, ref))
        px, py = _xy(p, f"punto de {ref}")
        paradas.append({"tipo": tipo, "ref": ref, "x": px, "y": py, "fijada": bool(p.get("fijada"))})
    if not paradas:
        raise HTTPException(400, "Elegí al menos una parada.")
    return modo, inicio, paradas, bool(d.get("volver")), d.get("criterio") if d.get("criterio") in ("tiempo", "distancia") else "tiempo"


def _calcular(c, modo, inicio, paradas, volver, criterio="tiempo"):
    try:
        return RUT.planificar(c, filas, modo, inicio, paradas, volver, criterio)
    except RUT.SinRuta as e:
        raise HTTPException(400, str(e))


@app.post("/api/itinerarios/calcular")
async def api_itin_calcular(req: Request):
    await run_in_threadpool(exigir, req, "inspector", True)
    d = await req.json()

    def tx():
        with conexion() as c:
            return _calcular(c, *_pedido_ruta(c, d))
    return await run_in_threadpool(tx)


def _guardar_paradas(c, iid, ruta, previas=()):
    ejecutar(c, "DELETE FROM itinerario_parada WHERE id_itinerario=%s", (iid,))
    filas_ = list(previas) + [dict(p, estado="pendiente", marcada=None) for p in ruta["paradas"]]
    km = {len(previas) + k: pi["km"] for k, pi in enumerate(ruta["piernas"])}
    for k, p in enumerate(filas_):
        ejecutar(c, """INSERT INTO itinerario_parada (id_itinerario, orden, tipo, ref, x, y, fijada, estado, marcada, km_desde_anterior)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                 (iid, k + 1, p["tipo"], p["ref"], p["x"], p["y"], bool(p.get("fijada")), p["estado"], p.get("marcada"),
                  km.get(k, p.get("km_desde_anterior") or 0)))


@app.post("/api/itinerarios")
async def api_itin_guardar(req: Request):
    u = await run_in_threadpool(exigir, req, "inspector", True)
    d = await req.json()

    def tx():
        with conexion() as c:
            modo, inicio, paradas, volver, criterio = _pedido_ruta(c, d)
            ruta = _calcular(c, modo, inicio, paradas, volver, criterio)
            ejecutar(c, """UPDATE itinerario SET estado='reemplazado', cerrado=NOW()
                           WHERE id_usuario=%s AND fecha=%s AND estado='activo'""", (u["id_usuario"], hoy()))
            ejecutar(c, """INSERT INTO itinerario (fecha, id_usuario, modo, inicio, volver, km_plan, minutos_plan, geometria)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                     (hoy(), u["id_usuario"], modo, json.dumps(inicio), volver, ruta["km"], ruta["minutos"],
                      json.dumps(ruta["piernas"])))
            iid = fila(c, "SELECT LAST_INSERT_ID() id")["id"]
            _guardar_paradas(c, iid, ruta)
            return _itinerario(c, iid)
    r = await run_in_threadpool(tx)
    cambio()
    return r


def _itinerario(c, iid):
    it = fila(c, """SELECT i.*, u.nombre usuario FROM itinerario i JOIN usuario u ON u.id_usuario=i.id_usuario
                    WHERE i.id_itinerario=%s""", (iid,))
    if not it:
        raise HTTPException(404, "No existe ese recorrido.")
    for k in ("inicio", "geometria"):
        it[k] = json.loads(it[k]) if isinstance(it[k], str) else it[k]
    ps = filas(c, "SELECT * FROM itinerario_parada WHERE id_itinerario=%s ORDER BY orden", (iid,))
    for p in ps:                                   # una visita o un movimiento cargado después de planificar la marca como hecha
        p["fijada"] = bool(p["fijada"])
        if p["estado"] == "hecha":
            continue
        if p["tipo"] == "uf":
            ufs = [int(x) for x in re.findall(r"\d+", p["ref"])]
            r = fila(c, f"""SELECT MIN(creado) t FROM visita WHERE nro_uf IN ({','.join(['%s'] * len(ufs))})
                            AND fecha=%s AND creado >= %s""", (*ufs, it["fecha"], it["creado"])) if ufs else None
        else:
            r = fila(c, "SELECT MIN(creado) t FROM historial WHERE nro_registro=%s AND creado >= %s", (p["ref"], it["creado"]))
        if r and r["t"]:
            p["estado"], p["marcada"], p["auto"] = "hecha", r["t"], True
    it["paradas"] = ps
    it["hechas"] = sum(1 for p in ps if p["estado"] == "hecha")
    it["salteadas"] = sum(1 for p in ps if p["estado"] == "salteada")
    it["volver"] = bool(it["volver"])
    return it


def _dueno(c, req, iid, u):
    it = fila(c, "SELECT id_usuario, estado FROM itinerario WHERE id_itinerario=%s FOR UPDATE", (iid,))
    if not it:
        raise HTTPException(404, "No existe ese recorrido.")
    if it["id_usuario"] != u["id_usuario"] and u["rol"] not in ("supervisor", "admin"):
        raise HTTPException(403, "Ese recorrido es de otro usuario.")
    return it


@app.get("/api/itinerarios/actual")
def api_itin_actual(req: Request):
    u = exigir(req, "inspector")
    with conexion() as c:
        r = fila(c, """SELECT id_itinerario FROM itinerario WHERE id_usuario=%s AND fecha=%s AND estado='activo'
                       ORDER BY id_itinerario DESC LIMIT 1""", (u["id_usuario"], hoy()))
        return _itinerario(c, r["id_itinerario"]) if r else None


@app.get("/api/itinerarios/{iid}")
def api_itin_ver(iid: int, req: Request):
    u = exigir(req, "inspector")
    with conexion() as c:
        _dueno(c, req, iid, u)
        return _itinerario(c, iid)


@app.post("/api/itinerarios/{iid}/paradas/{orden}")
async def api_itin_parada(iid: int, orden: int, req: Request):
    u = await run_in_threadpool(exigir, req, "inspector", True)
    d = await req.json()
    if d.get("estado") not in ("pendiente", "hecha", "salteada"):
        raise HTTPException(400, "Estado no válido.")

    def tx():
        with conexion() as c:
            _dueno(c, req, iid, u)
            if not fila(c, "SELECT 1 x FROM itinerario_parada WHERE id_itinerario=%s AND orden=%s", (iid, orden)):
                raise HTTPException(404, "No existe esa parada.")
            ejecutar(c, "UPDATE itinerario_parada SET estado=%s, marcada=%s WHERE id_itinerario=%s AND orden=%s",
                     (d["estado"], None if d["estado"] == "pendiente" else dt.datetime.now(), iid, orden))
            return _itinerario(c, iid)
    return await run_in_threadpool(tx)


@app.post("/api/itinerarios/{iid}/recalcular")
async def api_itin_recalcular(iid: int, req: Request):
    """Reordena lo que falta desde la posición actual (o desde la última parada hecha)."""
    u = await run_in_threadpool(exigir, req, "inspector", True)
    d = await req.json()

    def tx():
        with conexion() as c:
            _dueno(c, req, iid, u)
            it = _itinerario(c, iid)
            hechas = [p for p in it["paradas"] if p["estado"] != "pendiente"]
            pend = [p for p in it["paradas"] if p["estado"] == "pendiente"]
            if not pend:
                raise HTTPException(400, "No quedan paradas pendientes.")
            if d.get("inicio"):
                x, y = _xy(d["inicio"], "punto de partida")
                inicio = {"x": x, "y": y, "nombre": "Mi ubicación"}
            elif hechas:
                ult = [p for p in hechas if p["estado"] == "hecha"][-1:] or hechas[-1:]
                inicio = {"x": float(ult[0]["x"]), "y": float(ult[0]["y"]), "nombre": ult[0]["ref"]}
            else:
                inicio = it["inicio"]
            ruta = _calcular(c, it["modo"], inicio, [{"tipo": p["tipo"], "ref": p["ref"], "x": float(p["x"]), "y": float(p["y"]),
                                                       "fijada": p["fijada"]} for p in pend], it["volver"])
            prev = [dict(p, x=float(p["x"]), y=float(p["y"]), estado=p["estado"] if not p.get("auto") else "hecha") for p in hechas]
            _guardar_paradas(c, iid, ruta, prev)
            ejecutar(c, "UPDATE itinerario SET geometria=%s WHERE id_itinerario=%s", (json.dumps(ruta["piernas"]), iid))
            r = _itinerario(c, iid)
            r["recalculado"] = {"km": ruta["km"], "minutos": ruta["minutos"], "avisos": ruta["avisos"]}
            return r
    r = await run_in_threadpool(tx)
    return r


@app.post("/api/itinerarios/{iid}/paradas/{orden}/llegada")
async def api_itin_llegada(iid: int, orden: int, req: Request):
    """El celular avisa que llegó a la parada (GPS dentro del radio durante unos segundos). Queda como constancia."""
    u = await run_in_threadpool(exigir, req, "inspector", True)
    d = await req.json()

    def num(k, hi):
        try:
            v = int(float(d.get(k)))
            return v if 0 <= v <= hi else None
        except (TypeError, ValueError):
            return None

    def tx():
        with conexion() as c:
            _dueno(c, req, iid, u)
            ejecutar(c, """UPDATE itinerario_parada SET llegada=NOW(), llegada_m=%s, llegada_prec=%s
                           WHERE id_itinerario=%s AND orden=%s AND llegada IS NULL""", (num("dist_m", 5000), num("prec", 65000), iid, orden))
            return _itinerario(c, iid)
    return await run_in_threadpool(tx)


def _pendientes_visita(c):
    """Paradas que quedaron sin visitar (recorrido terminado, o activo de un día anterior) y que todavía nadie visitó."""
    ps = filas(c, """SELECT p.ref, p.tipo, p.x, p.y, i.fecha, i.creado, u.nombre usuario FROM itinerario_parada p
                     JOIN itinerario i ON i.id_itinerario=p.id_itinerario JOIN usuario u ON u.id_usuario=i.id_usuario
                     WHERE p.tipo='uf' AND (p.estado='no_visitada' OR (p.estado='pendiente' AND i.estado='activo' AND i.fecha < %s))
                     ORDER BY i.fecha DESC""", (hoy(),))
    if not ps:
        return []
    ult = {r["nro_uf"]: r["t"] for r in filas(c, "SELECT nro_uf, MAX(creado) t FROM visita GROUP BY nro_uf")}
    out, vistos = [], set()
    for p in ps:
        ufs = [int(x) for x in re.findall(r"\d+", p["ref"])]
        if p["ref"] in vistos or any(ult.get(x) and ult[x] >= p["creado"] for x in ufs):
            continue
        vistos.add(p["ref"])
        out.append({"ref": p["ref"], "ufs": ufs, "desde": p["fecha"], "usuario": p["usuario"]})
    return out


@app.post("/api/itinerarios/{iid}/terminar")
async def api_itin_terminar(iid: int, req: Request):
    u = await run_in_threadpool(exigir, req, "inspector", True)

    def tx():
        with conexion() as c:
            _dueno(c, req, iid, u)
            it = _itinerario(c, iid)
            if it["estado"] == "activo":
                for p in it["paradas"]:     # lo que se marcó solo por una visita queda como hecho; lo que falta, "no visitada"
                    if p.get("auto"):
                        ejecutar(c, "UPDATE itinerario_parada SET estado='hecha', marcada=%s WHERE id_itinerario=%s AND orden=%s",
                                 (p["marcada"], iid, p["orden"]))
                    elif p["estado"] == "pendiente":
                        ejecutar(c, "UPDATE itinerario_parada SET estado='no_visitada' WHERE id_itinerario=%s AND orden=%s", (iid, p["orden"]))
            ejecutar(c, "UPDATE itinerario SET estado='terminado', cerrado=NOW() WHERE id_itinerario=%s AND estado='activo'", (iid,))
            return _itinerario(c, iid)
    return await run_in_threadpool(tx)


@app.get("/api/itinerarios")
def api_itin_lista(req: Request):
    u = exigir(req, "inspector")
    q = req.query_params
    desde = _fecha(q.get("desde"), "fecha desde", True) or (hoy() - dt.timedelta(days=30))
    hasta = _fecha(q.get("hasta"), "fecha hasta", True) or hoy()
    cond, args = ["i.fecha BETWEEN %s AND %s", "i.estado <> 'reemplazado'"], [desde, hasta]
    if u["rol"] not in ("supervisor", "admin"):
        cond.append("i.id_usuario=%s")
        args.append(u["id_usuario"])
    with conexion() as c:
        ids = filas(c, f"SELECT i.id_itinerario FROM itinerario i WHERE {' AND '.join(cond)} ORDER BY i.fecha DESC, i.id_itinerario DESC LIMIT 200", args)
        out = []
        for r in ids:
            it = _itinerario(c, r["id_itinerario"])
            out.append({k: it[k] for k in ("id_itinerario", "fecha", "usuario", "modo", "km_plan", "minutos_plan", "estado", "hechas", "salteadas")}
                       | {"paradas": len(it["paradas"])})
        return out


# ───────── importación de faltas desde la planilla de Reportes (solo admin) ─────────
@app.post("/api/importar/faltas")
async def api_importar(req: Request):
    u = await run_in_threadpool(exigir, req, "admin", True)
    form = await req.form()
    f = form.get("archivo")
    if not hasattr(f, "read"):
        raise HTTPException(400, "Elegí el archivo CSV.")
    raw = await f.read(IMPB.MAX_BYTES + 1)
    confirmar = form.get("confirmar") == "1"
    nombre = (getattr(f, "filename", "") or "planilla.csv").replace("\\", "/").split("/")[-1]

    if raw[:2] == b"PK":                      # .xlsx: la planilla completa de Construcciones
        class _Deshacer(Exception):
            pass

        def tx_base():
            try:
                hojas = IMPB.leer(raw)
            except IMPB.ErrorArchivo as e:
                raise HTTPException(400, str(e))
            res = {}
            try:
                with conexion() as c:
                    res = IMPB.procesar(c, hojas, nombre, u["id_usuario"])
                    if not (confirmar and res["hay_cambios"]):
                        raise _Deshacer()     # revisión previa: se deshace todo
            except _Deshacer:
                pass
            res["confirmado"] = bool(confirmar and res["hay_cambios"])
            if not res["confirmado"]:
                res["importacion"] = None
            return res

        r = await run_in_threadpool(tx_base)
        if r["confirmado"]:
            cambio()
        return r
    if len(raw) > IMP.MAX_BYTES:
        raise HTTPException(400, "El archivo supera los 2 MB.")

    def tx():
        try:
            rows = IMP.leer(raw)
        except IMP.ErrorArchivo as e:
            raise HTTPException(400, str(e))
        with conexion() as c:
            rows = IMP.analizar(c, rows)
            nuevas = [d for d in rows if d["resultado"] == "nueva"]
            imp = None
            if confirmar and nuevas:
                imp, _ = IMP.aplicar(c, nuevas, nombre, u["id_usuario"])
                cuenta = {k: sum(1 for d in rows if d["resultado"] == k) for k in ("nueva", "omitida", "error")}
                ejecutar(c, "UPDATE importacion SET filas=%s, creadas=%s, omitidas=%s, errores=%s WHERE id_importacion=%s",
                         (len(rows), cuenta["nueva"], cuenta["omitida"], cuenta["error"], imp))
        return {"archivo": nombre, "confirmado": bool(confirmar and nuevas), "importacion": imp, "filas": [
            {k: d.get(k) for k in ("fila", "n", "fecha", "uf", "codigo", "estado", "cargo", "resultado", "motivo", "nuevo")} for d in rows]}

    r = await run_in_threadpool(tx)
    if r["confirmado"]:
        cambio()
    return r


@app.get("/api/importar/historial")
def api_importar_hist(req: Request):
    exigir(req, "admin")
    with conexion() as c:
        return filas(c, """SELECT i.id_importacion id, i.archivo, i.filas, i.creadas, i.omitidas, i.errores, i.creado, u.nombre usuario
                           FROM importacion i JOIN usuario u ON u.id_usuario = i.id_usuario ORDER BY i.id_importacion DESC LIMIT 30""")


# ───────── catálogo ─────────
def _guardar_cat(c, x):
    cod, falta = _texto(x.get("codigo"), 10), _texto(x.get("falta"), 250)
    if not cod or not falta:
        return False
    rubro = _texto(x.get("rubro"), 80) or "Sin rubro"
    ejecutar(c, "INSERT IGNORE INTO rubro (nombre) VALUES (%s)", (rubro,))
    rid = fila(c, "SELECT id_rubro FROM rubro WHERE nombre=%s", (rubro,))["id_rubro"]
    ejecutar(c, """INSERT INTO catalogo_falta (codigo,id_rubro,falta,norma,articulo,penalidad,activo)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE id_rubro=VALUES(id_rubro), falta=VALUES(falta), norma=VALUES(norma),
                   articulo=VALUES(articulo), penalidad=VALUES(penalidad), activo=VALUES(activo)""",
             (cod, rid, falta, _texto(x.get("norma"), 150), _texto(x.get("articulo"), 40), _texto(x.get("penalidad"), 150),
              x.get("activo", True) is not False))
    return True


@app.post("/api/catalogo")
async def api_catalogo(req: Request):
    await run_in_threadpool(exigir, req, "admin", True)
    d = await req.json()

    def tx():
        filas_in = d.get("filas") or []
        if len(filas_in) > 2000:
            raise HTTPException(400, "Demasiadas filas.")
        with conexion() as c:
            if d.get("quitar_ejemplos"):
                ejecutar(c, "UPDATE catalogo_falta SET activo=FALSE WHERE codigo LIKE 'EJ-%%'")
                ejecutar(c, """DELETE FROM catalogo_falta WHERE codigo LIKE 'EJ-%%'
                               AND codigo NOT IN (SELECT DISTINCT codigo FROM hallazgo)""")
            n = sum(1 for x in filas_in if _guardar_cat(c, x))
        return {"ok": True, "guardados": n}

    r = await run_in_threadpool(tx)
    cambio()
    return r


# ───────── ABM del catálogo (solo admin) ─────────
CODIGO_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,9}$")


def _cat_log(c, codigo, accion, detalle, uid):
    ejecutar(c, "INSERT INTO catalogo_log (codigo,accion,detalle,id_usuario) VALUES (%s,%s,%s,%s)",
             (codigo, accion, detalle[:500], uid))


def _datos_cat(d):
    falta = _texto(d.get("falta"), 250)
    if not falta:
        raise HTTPException(400, "Escribí la descripción de la falta.")
    return {
        "rubro": _texto(d.get("rubro"), 80) or "Sin rubro", "falta": falta,
        "que_observar": _texto(d.get("que_observar"), 2000), "norma": _texto(d.get("norma"), 150),
        "articulo": _texto(d.get("articulo"), 40), "penalidad": _texto(d.get("penalidad"), 150),
        "visible": d.get("visible", True) is not False,
    }


def _rubro_id(c, nombre):
    ejecutar(c, "INSERT IGNORE INTO rubro (nombre) VALUES (%s)", (nombre,))
    return fila(c, "SELECT id_rubro FROM rubro WHERE nombre=%s", (nombre,))["id_rubro"]


@app.post("/api/catalogo/codigos")
async def api_cat_alta(req: Request):
    u = await run_in_threadpool(exigir, req, "admin", True)
    d = await req.json()

    def tx():
        cod = _texto(d.get("codigo"), 10).upper()
        if not CODIGO_OK.match(cod):
            raise HTTPException(400, "El código tiene que tener de 1 a 10 caracteres: letras, números, punto, guion o barra.")
        x = _datos_cat(d)
        with conexion() as c:
            if fila(c, "SELECT 1 e FROM catalogo_falta WHERE codigo=%s", (cod,)):
                raise HTTPException(409, f"El código {cod} ya existe. Editalo en lugar de crearlo.")
            ejecutar(c, """INSERT INTO catalogo_falta (codigo,id_rubro,falta,que_observar,norma,articulo,penalidad,visible_recorrido,activo)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,TRUE)""",
                     (cod, _rubro_id(c, x["rubro"]), x["falta"], x["que_observar"], x["norma"], x["articulo"], x["penalidad"], x["visible"]))
            _cat_log(c, cod, "alta", f"{x['rubro']} · {x['falta']}", u["id_usuario"])
        return {"ok": True, "codigo": cod}

    r = await run_in_threadpool(tx)
    cambio()
    return r


@app.put("/api/catalogo/codigos/{codigo}")
async def api_cat_modif(codigo: str, req: Request):
    u = await run_in_threadpool(exigir, req, "admin", True)
    d = await req.json()

    def tx():
        x = _datos_cat(d)
        with conexion() as c:
            antes = fila(c, """SELECT r.nombre rubro, c.falta, c.que_observar, c.norma, c.articulo, c.penalidad,
                               c.visible_recorrido visible, c.activo FROM catalogo_falta c
                               JOIN rubro r ON r.id_rubro=c.id_rubro WHERE c.codigo=%s""", (codigo[:10],))
            if not antes:
                raise HTTPException(404, f"No existe el código {codigo}.")
            activo = antes["activo"] if d.get("activo") is None else bool(d.get("activo"))
            ejecutar(c, """UPDATE catalogo_falta SET id_rubro=%s, falta=%s, que_observar=%s, norma=%s, articulo=%s,
                           penalidad=%s, visible_recorrido=%s, activo=%s WHERE codigo=%s""",
                     (_rubro_id(c, x["rubro"]), x["falta"], x["que_observar"], x["norma"], x["articulo"], x["penalidad"],
                      x["visible"], activo, codigo[:10]))
            cambios = [k for k in x if str(x[k] or "") != str(antes.get(k) or "") and not (k == "visible" and bool(x[k]) == bool(antes[k]))]
            if bool(activo) != bool(antes["activo"]):
                cambios.append("reactivado" if activo else "dado de baja")
            _cat_log(c, codigo[:10], "modificación", ", ".join(cambios) or "sin cambios", u["id_usuario"])
        return {"ok": True}

    r = await run_in_threadpool(tx)
    cambio()
    return r


@app.delete("/api/catalogo/codigos/{codigo}")
async def api_cat_baja(codigo: str, req: Request):
    """Si el código nunca se usó, se elimina. Si ya tiene faltas cargadas, se da de baja (deja de ofrecerse
    al cargar visitas) pero se conserva, para que el historial de esas faltas siga teniendo su descripción."""
    u = await run_in_threadpool(exigir, req, "admin", True)

    def tx():
        with conexion() as c:
            cat = fila(c, "SELECT codigo FROM catalogo_falta WHERE codigo=%s", (codigo[:10],))
            if not cat:
                raise HTTPException(404, f"No existe el código {codigo}.")
            usos = fila(c, "SELECT COUNT(*) n FROM hallazgo WHERE codigo=%s", (cat["codigo"],))["n"]
            if usos:
                ejecutar(c, "UPDATE catalogo_falta SET activo=FALSE WHERE codigo=%s", (cat["codigo"],))
                _cat_log(c, cat["codigo"], "baja", f"dado de baja (tiene {usos} faltas cargadas)", u["id_usuario"])
                return {"ok": True, "resultado": "baja", "usos": usos}
            ejecutar(c, "DELETE FROM catalogo_falta WHERE codigo=%s", (cat["codigo"],))
            _cat_log(c, cat["codigo"], "eliminado", "sin faltas cargadas", u["id_usuario"])
            return {"ok": True, "resultado": "eliminado", "usos": 0}

    r = await run_in_threadpool(tx)
    cambio()
    return r


@app.get("/api/catalogo/historial")
def api_cat_historial(req: Request):
    exigir(req, "admin")
    with conexion() as c:
        return filas(c, """SELECT l.fecha, l.codigo, l.accion, l.detalle, u.nombre usuario FROM catalogo_log l
                           JOIN usuario u ON u.id_usuario=l.id_usuario ORDER BY l.id DESC LIMIT 200""")


# ───────── ABM de usuarios (solo admin) y cambio de la clave propia ─────────
USUARIO_OK = re.compile(r"^[a-z0-9][a-z0-9._-]{2,39}$")
ROLES = ["consulta", "inspector", "supervisor", "admin"]


def _usr_log(c, id_obj, usuario, accion, detalle, actor):
    ejecutar(c, "INSERT INTO usuario_log (id_usuario_obj,usuario,accion,detalle,id_actor) VALUES (%s,%s,%s,%s,%s)",
             (id_obj, usuario, accion, (detalle or "")[:300], actor))


def _clave_nueva(clave):
    try:
        return hash_clave(clave or "")
    except ValueError as e:
        raise HTTPException(400, str(e))


def _admins_activos(c, excepto=None):
    return fila(c, "SELECT COUNT(*) n FROM usuario WHERE rol='admin' AND activo AND id_usuario<>%s", (excepto or 0,))["n"]


@app.get("/api/usuarios")
def api_usuarios(req: Request):
    exigir(req, "admin")
    with conexion() as c:
        return filas(c, """SELECT u.id_usuario id, u.usuario, u.nombre, u.rol, u.activo, u.creado,
                           (SELECT MAX(a.fecha) FROM acceso_log a WHERE a.usuario=u.usuario AND a.resultado='ok') ultimo_ingreso,
                           (SELECT COUNT(*) FROM visita WHERE id_usuario=u.id_usuario) + (SELECT COUNT(*) FROM hallazgo WHERE id_usuario=u.id_usuario)
                           + (SELECT COUNT(*) FROM historial WHERE id_usuario=u.id_usuario) + (SELECT COUNT(*) FROM foto WHERE id_usuario=u.id_usuario)
                           + (SELECT COUNT(*) FROM registro_borrado WHERE id_usuario=u.id_usuario)
                           + (SELECT COUNT(*) FROM catalogo_log WHERE id_usuario=u.id_usuario)
                           + (SELECT COUNT(*) FROM usuario_log WHERE id_actor=u.id_usuario AND NOT (id_usuario_obj <=> u.id_usuario)) actividad
                           FROM usuario u ORDER BY u.activo DESC, u.nombre""")


@app.post("/api/usuarios")
async def api_usuario_alta(req: Request):
    yo = await run_in_threadpool(exigir, req, "admin", True)
    d = await req.json()

    def tx():
        usuario = _texto(d.get("usuario"), 40).lower()
        nombre = _texto(d.get("nombre"), 80)
        rol = d.get("rol")
        if not USUARIO_OK.match(usuario):
            raise HTTPException(400, "El usuario tiene que tener de 3 a 40 caracteres: minúsculas, números, punto, guion o guion bajo.")
        if not nombre:
            raise HTTPException(400, "Escribí el nombre y apellido.")
        if rol not in ROLES:
            raise HTTPException(400, "Elegí un perfil válido.")
        h = _clave_nueva(d.get("clave"))
        with conexion() as c:
            if fila(c, "SELECT 1 e FROM usuario WHERE usuario=%s", (usuario,)):
                raise HTTPException(409, f"Ya existe el usuario {usuario}.")
            nid = ejecutar(c, "INSERT INTO usuario (usuario,nombre,rol,clave_hash) VALUES (%s,%s,%s,%s)", (usuario, nombre, rol, h))
            _usr_log(c, nid, usuario, "alta", f"{nombre} · {rol}", yo["id_usuario"])
        return {"ok": True, "id": nid}

    r = await run_in_threadpool(tx)
    cambio()
    return r


@app.put("/api/usuarios/{uid}")
async def api_usuario_modif(uid: int, req: Request):
    yo = await run_in_threadpool(exigir, req, "admin", True)
    d = await req.json()

    def tx():
        with conexion() as c:
            u = fila(c, "SELECT id_usuario, usuario, nombre, rol, activo FROM usuario WHERE id_usuario=%s FOR UPDATE", (uid,))
            if not u:
                raise HTTPException(404, "No existe ese usuario.")
            nombre = _texto(d.get("nombre"), 80) if d.get("nombre") is not None else u["nombre"]
            rol = d.get("rol", u["rol"])
            activo = u["activo"] if d.get("activo") is None else bool(d.get("activo"))
            if not nombre:
                raise HTTPException(400, "Escribí el nombre y apellido.")
            if rol not in ROLES:
                raise HTTPException(400, "Elegí un perfil válido.")
            if uid == yo["id_usuario"] and (rol != "admin" or not activo):
                raise HTTPException(400, "No podés quitarte el perfil de administrador ni darte de baja a vos mismo.")
            if u["rol"] == "admin" and u["activo"] and (rol != "admin" or not activo) and _admins_activos(c, uid) == 0:
                raise HTTPException(400, "Tiene que quedar al menos un administrador activo.")
            ejecutar(c, "UPDATE usuario SET nombre=%s, rol=%s, activo=%s WHERE id_usuario=%s", (nombre, rol, activo, uid))
            cambios = []
            if nombre != u["nombre"]: cambios.append(f"nombre: {nombre}")
            if rol != u["rol"]: cambios.append(f"perfil: {u['rol']} → {rol}")
            if bool(activo) != bool(u["activo"]):
                cambios.append("reactivado" if activo else "dado de baja")
                if not activo:
                    ejecutar(c, "DELETE FROM sesion WHERE id_usuario=%s", (uid,))      # lo saca en el momento
            accion = "baja" if (u["activo"] and not activo) else "reactivación" if (activo and not u["activo"]) else "modificación"
            _usr_log(c, uid, u["usuario"], accion, ", ".join(cambios) or "sin cambios", yo["id_usuario"])
        return {"ok": True}

    r = await run_in_threadpool(tx)
    cambio()
    return r


@app.post("/api/usuarios/{uid}/clave")
async def api_usuario_clave(uid: int, req: Request):
    yo = await run_in_threadpool(exigir, req, "admin", True)
    d = await req.json()

    def tx():
        h = _clave_nueva(d.get("clave"))
        with conexion() as c:
            u = fila(c, "SELECT usuario FROM usuario WHERE id_usuario=%s", (uid,))
            if not u:
                raise HTTPException(404, "No existe ese usuario.")
            ejecutar(c, "UPDATE usuario SET clave_hash=%s WHERE id_usuario=%s", (h, uid))
            if uid != yo["id_usuario"]:
                ejecutar(c, "DELETE FROM sesion WHERE id_usuario=%s", (uid,))          # tiene que volver a ingresar
            _usr_log(c, uid, u["usuario"], "clave", "clave restablecida por el administrador", yo["id_usuario"])
        return {"ok": True}

    return await run_in_threadpool(tx)


@app.delete("/api/usuarios/{uid}")
async def api_usuario_eliminar(uid: int, req: Request):
    """Solo se elimina un usuario sin actividad registrada; si cargó algo, se da de baja para conservar la autoría."""
    yo = await run_in_threadpool(exigir, req, "admin", True)

    def tx():
        if uid == yo["id_usuario"]:
            raise HTTPException(400, "No podés eliminar tu propio usuario.")
        with conexion() as c:
            u = fila(c, "SELECT usuario, rol, activo FROM usuario WHERE id_usuario=%s", (uid,))
            if not u:
                raise HTTPException(404, "No existe ese usuario.")
            if u["rol"] == "admin" and u["activo"] and _admins_activos(c, uid) == 0:
                raise HTTPException(400, "Tiene que quedar al menos un administrador activo.")
            usos = fila(c, """SELECT (SELECT COUNT(*) FROM visita WHERE id_usuario=%s) + (SELECT COUNT(*) FROM hallazgo WHERE id_usuario=%s)
                              + (SELECT COUNT(*) FROM historial WHERE id_usuario=%s) + (SELECT COUNT(*) FROM foto WHERE id_usuario=%s)
                              + (SELECT COUNT(*) FROM registro_borrado WHERE id_usuario=%s) + (SELECT COUNT(*) FROM catalogo_log WHERE id_usuario=%s)
                              + (SELECT COUNT(*) FROM usuario_log WHERE id_actor=%s AND NOT (id_usuario_obj <=> %s)) n""", (uid,) * 8)["n"]
            if usos:
                raise HTTPException(409, "Este usuario tiene actividad registrada: no se puede eliminar, solo dar de baja.")
            _usr_log(c, None, u["usuario"], "eliminado", "sin actividad registrada", yo["id_usuario"])
            ejecutar(c, "UPDATE usuario_log SET id_usuario_obj=NULL WHERE id_usuario_obj=%s", (uid,))
            ejecutar(c, "UPDATE usuario_log SET id_actor=%s WHERE id_actor=%s", (yo["id_usuario"], uid))   # sus propios cambios de clave
            ejecutar(c, "DELETE FROM usuario WHERE id_usuario=%s", (uid,))
        return {"ok": True}

    r = await run_in_threadpool(tx)
    cambio()
    return r


@app.get("/api/usuarios/historial")
def api_usuarios_historial(req: Request):
    exigir(req, "admin")
    with conexion() as c:
        return filas(c, """SELECT l.fecha, l.usuario, l.accion, l.detalle, a.nombre actor FROM usuario_log l
                           JOIN usuario a ON a.id_usuario=l.id_actor ORDER BY l.id DESC LIMIT 200""")


@app.post("/api/yo/clave")
async def api_mi_clave(req: Request):
    yo = await run_in_threadpool(exigir, req, "consulta", True)
    d = await req.json()

    def tx():
        with conexion() as c:
            h = fila(c, "SELECT clave_hash FROM usuario WHERE id_usuario=%s", (yo["id_usuario"],))["clave_hash"]
            try:
                PH.verify(h, d.get("actual") or "")
            except Exception:
                raise HTTPException(400, "La clave actual no es correcta.")
            ejecutar(c, "UPDATE usuario SET clave_hash=%s WHERE id_usuario=%s", (_clave_nueva(d.get("nueva")), yo["id_usuario"]))
            ejecutar(c, "DELETE FROM sesion WHERE id_usuario=%s AND token_hash<>%s", (yo["id_usuario"], _sha(req.cookies.get(COOKIE, ""))))
            _usr_log(c, yo["id_usuario"], yo["usuario"], "clave", "cambió su propia clave", yo["id_usuario"])
        return {"ok": True}

    return await run_in_threadpool(tx)


# ───────── Reportes (consulta, inspector y superiores) ─────────
def _filtros_reporte(req: Request):
    q = req.query_params
    hasta = _fecha(q.get("hasta"), "fecha hasta", True) or hoy()
    desde = _fecha(q.get("desde"), "fecha desde", True) or (hasta - dt.timedelta(days=30))
    if desde > hasta:
        raise HTTPException(400, "La fecha desde no puede ser posterior a la fecha hasta.")
    if (hasta - desde).days > 3660:
        raise HTTPException(400, "El período máximo es de 10 años.")
    cond, args = ["h.fecha BETWEEN %s AND %s"], [desde, hasta]
    if q.get("sector"):
        cond.append("s.nombre = %s"); args.append("Sector " + q.get("sector")[:10])
    if q.get("rubro"):
        cond.append("r.nombre = %s"); args.append(q.get("rubro")[:80])
    if q.get("codigo"):
        cond.append("h.codigo = %s"); args.append(q.get("codigo")[:10])
    est = q.get("estado", "")
    cerr = "('Resuelto','Verificado sin falta')"
    if est == "abiertas":
        cond.append(f"h.estado NOT IN {cerr}")
    elif est == "cerradas":
        cond.append(f"h.estado IN {cerr}")
    elif est == "vencidas":
        cond.append(f"h.estado NOT IN {cerr} AND h.fecha_revision < %s"); args.append(hoy())
    elif est in ESTADOS:
        cond.append("h.estado = %s"); args.append(est)
    return desde, hasta, " AND ".join(cond), args


_BASE_REPORTE = """FROM hallazgo h JOIN visita v ON v.nro_visita = h.nro_visita
    JOIN unidad_funcional uf ON uf.nro_uf = v.nro_uf JOIN sector s ON s.id_sector = uf.id_sector
    JOIN catalogo_falta c ON c.codigo = h.codigo JOIN rubro r ON r.id_rubro = c.id_rubro
    JOIN usuario u ON u.id_usuario = h.id_usuario"""
_ABIERTA = "h.estado NOT IN ('Resuelto','Verificado sin falta')"


def _listado(c, where, args, limite):
    return filas(c, f"""SELECT h.nro_hallazgo n, h.fecha, v.nro_uf uf, s.nombre sector, r.nombre rubro, h.codigo, c.falta,
                        h.estado, h.fecha_revision revision, h.fecha_cierre cierre, h.reiterancia reit, u.nombre cargo,
                        h.observacion obs {_BASE_REPORTE} WHERE {where} ORDER BY h.fecha DESC, h.nro_hallazgo DESC LIMIT {int(limite)}""", args)


@app.get("/api/reportes")
def api_reportes(req: Request):
    exigir(req, "consulta")
    desde, hasta, where, args = _filtros_reporte(req)
    t = hoy()
    with conexion() as c:
        res = fila(c, f"""SELECT COUNT(*) detectadas, SUM({_ABIERTA}) abiertas, SUM(NOT ({_ABIERTA})) cerradas,
                          SUM({_ABIERTA} AND h.fecha_revision < %s) vencidas, SUM(h.reiterancia > 0) reiteradas,
                          COUNT(DISTINCT v.nro_uf) ufs, ROUND(AVG(CASE WHEN h.fecha_cierre IS NOT NULL
                          THEN DATEDIFF(h.fecha_cierre, h.fecha) END), 1) dias_cierre {_BASE_REPORTE} WHERE {where}""", [t] + args)
        vcond, vargs = ["v.fecha BETWEEN %s AND %s"], [desde, hasta]
        if req.query_params.get("sector"):
            vcond.append("s.nombre = %s"); vargs.append("Sector " + req.query_params["sector"][:10])
        res["visitas"] = fila(c, f"""SELECT COUNT(*) n FROM visita v JOIN unidad_funcional uf ON uf.nro_uf=v.nro_uf
                                     JOIN sector s ON s.id_sector=uf.id_sector WHERE {' AND '.join(vcond)}""", vargs)["n"]
        agr = lambda campo, extra="", lim=50: filas(c, f"""SELECT {campo} etiqueta, COUNT(*) n, SUM({_ABIERTA}) abiertas {extra}
                                                     {_BASE_REPORTE} WHERE {where} GROUP BY 1 ORDER BY n DESC LIMIT {lim}""", args)
        out = {
            "desde": desde.isoformat(), "hasta": hasta.isoformat(), "resumen": res,
            "por_estado": agr("h.estado"),
            "por_sector": agr("s.nombre"),
            "por_rubro": agr("r.nombre"),
            "por_tipo": agr("CONCAT(h.codigo, ' · ', c.falta)", lim=15),
            "por_inspector": agr("u.nombre"),
            "por_uf": agr("v.nro_uf", lim=10),
            "por_mes": agr("DATE_FORMAT(h.fecha, '%%Y-%%m')", lim=120),
            "listado": _listado(c, where, args, 500),
        }
    out["por_mes"].sort(key=lambda x: x["etiqueta"])
    for k in ("resumen",):
        out[k] = {a: (int(b) if isinstance(b, (int, float)) and a != "dias_cierre" else b) for a, b in out[k].items()}
    return out


@app.get("/api/reportes.csv")
def api_reportes_csv(req: Request):
    exigir(req, "consulta")
    desde, hasta, where, args = _filtros_reporte(req)
    with conexion() as c:
        rows = _listado(c, where, args, 50000)
    import csv
    import io
    buf = io.StringIO()
    buf.write("\ufeff")                          # BOM: Excel abre bien los acentos
    w = csv.writer(buf, delimiter=";")
    w.writerow(["N° falta", "Fecha", "U.F.", "Sector", "Rubro", "Código", "Falta", "Estado", "Revisión", "Cierre",
                "Reiterancia", "Cargó", "Observación"])
    for r in rows:
        w.writerow([r["n"], r["fecha"], r["uf"], r["sector"], r["rubro"], r["codigo"], r["falta"], r["estado"],
                    r["revision"] or "", r["cierre"] or "", r["reit"], r["cargo"], (r["obs"] or "").replace("\n", " ")])
    nombre = f"faltas_{desde.isoformat()}_{hasta.isoformat()}.csv"
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"', "Cache-Control": "no-store"})


# ───────── Modo "todo en uno" (Railway): la API sirve también la web, sin nginx ─────────
if os.environ.get("SERVIR_WEB") == "1":
    from fastapi.staticfiles import StaticFiles

    _CABECERAS = {
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                                   "font-src https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self'; "
                                   "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "geolocation=(self), camera=(self), microphone=()",
        "Strict-Transport-Security": "max-age=31536000",
    }

    @app.middleware("http")
    async def _cabeceras(req: Request, call_next):
        resp = await call_next(req)
        for k, v in _CABECERAS.items():
            resp.headers.setdefault(k, v)
        p = req.url.path
        if p == "/" or p.endswith((".html", ".js", ".css")):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    app.mount("/", StaticFiles(directory=os.environ.get("WEB_DIR", "/srv/web"), html=True), name="web")
