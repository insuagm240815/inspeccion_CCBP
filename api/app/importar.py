"""Importación de faltas desde la planilla CSV que exporta Reportes (solo admin).

Sirve para llevar a un entorno de prueba (o a producción) lo que un inspector cargó en otro.
Cada fila válida crea una falta nueva con número propio de esta base; las faltas del mismo día,
U.F. e inspector quedan en una misma visita. Una fila ya importada (o que ya existe con el mismo
número, fecha, U.F. y código) se omite, así el mismo archivo se puede subir más de una vez.
"""
import csv
import datetime as dt
import hashlib
import io
import unicodedata

from .db import ejecutar, fila, filas, hoy, siguiente

MAX_BYTES = 2 * 1024 * 1024
MAX_FILAS = 5000

ESTADOS = ['Pendiente', 'Aviso verbal', 'Aviso por folleto', 'Derivado a Comisión',
           'Notificado/Intimado', 'En proceso de resolución', 'Resuelto', 'Verificado sin falta']
CERRADOS = ['Resuelto', 'Verificado sin falta']

# encabezado normalizado → campo
COLUMNAS = {"n falta": "n", "no falta": "n", "nro falta": "n", "numero": "n", "fecha": "fecha", "uf": "uf",
            "u f": "uf", "codigo": "codigo", "estado": "estado", "revision": "revision", "cierre": "cierre",
            "reiterancia": "reit", "cargo": "cargo", "observacion": "obs"}
OBLIGATORIAS = ("fecha", "uf", "codigo", "estado")


class ErrorArchivo(Exception):
    pass


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in s).split())


def _fecha(s):
    s = (s or "").strip()
    if not s:
        return None
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s[:10], f).date()
        except ValueError:
            pass
    raise ValueError(f"fecha «{s}» no válida")


def leer(raw: bytes):
    """bytes del CSV → lista de dicts con los campos conocidos. Acepta ; , o tab, UTF-8 (con o sin BOM) o Windows-1252."""
    if len(raw) > MAX_BYTES:
        raise ErrorArchivo("El archivo supera los 2 MB.")
    try:
        txt = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        txt = raw.decode("cp1252")
    lineas = txt.splitlines()
    if not lineas:
        raise ErrorArchivo("El archivo está vacío.")
    sep = max(";,\t", key=lineas[0].count)
    rd = csv.reader(io.StringIO(txt), delimiter=sep)
    enc = [COLUMNAS.get(_norm(h)) for h in next(rd)]
    faltan = [c for c in OBLIGATORIAS if c not in enc]
    if faltan:
        raise ErrorArchivo("No es la planilla de faltas de Reportes: faltan las columnas " + ", ".join(faltan) + ".")
    out = []
    for i, r in enumerate(rd, start=2):
        if not any(x.strip() for x in r):
            continue
        if len(out) >= MAX_FILAS:
            raise ErrorArchivo(f"Máximo {MAX_FILAS} filas por archivo.")
        d = {"fila": i}
        for k, v in zip(enc, r):
            if k:
                d[k] = v.strip()
        out.append(d)
    if not out:
        raise ErrorArchivo("La planilla no tiene filas.")
    return out


def _clave(d, fecha, uf, codigo):
    return hashlib.sha256(f"{d.get('n', '')}|{fecha}|{uf}|{codigo}".encode()).hexdigest()


