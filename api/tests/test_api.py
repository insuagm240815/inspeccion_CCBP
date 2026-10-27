"""Pruebas de la API contra una MariaDB real (la de CI o una local de desarrollo).

Variables: DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, FOTOS_DIR, COOKIE_SECURE=0.
Correr desde api/:  pytest -q
"""
import io
import os
import secrets

os.environ.setdefault("COOKIE_SECURE", "0")

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.db import conexion, ejecutar, fila
from app.main import app
from app.seguridad import hash_clave

CLAVE = "clave-de-prueba-" + secrets.token_hex(4)
SUF = secrets.token_hex(3)
H = {"X-CCBP": "1"}


@pytest.fixture(scope="module")
def usuarios():
    nombres = {}
    with conexion() as c:
        for rol in ("consulta", "inspector", "supervisor", "admin"):
            u = f"t_{rol[:3]}_{SUF}"
            ejecutar(c, "INSERT INTO usuario (usuario,nombre,rol,clave_hash) VALUES (%s,%s,%s,%s)",
                     (u, f"Prueba {rol}", rol, hash_clave(CLAVE)))
            nombres[rol] = u
    return nombres


def cliente(usuario=None):
    c = TestClient(app)
    if usuario:
        r = c.post("/api/login", json={"usuario": usuario, "clave": CLAVE}, headers=H)
        assert r.status_code == 200, r.text
    return c


def jpeg(w=2400, h=1600):
    b = io.BytesIO()
    Image.new("RGB", (w, h), (90, 140, 80)).save(b, "JPEG")
    return b.getvalue()


def test_salud():
    assert TestClient(app).get("/api/salud").json() == {"ok": True}


def test_sin_sesion_no_hay_datos():
    c = TestClient(app)
    assert c.get("/api/estado").status_code == 401
    assert c.get("/api/fotos/P-0001").status_code == 401


def test_login_incorrecto(usuarios):
    r = TestClient(app).post("/api/login", json={"usuario": usuarios["inspector"], "clave": "mala"}, headers=H)
    assert r.status_code == 401


def test_login_exige_encabezado(usuarios):
    r = TestClient(app).post("/api/login", json={"usuario": usuarios["inspector"], "clave": CLAVE})
    assert r.status_code == 403


def test_circuito_completo(usuarios):
    ins, sup = cliente(usuarios["inspector"]), cliente(usuarios["supervisor"])
    import json
    datos = {"uf": 1200, "fecha": None, "origen": "Recorrido de inspección",
             "contacto": "Hablé con el residente", "lat": -34.6019, "lon": -58.8607, "prec": "9",
             "faltas": [{"codigo": "EJ-03", "estado": "Pendiente", "revision": "2099-01-01", "obs": "prueba"}]}
    with conexion() as c:
        datos["fecha"] = str(fila(c, "SELECT CURDATE() d")["d"])
    r = ins.post("/api/visitas", data={"datos": json.dumps(datos)},
                 files=[("f_0", ("a.jpg", jpeg(), "image/jpeg")), ("f_visita", ("b.jpg", jpeg(), "image/jpeg"))], headers=H)
    assert r.status_code == 200, r.text
    nv, nf = r.json()["visita"], r.json()["faltas"][0]

    with conexion() as c:
        v = fila(c, "SELECT lat, precision_m FROM visita WHERE nro_visita=%s", (nv,))
        fotos = fila(c, "SELECT COUNT(*) n FROM foto WHERE nro_visita=%s", (nv,))["n"]
    assert v["lat"] == pytest.approx(-34.6019) and v["precision_m"] == 9
    assert fotos == 2

    est = ins.get("/api/estado").json()
    foto = next(f for f in est["fotos"] if f["reg"] == nf)
    img = Image.open(io.BytesIO(ins.get("/api/fotos/" + foto["n"]).content))
    assert max(img.size) == 1600 and not dict(img.getexif())          # achicada y sin EXIF

    r = ins.post(f"/api/faltas/{nf}/estado", data={"datos": json.dumps({"estado": "Aviso verbal", "nota": "x", "revision": "2099-02-01"})}, headers=H)
    assert r.status_code == 200, r.text
    r = ins.post(f"/api/faltas/{nf}/reprogramar", json={"fecha": "2099-03-01", "nota": "lluvia"}, headers=H)
    assert r.status_code == 200, r.text
    hist = [x["cambio"] for x in ins.get("/api/estado").json()["historial"] if x["reg"] == nf]
    assert hist[0].startswith("Alta") and "Aviso verbal" in hist[1] and hist[2].startswith("Revisión reprogramada")

    # permisos: el inspector no borra; sin encabezado no se escribe
    assert ins.post(f"/api/faltas/{nf}/borrar", json={"motivo": "no corresponde"}, headers=H).status_code == 403
    assert ins.post(f"/api/faltas/{nf}/reprogramar", json={"fecha": "2099-04-01"}).status_code == 403

    r = sup.post(f"/api/faltas/{nf}/borrar", json={"motivo": "Prueba automática"}, headers=H)
    assert r.status_code == 200, r.text
    with conexion() as c:
        assert fila(c, "SELECT COUNT(*) n FROM hallazgo WHERE nro_hallazgo=%s", (nf,))["n"] == 0
        assert fila(c, "SELECT COUNT(*) n FROM historial WHERE nro_registro=%s", (nf,))["n"] == 0
        assert fila(c, "SELECT motivo FROM registro_borrado WHERE nro_registro=%s ORDER BY id DESC LIMIT 1", (nf,))["motivo"] == "Prueba automática"


