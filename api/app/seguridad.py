"""Sesiones, roles, protección CSRF y límite de intentos de login."""
import hashlib
import os
import secrets
import threading
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, Request

from .db import conexion, ejecutar, fila

PH = PasswordHasher()
SESION_HORAS = int(os.environ.get("SESION_HORAS", "12"))
COOKIE = "ccbp_sid"
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") == "1"
NIVEL = {"inspector": 1, "supervisor": 2, "admin": 3}
_HASH_FALSO = PH.hash(secrets.token_hex(16))   # para que un usuario inexistente tarde lo mismo


def _sha(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def ip_de(req: Request) -> str:
    # nginx pone X-Real-IP; detrás de Cloudflare Tunnel, CF-Connecting-IP
    return (req.headers.get("cf-connecting-ip") or req.headers.get("x-real-ip")
            or (req.client.host if req.client else ""))[:45]


# ───────── límite de intentos: 8 fallidos por usuario+IP en 15 minutos ─────────
_intentos: dict[str, list[float]] = {}
_lock = threading.Lock()


def _bloqueado(clave: str) -> bool:
    ahora = time.time()
    with _lock:
        xs = [t for t in _intentos.get(clave, []) if ahora - t < 900]
        _intentos[clave] = xs
        return len(xs) >= 8


def _fallo(clave: str):
    with _lock:
        _intentos.setdefault(clave, []).append(time.time())


def _registrar(usuario: str, ip: str, resultado: str):
    with conexion() as c:
        ejecutar(c, "INSERT INTO acceso_log (usuario,ip,resultado) VALUES (%s,%s,%s)", (usuario, ip, resultado))


def login(usuario: str, clave: str, ip: str) -> str:
    usuario = (usuario or "").strip().lower()[:40]
    k = usuario + "|" + ip
    if _bloqueado(k):
        _registrar(usuario, ip, "bloqueado")
        raise HTTPException(429, "Demasiados intentos. Esperá 15 minutos.")
    with conexion() as c:
        u = fila(c, "SELECT id_usuario, clave_hash, activo FROM usuario WHERE usuario=%s", (usuario,))
    try:
        ok = PH.verify(u["clave_hash"] if u else _HASH_FALSO, clave or "")
    except (VerifyMismatchError, InvalidHashError):
        ok = False
    if not u or not ok:
        _fallo(k)
        _registrar(usuario, ip, "clave")
        raise HTTPException(401, "Usuario o clave incorrectos.")
    if not u["activo"]:
        _registrar(usuario, ip, "inactivo")
        raise HTTPException(401, "Usuario o clave incorrectos.")
    with conexion() as c:
        if PH.check_needs_rehash(u["clave_hash"]):
            ejecutar(c, "UPDATE usuario SET clave_hash=%s WHERE id_usuario=%s", (PH.hash(clave), u["id_usuario"]))
        token = secrets.token_urlsafe(32)
        ejecutar(c, "DELETE FROM sesion WHERE expira < NOW()")
        ejecutar(c, "INSERT INTO sesion (token_hash,id_usuario,expira,ip) VALUES (%s,%s,NOW() + INTERVAL %s HOUR,%s)",
                 (_sha(token), u["id_usuario"], SESION_HORAS, ip))
        ejecutar(c, "INSERT INTO acceso_log (usuario,ip,resultado) VALUES (%s,%s,'ok')", (usuario, ip))
        return token


def logout(token: str):
    if token:
        with conexion() as c:
            ejecutar(c, "DELETE FROM sesion WHERE token_hash=%s", (_sha(token),))


def usuario_de(req: Request) -> dict:
    token = req.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Iniciá sesión.")
    with conexion() as c:
        u = fila(c, """SELECT u.id_usuario, u.usuario, u.nombre, u.rol FROM sesion s
                       JOIN usuario u ON u.id_usuario = s.id_usuario
                       WHERE s.token_hash=%s AND s.expira > NOW() AND u.activo""", (_sha(token),))
    if not u:
        raise HTTPException(401, "La sesión venció. Volvé a ingresar.")
    return u


def exigir(req: Request, rol: str = "inspector", escritura: bool = False) -> dict:
    """Valida sesión y rol. En escrituras exige el encabezado X-CCBP: un sitio ajeno no puede
    mandarlo sin pasar por CORS (que no está habilitado), así se cubre CSRF junto con SameSite=Strict."""
    if escritura and req.headers.get("x-ccbp") != "1":
        raise HTTPException(403, "Solicitud no permitida.")
    u = usuario_de(req)
    if NIVEL[u["rol"]] < NIVEL[rol]:
        raise HTTPException(403, "Tu usuario no tiene permiso para esta acción.")
    return u


def hash_clave(clave: str) -> str:
    if len(clave) < 10:
        raise ValueError("La clave tiene que tener al menos 10 caracteres.")
    return PH.hash(clave)
