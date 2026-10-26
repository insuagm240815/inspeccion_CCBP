"""Tareas al arrancar, pensadas para plataformas sin consola cómoda (Railway):
crear el usuario administrador y, opcionalmente, usuarios de prueba, a partir de variables de entorno.

  ADMIN_USUARIO / ADMIN_CLAVE  → crea el admin si todavía no existe (nunca cambia una clave existente)
  DEMO_CLAVE                   → crea inspector, consulta y supervisor de prueba con esa clave (solo entornos de prueba)
"""
import logging
import os
import threading
import time

from .db import conexion, ejecutar, fila
from .seguridad import hash_clave

log = logging.getLogger("uvicorn.error")


def _crear(usuario, nombre, rol, clave):
    with conexion() as c:
        if fila(c, "SELECT 1 e FROM usuario WHERE usuario=%s", (usuario,)):
            return False
        ejecutar(c, "INSERT INTO usuario (usuario,nombre,rol,clave_hash) VALUES (%s,%s,%s,%s)",
                 (usuario, nombre, rol, hash_clave(clave)))
        return True


def _tarea():
    admin, clave = os.environ.get("ADMIN_USUARIO", "").strip().lower(), os.environ.get("ADMIN_CLAVE", "")
    demo = os.environ.get("DEMO_CLAVE", "")
    if not (admin and clave) and not demo:
        return
    for intento in range(40):                      # la base puede tardar en estar lista
        try:
            if admin and clave and _crear(admin, "Administrador", "admin", clave):
                log.info("Usuario administrador '%s' creado.", admin)
            if demo:
                for u, n, r in (("inspector", "Inspector de prueba", "inspector"), ("consulta", "Consulta de prueba", "consulta"),
                                ("supervisor", "Supervisor de prueba", "supervisor")):
                    if _crear(u, n, r, demo):
                        log.info("Usuario de prueba '%s' creado.", u)
            return
        except ValueError as e:                      # clave demasiado corta
            log.error("No se crearon usuarios: %s", e)
            return
        except Exception as e:                       # base todavía no disponible
            if intento == 39:
                log.error("No se pudo conectar a la base para crear usuarios: %s", e)
            time.sleep(3)


def iniciar():
    threading.Thread(target=_tarea, daemon=True).start()
