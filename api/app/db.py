"""Conexión a MariaDB y utilidades comunes."""
import datetime as dt
import decimal
import os
from contextlib import contextmanager
from zoneinfo import ZoneInfo

import pymysql
import pymysql.cursors

TZ = ZoneInfo("America/Argentina/Buenos_Aires")

_CFG = dict(
    host=os.environ.get("DB_HOST", "db"),
    port=int(os.environ.get("DB_PORT", "3306")),
    user=os.environ.get("DB_USER", "inspeccion"),
    password=os.environ.get("DB_PASSWORD", ""),
    database=os.environ.get("DB_NAME", "inspeccion_ccbp"),
    charset="utf8mb4",
    autocommit=False,
    cursorclass=pymysql.cursors.DictCursor,
)


@contextmanager
def conexion():
    """Una conexión por operación. Commit si todo sale bien, rollback si algo falla."""
    c = pymysql.connect(**_CFG)
    try:
        c.query("SET time_zone = '-03:00'")
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def filas(c, sql, args=None):
    with c.cursor() as cur:
        cur.execute(sql, args)
        return [_limpiar(r) for r in cur.fetchall()]


def fila(c, sql, args=None):
    with c.cursor() as cur:
        cur.execute(sql, args)
        r = cur.fetchone()
        return _limpiar(r) if r else None


def ejecutar(c, sql, args=None):
    with c.cursor() as cur:
        cur.execute(sql, args)
        return cur.lastrowid


def _limpiar(r):
    out = {}
    for k, v in r.items():
        if isinstance(v, (dt.datetime,)):
            v = v.isoformat(timespec="seconds")
        elif isinstance(v, dt.date):
            v = v.isoformat()
        elif isinstance(v, decimal.Decimal):
            v = float(v)
        out[k] = v
    return out


def hoy() -> dt.date:
    return dt.datetime.now(TZ).date()


def siguiente(c, prefijo: str) -> str:
    """Próximo número (V-0001, F-0001, P-0001). FOR UPDATE bloquea la fila hasta el commit:
    dos inspectores guardando a la vez nunca obtienen el mismo número."""
    r = fila(c, "SELECT ultimo FROM secuencia WHERE prefijo=%s FOR UPDATE", (prefijo,))
    n = (r["ultimo"] if r else 0) + 1
    ejecutar(c, "UPDATE secuencia SET ultimo=%s WHERE prefijo=%s", (n, prefijo))
    return f"{prefijo}-{n:04d}"