def analizar(c, filas_csv):
    """Valida cada fila contra la base. Devuelve la lista con 'resultado' = nueva | omitida | error y 'motivo'."""
    codigos = {r["codigo"] for r in filas(c, "SELECT codigo FROM catalogo_falta")}
    usuarios = {_norm(r["nombre"]): r["id_usuario"] for r in filas(c, "SELECT id_usuario, nombre FROM usuario")}
    vistas = set()
    for d in filas_csv:
        try:
            fecha = _fecha(d.get("fecha"))
            if not fecha:
                raise ValueError("falta la fecha")
            if fecha > hoy() + dt.timedelta(days=1):
                raise ValueError("la fecha es futura")
            try:
                uf = int(float(d.get("uf", "").split("/")[0]))
            except ValueError:
                raise ValueError(f"U.F. «{d.get('uf')}» no válida")
            if not fila(c, "SELECT 1 x FROM unidad_funcional WHERE nro_uf=%s", (uf,)):
                raise ValueError(f"la U.F. {uf} no existe")
            codigo = d.get("codigo", "").upper()
            if codigo not in codigos:
                raise ValueError(f"el código {codigo or '(vacío)'} no está en Tipos de faltas")
            estado = next((e for e in ESTADOS if _norm(e) == _norm(d.get("estado"))), None)
            if not estado:
                raise ValueError(f"estado «{d.get('estado')}» no válido")
            rev, cierre = _fecha(d.get("revision")), _fecha(d.get("cierre"))
            try:
                reit = max(0, min(int(float(d.get("reit") or 0)), 999))
            except ValueError:
                reit = 0
        except ValueError as e:
            d.update(resultado="error", motivo=str(e)[:200])
            continue
        clave = _clave(d, fecha, uf, codigo)
        n = (d.get("n") or "")[:10]
        if clave in vistas:
            d.update(resultado="omitida", motivo="repetida en el archivo")
        elif fila(c, "SELECT nro_registro FROM importacion_item WHERE clave=%s", (clave,)):
            d.update(resultado="omitida", motivo="ya importada antes")
        elif n and fila(c, """SELECT 1 x FROM hallazgo h JOIN visita v ON v.nro_visita=h.nro_visita
                               WHERE h.nro_hallazgo=%s AND h.fecha=%s AND v.nro_uf=%s AND h.codigo=%s""", (n, fecha, uf, codigo)):
            d.update(resultado="omitida", motivo="ya existe en esta base")
        else:
            cerr = estado in CERRADOS
            d.update(resultado="nueva", motivo="", _v=dict(
                clave=clave, fecha=fecha, uf=uf, codigo=codigo, estado=estado, reit=reit,
                rev=None if cerr else rev, cierre=(cierre or fecha) if cerr else None,
                obs=(d.get("obs") or "")[:2000], uid=usuarios.get(_norm(d.get("cargo")))))
        vistas.add(clave)
    return filas_csv


def aplicar(c, filas_ok, archivo, admin_id):
    """Crea visitas y faltas para las filas 'nueva'. Corre dentro de la transacción del llamador."""
    ejecutar(c, "INSERT INTO importacion (archivo, filas, creadas, omitidas, errores, id_usuario) VALUES (%s,0,0,0,0,%s)",
             (archivo[:120], admin_id))
    imp = fila(c, "SELECT LAST_INSERT_ID() id")["id"]
    visitas, creadas = {}, []
    for d in filas_ok:
        v = d["_v"]
        uid = v["uid"] or admin_id
        kv = (v["fecha"], v["uf"], uid)
        if kv not in visitas:
            nv = siguiente(c, "V")
            ejecutar(c, """INSERT INTO visita (nro_visita, fecha, nro_uf, origen, contacto, observacion, id_usuario)
                           VALUES (%s,%s,%s,'Recorrido de inspección',NULL,%s,%s)""",
                     (nv, v["fecha"], v["uf"], f"Importada de «{archivo[:80]}»", uid))
            visitas[kv] = nv
        nv, nf = visitas[kv], siguiente(c, "F")
        ejecutar(c, "INSERT INTO registro (nro_registro, tipo) VALUES (%s,'F')", (nf,))
        ejecutar(c, """INSERT INTO hallazgo (nro_hallazgo, nro_visita, codigo, fecha, estado, fecha_revision, observacion,
                       reiterancia, fecha_cierre, id_usuario) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                 (nf, nv, v["codigo"], v["fecha"], v["estado"], v["rev"], v["obs"], v["reit"], v["cierre"], uid))
        origen = f" (era {d['n']})" if d.get("n") else ""
        quien = "" if v["uid"] else f" Cargó: {d.get('cargo') or 'sin dato'} (no existe en esta base)."
        ejecutar(c, """INSERT INTO historial (nro_registro, nro_visita, fecha, cambio, nota, id_usuario) VALUES (%s,%s,%s,%s,%s,%s)""",
                 (nf, nv, v["fecha"], f"Alta por importación{origen}. Estado: {v['estado']}", quien.strip(), admin_id))
        ejecutar(c, "INSERT INTO importacion_item (clave, id_importacion, nro_origen, nro_registro) VALUES (%s,%s,%s,%s)",
                 (v["clave"], imp, (d.get("n") or "")[:10], nf))
        d["nuevo"] = nf
        creadas.append(nf)
    return imp, creadas