def test_archivo_que_no_es_imagen(usuarios):
    import json
    ins = cliente(usuarios["inspector"])
    with conexion() as c:
        hoy = str(fila(c, "SELECT CURDATE() d")["d"])
    r = ins.post("/api/visitas", data={"datos": json.dumps({"uf": 10, "fecha": hoy})},
                 files=[("f_visita", ("x.jpg", b"<script>alert(1)</script>", "image/jpeg"))], headers=H)
    assert r.status_code == 400


def test_validaciones(usuarios):
    import json
    ins = cliente(usuarios["inspector"])
    assert ins.post("/api/visitas", data={"datos": json.dumps({"uf": 99999, "fecha": "2020-01-01"})}, headers=H).status_code == 400
    assert ins.post("/api/visitas", data={"datos": json.dumps({"uf": 10, "fecha": "2999-01-01"})}, headers=H).status_code == 400


def test_catalogo_solo_admin(usuarios):
    fila_cat = {"filas": [{"codigo": "T-" + SUF[:4], "rubro": "Prueba", "falta": "Falta de prueba"}]}
    assert cliente(usuarios["supervisor"]).post("/api/catalogo", json=fila_cat, headers=H).status_code == 403
    r = cliente(usuarios["admin"]).post("/api/catalogo", json=fila_cat, headers=H)
    assert r.status_code == 200 and r.json()["guardados"] == 1
    with conexion() as c:
        ejecutar(c, "DELETE FROM catalogo_falta WHERE codigo=%s", ("T-" + SUF[:4],))


def test_consulta_solo_lee(usuarios):
    import json
    c = cliente(usuarios["consulta"])
    assert c.get("/api/estado").status_code == 200
    assert c.get("/api/yo").json()["rol"] == "consulta"
    with conexion() as cx:
        hoy = str(fila(cx, "SELECT CURDATE() d")["d"])
    assert c.post("/api/visitas", data={"datos": json.dumps({"uf": 10, "fecha": hoy})}, headers=H).status_code == 403
    assert c.post("/api/faltas/F-0001/reprogramar", json={"fecha": "2099-01-01"}, headers=H).status_code == 403


def test_consulta_gestiona_faltas(usuarios):
    import json
    ins, con = cliente(usuarios["inspector"]), cliente(usuarios["consulta"])
    with conexion() as cx:
        hoy = str(fila(cx, "SELECT CURDATE() d")["d"])
    r = ins.post("/api/visitas", data={"datos": json.dumps({"uf": 777, "fecha": hoy,
                 "faltas": [{"codigo": "EJ-01", "revision": "2099-01-01"}]})}, headers=H)
    nf = r.json()["faltas"][0]
    with conexion() as cx:
        visitas_antes = fila(cx, "SELECT COUNT(*) n FROM visita")["n"]

    est = lambda c, e, **kw: c.post(f"/api/faltas/{nf}/estado", data={"datos": json.dumps(dict(estado=e, nota="nota", **kw))}, headers=H)
    assert est(con, "Notificado/Intimado", revision="2099-02-01").status_code == 200
    assert est(con, "En proceso de resolución").status_code == 200
    assert est(con, "Resuelto").status_code == 403                       # no puede cerrar
    r = con.post(f"/api/faltas/{nf}/estado", data={"datos": json.dumps({"estado": "Notificado/Intimado"})},
                 files=[("f_estado", ("a.jpg", jpeg(), "image/jpeg"))], headers=H)
    assert r.status_code == 403                                           # no sube fotos

    with conexion() as cx:
        h = fila(cx, "SELECT estado, derivado_comision FROM hallazgo WHERE nro_hallazgo=%s", (nf,))
        assert h["estado"] == "En proceso de resolución" and h["derivado_comision"]
        assert fila(cx, "SELECT COUNT(*) n FROM visita")["n"] == visitas_antes   # no genera visitas
        quien = fila(cx, """SELECT u.rol FROM historial x JOIN usuario u ON u.id_usuario=x.id_usuario
                            WHERE x.nro_registro=%s ORDER BY x.id_historial DESC LIMIT 1""", (nf,))["rol"]
        assert quien == "consulta"

    assert est(ins, "Resuelto").status_code == 200                       # el inspector sí cierra
    assert est(con, "Notificado/Intimado").status_code == 403            # cerrada: consulta no la reabre


