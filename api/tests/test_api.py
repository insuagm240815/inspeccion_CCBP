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
