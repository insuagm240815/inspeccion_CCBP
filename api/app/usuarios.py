"""Administración de usuarios desde la consola del servidor.

  docker compose exec api python -m app.usuarios crear  --usuario mperez --nombre "María Pérez" --rol inspector
  docker compose exec api python -m app.usuarios clave  --usuario mperez
  docker compose exec api python -m app.usuarios baja   --usuario mperez
  docker compose exec api python -m app.usuarios listar
"""
import argparse
import getpass
import os
import sys

from .db import conexion, ejecutar, fila, filas
from .seguridad import hash_clave


def _pedir_clave():
    # Para automatizar (Codespaces, pruebas): la clave puede venir en la variable CLAVE_NUEVA.
    if os.environ.get("CLAVE_NUEVA"):
        return hash_clave(os.environ["CLAVE_NUEVA"])
    a = getpass.getpass("Clave (mínimo 10 caracteres): ")
    b = getpass.getpass("Repetila: ")
    if a != b:
        sys.exit("Las claves no coinciden.")
    return hash_clave(a)


def main():
    p = argparse.ArgumentParser(prog="usuarios")
    s = p.add_subparsers(dest="cmd", required=True)
    c = s.add_parser("crear"); c.add_argument("--usuario", required=True); c.add_argument("--nombre", required=True)
    c.add_argument("--rol", choices=["inspector", "supervisor", "admin"], default="inspector")
    s.add_parser("clave").add_argument("--usuario", required=True)
    s.add_parser("baja").add_argument("--usuario", required=True)
    s.add_parser("alta").add_argument("--usuario", required=True)
    s.add_parser("listar")
    a = p.parse_args()
    usuario = getattr(a, "usuario", "") and a.usuario.strip().lower()
    try:
        with conexion() as cx:
            if a.cmd == "crear":
                if fila(cx, "SELECT 1 x FROM usuario WHERE usuario=%s", (usuario,)):
                    sys.exit("Ese usuario ya existe.")
                ejecutar(cx, "INSERT INTO usuario (usuario,nombre,rol,clave_hash) VALUES (%s,%s,%s,%s)",
                         (usuario, a.nombre.strip(), a.rol, _pedir_clave()))
                print(f"Usuario {usuario} creado con rol {a.rol}.")
            elif a.cmd == "clave":
                ejecutar(cx, "UPDATE usuario SET clave_hash=%s WHERE usuario=%s", (_pedir_clave(), usuario))
                ejecutar(cx, "DELETE s FROM sesion s JOIN usuario u ON u.id_usuario=s.id_usuario WHERE u.usuario=%s", (usuario,))
                print("Clave cambiada. Se cerraron sus sesiones abiertas.")
            elif a.cmd in ("baja", "alta"):
                ejecutar(cx, "UPDATE usuario SET activo=%s WHERE usuario=%s", (a.cmd == "alta", usuario))
                if a.cmd == "baja":
                    ejecutar(cx, "DELETE s FROM sesion s JOIN usuario u ON u.id_usuario=s.id_usuario WHERE u.usuario=%s", (usuario,))
                print(f"Usuario {usuario}: {'activo' if a.cmd == 'alta' else 'dado de baja'}.")
            else:
                for r in filas(cx, "SELECT usuario, nombre, rol, activo, creado FROM usuario ORDER BY usuario"):
                    print(f"{r['usuario']:<16} {r['rol']:<11} {'activo' if r['activo'] else 'baja  '}  {r['nombre']}")
    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