def test_abm_catalogo(usuarios):
    import json
    adm, ins = cliente(usuarios["admin"]), cliente(usuarios["inspector"])
    cod = ("Z" + SUF[:5]).upper()
    nuevo = {"codigo": cod, "rubro": "Rubro de prueba", "falta": "Falta de prueba", "norma": "Reglamento", "penalidad": "Multa"}
    # solo admin
    assert ins.post("/api/catalogo/codigos", json=nuevo, headers=H).status_code == 403
    assert adm.post("/api/catalogo/codigos", json=nuevo).status_code == 403                      # sin encabezado
    # alta, duplicado, validación
    assert adm.post("/api/catalogo/codigos", json=nuevo, headers=H).status_code == 200
    assert adm.post("/api/catalogo/codigos", json=nuevo, headers=H).status_code == 409
    assert adm.post("/api/catalogo/codigos", json=dict(nuevo, codigo="MAL COD!"), headers=H).status_code == 400
    # modificación
    r = adm.put(f"/api/catalogo/codigos/{cod}", json=dict(nuevo, falta="Falta corregida", visible=False), headers=H)
    assert r.status_code == 200
    c = next(x for x in adm.get("/api/estado").json()["catalogo"] if x["codigo"] == cod)
    assert c["falta"] == "Falta corregida" and c["visible"] == 0 and c["activo"] == 1
    # usarlo en una falta → la baja no borra, desactiva
    with conexion() as cx:
        hoy = str(fila(cx, "SELECT CURDATE() d")["d"])
    r = ins.post("/api/visitas", data={"datos": json.dumps({"uf": 50, "fecha": hoy, "faltas": [{"codigo": cod}]})}, headers=H)
    assert r.status_code == 200, r.text
    r = adm.delete(f"/api/catalogo/codigos/{cod}", headers=H)
    assert r.json()["resultado"] == "baja" and r.json()["usos"] == 1
    r = ins.post("/api/visitas", data={"datos": json.dumps({"uf": 50, "fecha": hoy, "faltas": [{"codigo": cod}]})}, headers=H)
    assert r.status_code == 400                                                                   # dado de baja: no se ofrece
    # reactivar
    assert adm.put(f"/api/catalogo/codigos/{cod}", json=dict(nuevo, activo=True), headers=H).status_code == 200
    # un código sin usos se elimina
    cod2 = cod[:-1] + "Y"
    adm.post("/api/catalogo/codigos", json=dict(nuevo, codigo=cod2), headers=H)
    assert adm.delete(f"/api/catalogo/codigos/{cod2}", headers=H).json()["resultado"] == "eliminado"
    # historial
    h = adm.get("/api/catalogo/historial").json()
    acciones = {x["accion"] for x in h if x["codigo"] in (cod, cod2)}
    assert {"alta", "modificación", "baja", "eliminado"} <= acciones
    assert ins.get("/api/catalogo/historial").status_code == 403


def test_reportes(usuarios):
    import json
    ins, con = cliente(usuarios["inspector"]), cliente(usuarios["consulta"])
    with conexion() as cx:
        hoy = str(fila(cx, "SELECT CURDATE() d")["d"])
    r = ins.post("/api/visitas", data={"datos": json.dumps({"uf": 2900, "fecha": hoy,
                 "faltas": [{"codigo": "EJ-02", "revision": "2000-01-01"}, {"codigo": "EJ-03", "estado": "Resuelto"}]})}, headers=H)
    assert r.status_code == 200, r.text
    assert TestClient(app).get("/api/reportes").status_code == 401
    for c in (ins, con):                                             # inspector y consulta tienen acceso
        d = c.get("/api/reportes", params={"sector": "Golf"})
        assert d.status_code == 200, d.text
        d = d.json()
        assert d["resumen"]["detectadas"] >= 2 and d["resumen"]["vencidas"] >= 1 and d["resumen"]["cerradas"] >= 1
        assert {"Sector Golf"} == {x["etiqueta"] for x in d["por_sector"]}
        assert any(x["uf"] == 2900 for x in d["listado"])
    v = con.get("/api/reportes", params={"sector": "Golf", "estado": "vencidas"}).json()
    assert all(x["estado"] not in ("Resuelto", "Verificado sin falta") for x in v["listado"])
    assert con.get("/api/reportes", params={"desde": "2026-12-01", "hasta": "2026-01-01"}).status_code == 400
    csv = con.get("/api/reportes.csv", params={"sector": "Golf"})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert csv.text.startswith("﻿N° falta;") and ";2900;" in csv.text


