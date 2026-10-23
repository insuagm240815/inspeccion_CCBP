"""Validación y guardado de fotos. Se re-codifican a JPEG: eso descarta metadatos EXIF
(incluida la ubicación del celular) y cualquier contenido que no sea imagen."""
import io
import os
import shutil

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

FOTOS_DIR = os.environ.get("FOTOS_DIR", "/data/fotos")
MAX_BYTES = 15 * 1024 * 1024
MAX_POR_ENVIO = 12
LADO = 1600
Image.MAX_IMAGE_PIXELS = 60_000_000


def procesar(datos: bytes) -> bytes:
    if not datos:
        raise HTTPException(400, "Llegó una foto vacía.")
    if len(datos) > MAX_BYTES:
        raise HTTPException(413, "Una foto pesa más de 15 MB.")
    try:
        im = Image.open(io.BytesIO(datos))
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        im.thumbnail((LADO, LADO))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=82, optimize=True)
        return out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise HTTPException(400, "Uno de los archivos no es una imagen válida.")


def guardar(nro: str, fecha_iso: str, jpeg: bytes) -> str:
    rel = os.path.join(fecha_iso[:4], fecha_iso[5:7], nro + ".jpg")
    dest = os.path.join(FOTOS_DIR, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        f.write(jpeg)
    os.replace(tmp, dest)
    return rel


def ruta(rel: str) -> str:
    p = os.path.realpath(os.path.join(FOTOS_DIR, rel))
    if not p.startswith(os.path.realpath(FOTOS_DIR) + os.sep):
        raise HTTPException(404)
    return p


def a_papelera(rel: str):
    """Las fotos de un registro borrado no se eliminan: van a _papelera para poder recuperarlas."""
    try:
        src = ruta(rel)
        dst = os.path.join(FOTOS_DIR, "_papelera", rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
    except (OSError, HTTPException):
        pass


def borrar(rel: str):
    try:
        os.remove(ruta(rel))
    except (OSError, HTTPException):
        pass
