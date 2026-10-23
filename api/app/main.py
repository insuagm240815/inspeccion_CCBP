"""API de la Base de Inspección CCBP."""
import asyncio
import datetime as dt
import json
import threading

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse

from . import fotos as F
from .db import conexion, ejecutar, fila, filas, hoy, siguiente
from .seguridad import COOKIE, COOKIE_SECURE, SESION_HORAS, exigir, ip_de, login, logout, usuario_de

app = FastAPI(title="Inspección CCBP", docs_url=None, redoc_url=None, openapi_url=None)

ESTADOS = ['Pendiente', 'Aviso verbal', 'Aviso por folleto', 'Derivado a Comisión',
           'Notificado/Intimado', 'Resuelto', 'Verificado sin falta']
CERRADOS = ['Resuelto', 'Verificado sin falta']
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
    exigir(req)
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
            "catalogo": filas(c, """SELECT c.codigo, r.nombre rubro, c.falta, c.norma, c.articulo, c.penalidad, c.activo
                                    FROM catalogo_falta c JOIN rubro r ON r.id_rubro = c.id_rubro"""),
            "usuarios": filas(c, "SELECT id_usuario id, nombre FROM usuario"),
            "grupos": filas(c, """SELECT a.nro_uf uf, GROUP_CONCAT(DISTINCT b.nro_uf) ufs FROM uf_pilar a
                                  JOIN uf_pilar b ON b.nro_pilar = a.nro_pilar GROUP BY a.nro_uf
                                  HAVING COUNT(DISTINCT b.nro_uf) > 1"""),
        }
    return out


@app.get("/api/fotos/{nro}")
def api_foto(nro: str, req: Request):
    exigir(req)
    with conexion() as c:
        f = fila(c, "SELECT archivo FROM foto WHERE nro_foto=%s", (nro[:10],))
    if not f:
        raise HTTPException(404, "No existe esa foto.")
    return FileResponse(F.ruta(f["archivo"]), media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/eventos")
async def api_eventos(req: Request):
    """Server-Sent Events: avisa a cada navegador cuando cambian los datos, para que recargue."""
    await run_in_threadpool(exigir, req)

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
                    raise HTTPException(400, f"El código {fa.get('codigo')} no está en el catálogo.")
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
    u = await run_in_threadpool(exigir, req, "inspector", True)
    d, fotos = await _form(req)

    def tx(escritos):
        estado = d.get("estado")
        if estado not in ESTADOS:
            raise HTTPException(400, "Estado no válido.")
        t = hoy()
        with conexion() as c:
            h = _falta(c, n)
            cerr = estado in CERRADOS
            v = fila(c, "SELECT nro_visita FROM visita WHERE nro_uf=%s AND fecha=%s ORDER BY nro_visita DESC LIMIT 1",
                     (h["nro_uf"], t))
            nv = v["nro_visita"] if v else None
            if not nv:
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