def test_abm_usuarios(usuarios):
    import json
    adm, ins = cliente(usuarios["admin"]), cliente(usuarios["inspector"])
    nu = "t_nuevo_" + SUF
    assert ins.get("/api/usuarios").status_code == 403
    assert ins.post("/api/usuarios", json={"usuario": nu, "nombre": "X", "rol": "inspector", "clave": CLAVE}, headers=H).status_code == 403
    # alta y validaciones
    assert adm.post("/api/usuarios", json={"usuario": "A B", "nombre": "X", "rol": "inspector", "clave": CLAVE}, headers=H).status_code == 400
    assert adm.post("/api/usuarios", json={"usuario": nu, "nombre": "X", "rol": "inspector", "clave": "corta"}, headers=H).status_code == 400
    assert adm.post("/api/usuarios", json={"usuario": nu, "nombre": "X", "rol": "jefe", "clave": CLAVE}, headers=H).status_code == 400
    r = adm.post("/api/usuarios", json={"usuario": nu, "nombre": "Nuevo Usuario", "rol": "consulta", "clave": CLAVE}, headers=H)
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    assert adm.post("/api/usuarios", json={"usuario": nu, "nombre": "X", "rol": "consulta", "clave": CLAVE}, headers=H).status_code == 409
    nuevo = cliente(nu)                                                  # puede ingresar
    assert nuevo.get("/api/yo").json()["rol"] == "consulta"
    # cambio de perfil: rige en el momento, sin volver a ingresar
    assert adm.put(f"/api/usuarios/{uid}", json={"rol": "inspector", "nombre": "Nuevo Usuario"}, headers=H).status_code == 200
    assert nuevo.get("/api/yo").json()["rol"] == "inspector"
    # cambio de su propia clave
    assert nuevo.post("/api/yo/clave", json={"actual": "mala", "nueva": "otra-clave-123"}, headers=H).status_code == 400
    assert nuevo.post("/api/yo/clave", json={"actual": CLAVE, "nueva": "otra-clave-123"}, headers=H).status_code == 200
    assert TestClient(app).post("/api/login", json={"usuario": nu, "clave": "otra-clave-123"}, headers=H).status_code == 200
    # el admin restablece la clave: se cierran sus sesiones
    assert adm.post(f"/api/usuarios/{uid}/clave", json={"clave": CLAVE}, headers=H).status_code == 200
    assert nuevo.get("/api/yo").status_code == 401
    nuevo = cliente(nu)
    # baja: no puede entrar más y se cierran sus sesiones
    assert adm.put(f"/api/usuarios/{uid}", json={"activo": False}, headers=H).status_code == 200
    assert nuevo.get("/api/yo").status_code == 401
    assert TestClient(app).post("/api/login", json={"usuario": nu, "clave": CLAVE}, headers=H).status_code == 401
    # sin actividad → se puede eliminar; con actividad → no
    assert adm.delete(f"/api/usuarios/{uid}", headers=H).status_code == 200
    ins_id = ins.get("/api/yo").json()["id"]
    with conexion() as cx:
        hoy = str(fila(cx, "SELECT CURDATE() d")["d"])
    ins.post("/api/visitas", data={"datos": json.dumps({"uf": 12, "fecha": hoy})}, headers=H)
    assert adm.delete(f"/api/usuarios/{ins_id}", headers=H).status_code == 409
    # protecciones del propio admin
    adm_id = adm.get("/api/yo").json()["id"]
    assert adm.put(f"/api/usuarios/{adm_id}", json={"rol": "inspector"}, headers=H).status_code == 400
    assert adm.put(f"/api/usuarios/{adm_id}", json={"activo": False}, headers=H).status_code == 400
    assert adm.delete(f"/api/usuarios/{adm_id}", headers=H).status_code == 400
    acciones = {x["accion"] for x in adm.get("/api/usuarios/historial").json() if x["usuario"] == nu}
    assert {"alta", "modificación", "clave", "baja", "eliminado"} <= acciones


def test_novedades_espacios_comunes(usuarios):
    import json
    ins, con, sup = cliente(usuarios["inspector"]), cliente(usuarios["consulta"]), cliente(usuarios["supervisor"])
    area = [[1000, 1000], [1100, 1000], [1100, 1100]]
    datos = {"forma": "A", "geo": area, "tipo": "Pasto alto / falta de limpieza", "descripcion": "Plaza central sin cortar",
             "lugar": "Plaza", "estado": "Relevado", "revision": "2099-01-01", "sector": "II",
             "lat": -34.6019, "lon": -58.8607, "ubicacion": "GPS", "prec": "7"}
    # consulta no da de alta; dibujo inválido rechazado
    assert con.post("/api/marcas", data={"datos": json.dumps(datos)}, headers=H).status_code == 403
    malo = dict(datos, geo=area[:2])
    assert ins.post("/api/marcas", data={"datos": json.dumps(malo)}, headers=H).status_code == 400
    r = ins.post("/api/marcas", data={"datos": json.dumps(datos)}, files=[("f_marca", ("a.jpg", jpeg(), "image/jpeg"))], headers=H)
    assert r.status_code == 200, r.text
    n = r.json()["n"]
    m = next(x for x in ins.get("/api/estado").json()["marcas"] if x["n"] == n)
    assert m["forma"] == "Área" and m["geo"] == area and m["sector"] == "Sector II" and m["estado"] == "Relevado"
    assert float(m["lat"]) == pytest.approx(-34.6019) and m["ubic"] == "GPS" and m["prec"] == 7

    # edición y redibujo (inspector); consulta no edita
    assert con.put(f"/api/marcas/{n}", json={"descripcion": "x"}, headers=H).status_code == 403
    r = ins.put(f"/api/marcas/{n}", json={"descripcion": "Plaza central, pasto de 40 cm", "forma": "P", "geo": [[1050, 1050]],
                                          "lat": -34.6020, "lon": -58.8608, "ubicacion": "Plano", "prec": "5"}, headers=H)
    assert r.status_code == 200, r.text

    # consulta gestiona solo estados intermedios
    ok = lambda cl, e: cl.post(f"/api/marcas/{n}/estado", data={"datos": json.dumps({"estado": e, "nota": "t"})}, headers=H).status_code
    assert ok(con, "Reparado") == 403
    assert ok(con, "Informado a mantenimiento") == 200
    assert ok(ins, "Reparado") == 200
    assert ok(con, "En reparación") == 403            # cerrada: solo inspector reabre
    est = ins.get("/api/estado").json()
    m = next(x for x in est["marcas"] if x["n"] == n)
    assert m["forma"] == "Punto" and m["estado"] == "Reparado" and m["cierre"] and not m["revision"]
    assert m["ubic"] == "Plano" and m["prec"] is None and float(m["lon"]) == pytest.approx(-58.8608)
    hist = [x["cambio"] for x in est["historial"] if x["reg"] == n]
    assert hist[0].startswith("Alta en plaza") and hist[1].startswith("Editada") and len(hist) == 4

    # borrado: solo supervisor+, con motivo
    assert ins.post(f"/api/marcas/{n}/borrar", json={"motivo": "prueba"}, headers=H).status_code == 403
    assert sup.post(f"/api/marcas/{n}/borrar", json={"motivo": "Prueba automática"}, headers=H).status_code == 200
    with conexion() as c:
        assert fila(c, "SELECT COUNT(*) n FROM marca WHERE nro_marca=%s", (n,))["n"] == 0
        assert fila(c, "SELECT COUNT(*) n FROM foto WHERE nro_registro=%s", (n,))["n"] == 0


def test_importar_faltas(usuarios):
    adm, ins = cliente(usuarios["admin"]), cliente(usuarios["inspector"])
    n1, n2 = f"F-9{SUF[:3]}", f"F-8{SUF[:3]}"
    csv_txt = ("﻿N° falta;Fecha;U.F.;Sector;Rubro;Código;Falta;Estado;Revisión;Cierre;Reiterancia;Cargó;Observación\n"
               f"{n1};2026-10-20;1200;Sector III;x;EJ-01;x;Pendiente;2026-11-02;;0;Prueba inspector;obs uno\n"
               f"{n2};20/10/2026;1200;Sector III;x;EJ-03;x;Resuelto;;;1;Alguien de afuera;\n"
               "F-0099;2026-10-20;99999;x;x;EJ-01;x;Pendiente;;;0;x;\n"
               "F-0098;2026-10-20;1200;x;x;ZZ-99;x;Pendiente;;;0;x;\n")
    arch = lambda: {"archivo": ("faltas.csv", csv_txt.encode("utf-8"), "text/csv")}
    assert ins.post("/api/importar/faltas", files=arch(), data={"confirmar": "1"}, headers=H).status_code == 403

    r = adm.post("/api/importar/faltas", files=arch(), data={"confirmar": "0"}, headers=H)
    assert r.status_code == 200, r.text
    res = [f["resultado"] for f in r.json()["filas"]]
    assert res == ["nueva", "nueva", "error", "error"] and not r.json()["confirmado"]
    with conexion() as c:
        assert fila(c, "SELECT COUNT(*) n FROM importacion_item WHERE nro_origen IN (%s,%s)", (n1, n2))["n"] == 0

    r = adm.post("/api/importar/faltas", files=arch(), data={"confirmar": "1"}, headers=H)
    assert r.status_code == 200, r.text
    nuevos = [f["nuevo"] for f in r.json()["filas"] if f.get("nuevo")]
    assert len(nuevos) == 2
    est = adm.get("/api/estado").json()
    h = {x["n"]: x for x in est["hallazgos"]}
    assert h[nuevos[0]]["estado"] == "Pendiente" and h[nuevos[0]]["uf"] == 1200 and h[nuevos[0]]["autor"] is not None
    assert h[nuevos[1]]["estado"] == "Resuelto" and h[nuevos[1]]["cierre"] and h[nuevos[1]]["reit"] == 1
    hist = [x for x in est["historial"] if x["reg"] == nuevos[1]]
    assert f"era {n2}" in hist[0]["cambio"] and "Alguien de afuera" in hist[0]["nota"]

    # el mismo archivo otra vez: no duplica
    r = adm.post("/api/importar/faltas", files=arch(), data={"confirmar": "1"}, headers=H)
    assert [f["resultado"] for f in r.json()["filas"]][:2] == ["omitida", "omitida"] and not r.json()["confirmado"]
    assert adm.get("/api/importar/historial").json()[0]["creadas"] == 2

    # archivo que no es la planilla
    r = adm.post("/api/importar/faltas", files={"archivo": ("x.csv", b"a;b\n1;2\n", "text/csv")}, data={"confirmar": "0"}, headers=H)
    assert r.status_code == 400 and "columnas" in r.json()["detail"]


def _xlsx(estado_f2="Pendiente"):
    import datetime as dt
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = "Leeme"
    hojas = {
        "Catálogo": [["Código", "Rubro", "Falta", "Qué observar", "Norma", "Artículo", "Penalidad", "Detectable en recorrido", "Visible en recorrido", "Módulo", "Activo"],
                     [f"T{SUF[:4]}".upper(), f"Rubro {SUF}", "Falta de la planilla", "", "", "", "", "Si", "Sí", "Infracción", "Sí"]],
        "Visitas": [["N° visita", "Fecha", "U.F.", "Sector", "Origen", "Contacto", "Observación", "Origen del dato", "Sin novedad"],
                    ["V-9001", dt.datetime(2026, 10, 1, 4), 1200, "Sector III", "Recorrido de inspección / Reclamo de vecino", "No había nadie", "obs", "x", None],
                    ["V-9002", None, 1201, "Sector III", "Revisión de caso", None, None, "x", None]],
        "Hallazgos": [["N° hallazgo", "N° visita", "Fecha", "U.F.", "Pilar", "Sector", "Rubro", "Código", "Tipo de falta", "Estado", "Fecha de revisión",
                       "Foto tomada", "Derivado a Comisión", "Observación", "Reiterancia", "Fecha de cierre", "Origen del dato"],
                      ["F-9001", "V-9001", dt.datetime(2026, 10, 1, 4), 1200, 1200, "", "", f"T{SUF[:4]}".upper(), "", "Notificado/Intimado", None, "Sí", "Sí", "o1", 1, None, ""],
                      ["F-9002", "V-9002", None, 1201, 1201, "", "", "EJ-01", "", estado_f2, dt.datetime(2026, 10, 9, 12), "No", None, None, 0, None, ""],
                      ["F-9003", "V-9999", dt.datetime(2026, 10, 1), 1200, 1200, "", "", "EJ-01", "", "Pendiente", None, None, None, None, 0, None, ""]],
        "Historial": [["Fecha", "N° hallazgo", "U.F.", "Cambio", "N° visita", "Nota"],
                      [dt.datetime(2026, 10, 1, 4), "F-9001", 1200, "Alta. Estado: Pendiente", "V-9001", None],
                      [dt.datetime(2026, 10, 5, 12), "F-9002", 1201, "Alta. Estado: Pendiente", None, None],
                      [dt.datetime(2026, 10, 6, 12), "O-0001", 1201, "Observado", None, None]],
        "Marcas": [["N° marca", "Fecha", "Grupo", "Capa", "Tipo", "Falta", "Forma", "Lugar", "Sector", "Estado", "Fecha de revisión", "Observación",
                    "Fecha de cierre", "Geometría", "Origen del dato"],
                   ["M-9001", dt.datetime(2026, 10, 9, 12), "Áreas comunes", "Calles", "Bache", "Bache", "Punto", "Calle; Zanja / cuneta", "Sector III",
                    "Relevado", dt.datetime(2026, 10, 30, 12), "Bache frente a la 1200", None, "[[2553,2592]]", "Herramienta"]],
        "Observaciones": [["N° observación"], ["O-0001"]],
    }
    for nombre, filas_ in hojas.items():
        ws = wb.create_sheet(nombre)
        for r in filas_:
            ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_importar_planilla_construcciones(usuarios):
    adm = cliente(usuarios["admin"])
    sube = lambda raw, conf: adm.post("/api/importar/faltas", files={"archivo": ("Base de datos.xlsx", raw, "application/octet-stream")},
                                      data={"confirmar": "1" if conf else "0"}, headers=H)
    with conexion() as c:
        ya = fila(c, "SELECT COUNT(*) n FROM importacion_item WHERE nro_origen='F-9001'")["n"]
    r = sube(_xlsx(), False)
    assert r.status_code == 200, r.text
    j = r.json()
    if ya:                                   # base de desarrollo reutilizada: ya se importó en una corrida anterior
        return
    hojas = {h["hoja"]: h for h in j["hojas"]}
    assert not j["confirmado"] and hojas["Visitas"]["nuevas"] == 2 and hojas["Hallazgos"]["nuevas"] == 2 and hojas["Hallazgos"]["errores"] == 1
    assert hojas["Marcas"]["nuevas"] == 1 and hojas["Historial"]["nuevas"] == 2 and any(x["hoja"] == "Observaciones" for x in j["no_importa"])
    with conexion() as c:
        assert fila(c, "SELECT COUNT(*) n FROM importacion_item WHERE nro_origen='F-9001'")["n"] == 0    # la revisión no guarda

    j = sube(_xlsx(), True).json()
    assert j["confirmado"] and j["totales"]["nuevas"] == 8
    est = adm.get("/api/estado").json()
    with conexion() as c:
        f1 = fila(c, "SELECT nro_registro FROM importacion_item WHERE nro_origen='F-9001' AND nro_registro LIKE 'F-%%'")["nro_registro"]
        f2 = fila(c, "SELECT nro_registro FROM importacion_item WHERE nro_origen='F-9002' AND nro_registro LIKE 'F-%%'")["nro_registro"]
        m1 = fila(c, "SELECT nro_registro FROM importacion_item WHERE nro_origen='M-9001'")["nro_registro"]
    h = {x["n"]: x for x in est["hallazgos"]}
    assert h[f1]["estado"] == "Notificado/Intimado" and h[f1]["reit"] == 1 and h[f1]["fotoTomada"]
    assert h[f2]["fecha"] == "2026-10-05"              # sin fecha en la planilla: estimada por su historial
    v1 = next(v for v in est["visitas"] if v["n"] == h[f1]["visita"])
    assert v1["origen"] == "Recorrido de inspección" and v1["contacto"] == "No había nadie"
    m = next(x for x in est["marcas"] if x["n"] == m1)
    assert m["lugar"] == "Calle" and m["geo"] == [[2553, 2592]] and m["lat"] is not None

    # versión más nueva de la planilla: se actualiza el estado, sin duplicar nada
    j = sube(_xlsx("Resuelto"), True).json()
    assert j["totales"]["nuevas"] == 0 and j["totales"]["actualizadas"] == 1
    h2 = next(x for x in adm.get("/api/estado").json()["hallazgos"] if x["n"] == f2)
    assert h2["estado"] == "Resuelto" and h2["cierre"] == "2026-10-09" and h2["revision"] is None


def test_red_y_recorrido(usuarios):
    ins, adm, con = cliente(usuarios["inspector"]), cliente(usuarios["admin"]), cliente(usuarios["consulta"])
    red = ins.get("/api/red").json()
    assert len(red["tramos"]) > 100 and red["inicio"]["x"]
    assert con.get("/api/red").status_code == 403
    # paradas: tres puntos sobre calles conocidas del plano (centros de tramos)
    calles = [t for t in red["tramos"] if t["tipo"] == "calle" and len(t["geo"]) > 2]
    pts = [calles[k * len(calles) // 4]["geo"][1] for k in range(4)]
    par = [{"tipo": "uf", "ref": str(1000 + k), "x": x, "y": y} for k, (x, y) in enumerate(pts)]
    r = ins.post("/api/itinerarios/calcular", json={"modo": "vehiculo", "paradas": par}, headers=H)
    assert r.status_code == 200, r.text
    j = r.json()
    assert len(j["paradas"]) == 4 and len(j["piernas"]) == 4 and j["km"] > 0
    assert {p["ref"] for p in j["paradas"]} == {p["ref"] for p in par}
    # el orden óptimo no es más largo que recorrerlas en el orden cargado
    fijo = ins.post("/api/itinerarios/calcular", json={"modo": "vehiculo", "paradas": [dict(p, fijada=True) for p in par]}, headers=H).json()
    assert [p["ref"] for p in fijo["paradas"]] == [p["ref"] for p in par] and j["km"] <= fijo["km"] + 1e-6
    vuelta = ins.post("/api/itinerarios/calcular", json={"modo": "pie", "paradas": par, "volver": True}, headers=H).json()
    assert len(vuelta["piernas"]) == 5
    assert ins.post("/api/itinerarios/calcular", json={"modo": "vehiculo", "paradas": []}, headers=H).status_code == 400
    assert con.post("/api/itinerarios/calcular", json={"modo": "vehiculo", "paradas": par}, headers=H).status_code == 403

    # guardar, saltear, recalcular y terminar
    it = ins.post("/api/itinerarios", json={"modo": "vehiculo", "paradas": par}, headers=H).json()
    assert it["estado"] == "activo" and len(it["paradas"]) == 4 and ins.get("/api/itinerarios/actual").json()["id_itinerario"] == it["id_itinerario"]
    iid = it["id_itinerario"]
    it = ins.post(f"/api/itinerarios/{iid}/paradas/1", json={"estado": "hecha"}, headers=H).json()
    assert it["hechas"] == 1
    it = ins.post(f"/api/itinerarios/{iid}/recalcular", json={}, headers=H).json()
    assert it["paradas"][0]["estado"] == "hecha" and [p["estado"] for p in it["paradas"][1:]] == ["pendiente"] * 3
    otro = cliente(usuarios["supervisor"])
    assert otro.get(f"/api/itinerarios/{iid}").status_code == 200          # el supervisor puede ver los recorridos
    assert ins.post(f"/api/itinerarios/{iid}/terminar", json={}, headers=H).json()["estado"] == "terminado"
    assert ins.get("/api/itinerarios/actual").json() is None

    # editor de red: solo admin; un tramo cerrado deja de usarse
    t = calles[len(calles) // 2 + 3]          # un tramo sin paradas encima: cerrarlo solo puede alargar el recorrido
    assert ins.put(f"/api/red/tramos/{t['id']}", json={"tipo": "cerrado"}, headers=H).status_code == 403
    try:
        assert adm.put(f"/api/red/tramos/{t['id']}", json={"tipo": "cerrado"}, headers=H).status_code == 200
        r = ins.post("/api/itinerarios/calcular", json={"modo": "vehiculo", "paradas": par}, headers=H)
        assert r.status_code in (200, 400)
        if r.status_code == 200:
            assert r.json()["km"] >= j["km"] - 1e-6
    finally:
        adm.put(f"/api/red/tramos/{t['id']}", json={"tipo": t["tipo"], "sentido": t["sentido"]}, headers=H)
        with conexion() as c:
            ejecutar(c, "UPDATE red_tramo SET revisado=%s, modificado=NULL, id_usuario=NULL WHERE id_tramo=%s", (t["revisado"], t["id"]))
    assert adm.put("/api/red/inicio", json={"x": 99999, "y": 0}, headers=H).status_code == 400


def test_ficha_pdf(usuarios):
    import json
    from pypdf import PdfReader
    ins, con = cliente(usuarios["inspector"]), cliente(usuarios["consulta"])
    with conexion() as c:
        f = str(fila(c, "SELECT CURDATE() d")["d"])
    d = {"uf": 1300, "fecha": f, "origen": "Recorrido de inspección", "contacto": "No había nadie",
         "faltas": [{"codigo": "EJ-02", "estado": "Pendiente", "revision": "2099-01-01", "obs": "Cerco caído → avisado"}]}
    r = ins.post("/api/visitas", data={"datos": json.dumps(d)},
                 files=[("f_0", ("a.jpg", jpeg(800, 600), "image/jpeg")), ("f_0", ("b.jpg", jpeg(600, 800), "image/jpeg"))], headers=H)
    nf = r.json()["faltas"][0]
    r = con.get(f"/api/faltas/{nf}/pdf")                   # el de consulta también puede descargarla
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert f'Falta {nf} UF 1300.pdf' in r.headers["content-disposition"]
    pdf = PdfReader(io.BytesIO(r.content))
    texto = " ".join(p.extract_text() for p in pdf.pages)
    assert "Ficha de falta" in texto and nf in texto and "Cerco ca" in texto and "HISTORIAL" in texto.replace(" ", "")
    assert len(pdf.attachments) == 2
    assert TestClient(app).get(f"/api/faltas/{nf}/pdf").status_code == 401
    assert con.get("/api/faltas/F-99999/pdf").status_code == 404
