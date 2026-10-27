"""Ficha de falta en PDF (formato de Inspección técnica): datos, resumen, fotos, historial y firma.
Las fotos van además adjuntas al PDF en tamaño completo (panel de adjuntos del visor)."""
import datetime as dt
import io
import os
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (Flowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from . import fotos as F
from .db import fila, filas, hoy

CLUB = "Country Club Atlético Banco de la Provincia de Buenos Aires"
LOGO = os.path.join(os.path.dirname(__file__), "recursos", "logo.jpg")
VERDE, VERDE_CLARO, ROJO = colors.HexColor("#4E8A2E"), colors.HexColor("#EEF2EB"), colors.HexColor("#D93A32")
GRIS, LINEA, TINTA = colors.HexColor("#6B7280"), colors.HexColor("#D9DDD5"), colors.HexColor("#1F2328")
COLOR_ESTADO = {"Pendiente": "#C98A06", "Aviso verbal": "#D97706", "Aviso por folleto": "#D97706",
                "Derivado a Comisión": "#D93A32", "Notificado/Intimado": "#A61B1B", "En proceso de resolución": "#2F6FCE",
                "Resuelto": "#3F8F4F", "Verificado sin falta": "#3F8F4F"}
CERRADOS = ("Resuelto", "Verificado sin falta")
ANCHO = A4[0] - 40 * mm


def t(s):
    """Texto seguro para las fuentes estándar del PDF (WinAnsi) y para Paragraph."""
    s = "" if s is None else str(s)
    s = s.replace("→", "»").replace("←", "«").replace("✓", "OK")
    return escape(s.encode("cp1252", "replace").decode("cp1252"))


def fmt(d):
    if not d:
        return "—"
    d = d if isinstance(d, (dt.date, dt.datetime)) else dt.date.fromisoformat(str(d)[:10])
    return d.strftime("%d/%m/%Y")


def _d(d):
    return d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)[:10])


E = {
    "club": ParagraphStyle("club", fontName="Helvetica-Bold", fontSize=6.8, textColor=GRIS, leading=9),
    "tit": ParagraphStyle("tit", fontName="Helvetica-Bold", fontSize=21, textColor=VERDE, leading=25),
    "sub": ParagraphStyle("sub", fontName="Helvetica", fontSize=9, textColor=GRIS, leading=11),
    "lab": ParagraphStyle("lab", fontName="Helvetica", fontSize=8, textColor=GRIS, leading=10),
    "val": ParagraphStyle("val", fontName="Helvetica-Bold", fontSize=9.5, textColor=TINTA, leading=12),
    "barra": ParagraphStyle("barra", fontName="Helvetica", fontSize=9.5, textColor=TINTA, leading=12),
    "res_t": ParagraphStyle("res_t", fontName="Helvetica-Bold", fontSize=11, textColor=VERDE, leading=14, spaceAfter=3),
    "bul": ParagraphStyle("bul", fontName="Helvetica", fontSize=9.5, textColor=TINTA, leading=13, leftIndent=12, bulletIndent=0),
    "sec": ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=8, textColor=VERDE, leading=10, spaceBefore=10, spaceAfter=5),
    "falta": ParagraphStyle("falta", fontName="Helvetica-Bold", fontSize=11, textColor=TINTA, leading=14),
    "norma": ParagraphStyle("norma", fontName="Helvetica", fontSize=8, textColor=GRIS, leading=10),
    "k": ParagraphStyle("k", fontName="Helvetica", fontSize=9, textColor=GRIS, leading=12),
    "v": ParagraphStyle("v", fontName="Helvetica", fontSize=9, textColor=TINTA, leading=12),
    "pie": ParagraphStyle("pie", fontName="Helvetica", fontSize=7.5, textColor=GRIS, leading=9),
    "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=8.5, textColor=VERDE, leading=11),
    "td": ParagraphStyle("td", fontName="Helvetica", fontSize=8.5, textColor=TINTA, leading=11),
    "nota": ParagraphStyle("nota", fontName="Helvetica", fontSize=8.5, textColor=GRIS, leading=11),
    "firma": ParagraphStyle("firma", fontName="Helvetica", fontSize=8.5, textColor=GRIS, leading=11, alignment=1),
}
ROMBO = '<img src="%s" width="6" height="6" valign="1"/>' % os.path.join(os.path.dirname(__file__), "recursos", "rombo.png")


class Raya(Flowable):
    """Línea verde con el extremo rojo, como en el encabezado del formato."""
    def __init__(self, ancho):
        super().__init__()
        self.width, self.height = ancho, 3

    def draw(self):
        c = self.canv
        c.setLineWidth(2.2)
        c.setStrokeColor(VERDE)
        c.line(0, 1, self.width * 0.87, 1)
        c.setStrokeColor(ROJO)
        c.line(self.width * 0.87, 1, self.width, 1)


def _lienzo(n_falta):
    class Lienzo(rl_canvas.Canvas):
        """Pie con "Página x de y" y encabezado reducido desde la página 2."""
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._paginas = []

        def showPage(self):
            self._paginas.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._paginas)
            for p in self._paginas:
                self.__dict__.update(p)
                self._decorar(total)
                super().showPage()
            super().save()

        def _decorar(self, total):
            w, h = A4
            self.setFont("Helvetica", 7.5)
            self.setFillColor(GRIS)
            self.setStrokeColor(LINEA)
            self.setLineWidth(0.6)
            self.line(20 * mm, 16 * mm, w - 20 * mm, 16 * mm)
            self.drawString(20 * mm, 12 * mm, f"{CLUB} · Inspección técnica · Generado el {fmt(hoy())}")
            self.setFont("Helvetica", 8)
            self.drawRightString(w - 20 * mm, 12 * mm, f"Página {self._pageNumber} de {total}")
            if self._pageNumber > 1:
                self.setFont("Helvetica", 7.5)
                self.drawString(20 * mm, h - 13 * mm, f"{CLUB} · Inspección técnica · Ficha de falta {n_falta}")
                self.line(20 * mm, h - 15 * mm, w - 20 * mm, h - 15 * mm)
    return Lienzo


def datos(c, n):
    h = fila(c, """SELECT h.*, v.nro_uf uf, v.origen, s.nombre sector, cf.falta, cf.norma, cf.articulo, cf.penalidad, r.nombre rubro
                   FROM hallazgo h JOIN visita v ON v.nro_visita=h.nro_visita
                   JOIN unidad_funcional u ON u.nro_uf=v.nro_uf JOIN sector s ON s.id_sector=u.id_sector
                   JOIN catalogo_falta cf ON cf.codigo=h.codigo JOIN rubro r ON r.id_rubro=cf.id_rubro
                   WHERE h.nro_hallazgo=%s""", (n,))
    if not h:
        return None
    h["grupo"] = [r["nro_uf"] for r in filas(c, """SELECT DISTINCT b.nro_uf FROM uf_pilar a JOIN uf_pilar b ON b.nro_pilar=a.nro_pilar
                                                   WHERE a.nro_uf=%s ORDER BY b.nro_uf""", (h["uf"],))]
    h["fotos"] = filas(c, "SELECT nro_foto, momento, fecha, nro_visita, archivo FROM foto WHERE nro_registro=%s ORDER BY nro_foto", (n,))
    h["historial"] = filas(c, "SELECT fecha, cambio, nota, nro_visita FROM historial WHERE nro_registro=%s ORDER BY id_historial", (n,))
    return h


def _foto(rel, ancho, alto):
    """Versión liviana para la página (la original va adjunta)."""
    try:
        with PILImage.open(F.ruta(rel)) as im:
            im = im.convert("RGB")
            w, hh = im.size
            im.thumbnail((900, 900))
            b = io.BytesIO()
            im.save(b, "JPEG", quality=78)
    except Exception:
        return None
    b.seek(0)
    k = min(ancho / w, alto / hh)
    return Image(b, width=w * k, height=hh * k)


def generar(h, base_url):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=22 * mm,
                            title=f"Ficha de falta {h['nro_hallazgo']}", author="Inspección técnica", creator="Inspección CCBP")
    n = h["nro_hallazgo"]
    unif = len(h["grupo"]) > 1
    uf_txt = f"{h['uf']}" + (f" (unificada: {' y '.join(str(x) for x in h['grupo'])})" if unif else "")
    abierta = h["estado"] not in CERRADOS
    det = _d(h["fecha"])
    st = []

    # encabezado
    logo = Image(LOGO, width=17 * mm, height=20.4 * mm) if os.path.exists(LOGO) else Spacer(17 * mm, 20 * mm)
    titulo = [Paragraph(t(CLUB.upper()), E["club"]), Spacer(1, 2), Paragraph("Ficha de falta", E["tit"]), Paragraph("Inspección técnica", E["sub"])]
    datos_doc = Table([[Paragraph("Emitido", E["lab"]), Paragraph(fmt(hoy()), E["val"])],
                       [Paragraph("N°", E["lab"]), Paragraph(t(n), E["val"])]], colWidths=[14 * mm, 36 * mm])
    datos_doc.setStyle(TableStyle([("LINEBELOW", (1, 0), (1, -1), 0.6, LINEA), ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 5)]))
    enc = Table([[logo, titulo, datos_doc]], colWidths=[21 * mm, ANCHO - 21 * mm - 52 * mm, 52 * mm])
    enc.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    st += [enc, Spacer(1, 6), Raya(ANCHO), Spacer(1, 8)]

    barra = Table([[Paragraph(f"<b>U.F.</b>&nbsp; {t(uf_txt)} &nbsp;&nbsp;&nbsp;&nbsp; <b>Sector</b>&nbsp; {t(str(h['sector']).replace('Sector ', ''))}"
                              f" &nbsp;&nbsp;&nbsp;&nbsp; <b>Falta</b>&nbsp; {t(n)}", E["barra"])]], colWidths=[ANCHO])
    barra.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), VERDE_CLARO), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    st += [barra, Spacer(1, 8)]

    # resumen
    hoy_ = hoy()
    puntos = [f"Estado actual: {h['estado']}."]
    if abierta:
        dias = (hoy_ - det).days
        puntos.append(f"Abierta hace {dias} día{'s' if dias != 1 else ''} (detectada el {fmt(det)}).")
        puntos.append(f"Próxima revisión: {fmt(h['fecha_revision'])}." if h["fecha_revision"] else "Próxima revisión: sin fecha.")
    else:
        cierre = _d(h["fecha_cierre"]) if h["fecha_cierre"] else None
        puntos.append(f"Cerrada el {fmt(cierre)}" + (f", {(cierre - det).days} días después de detectada." if cierre else "."))
    puntos.append(f"Derivada a Comisión: {'Sí' if h['derivado_comision'] else 'No'}.")
    if h["reiterancia"]:
        puntos.append(f"Reiterancia: {h['reiterancia']}.")
    res = [Paragraph("En resumen", E["res_t"])] + [Paragraph(ROMBO + "&nbsp;&nbsp;" + t(p), E["bul"]) for p in puntos]
    caja = Table([[res]], colWidths=[ANCHO])
    caja.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), VERDE_CLARO), ("LINEBEFORE", (0, 0), (0, -1), 3.5, VERDE),
                              ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    st += [caja]

    # falta
    st.append(Paragraph("F A L T A", E["sec"]))
    norma = " · ".join(x for x in (h["norma"], f"art. {h['articulo']}" if h["articulo"] else None, h["penalidad"]) if x)
    col = COLOR_ESTADO.get(h["estado"], "#6B7280")
    from reportlab.pdfbase.pdfmetrics import stringWidth
    badge = Table([[Paragraph(f'<font color="white"><b>{t(h["estado"])}</b></font>', ParagraphStyle("b", fontName="Helvetica", fontSize=7.5, leading=9))]],
                  colWidths=[stringWidth(h["estado"], "Helvetica-Bold", 7.5) + 10])
    badge.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(col)), ("LEFTPADDING", (0, 0), (-1, -1), 4),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    badge.hAlign = "LEFT"
    fb = [Paragraph(f"{ROMBO}&nbsp; {t(h['codigo'])} {t(h['falta'])}", E["falta"])]
    if norma:
        fb.append(Paragraph(t(norma), E["norma"]))
    fb += [Spacer(1, 2), badge]
    caja = Table([[fb]], colWidths=[ANCHO])
    caja.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINEA), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                              ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    st += [caja, Spacer(1, 6)]
    filas_det = [("U.F.", uf_txt), ("Sector", h["sector"]), ("Rubro", h["rubro"]),
                 ("Detectada", f"{fmt(det)} · visita {h['nro_visita']} ({h['origen']})")]
    if abierta:
        filas_det.append(("Próxima revisión", fmt(h["fecha_revision"])))
    else:
        filas_det.append(("Cierre", fmt(h["fecha_cierre"])))
    filas_det += [("Reiterancia", h["reiterancia"]), ("Derivada a Comisión", "Sí" if h["derivado_comision"] else "No"),
                  ("Foto tomada", "Sí" if h["foto_tomada"] else "No"), ("Observación", h["observacion"] or "—")]
    tab = Table([[Paragraph(t(k), E["k"]), Paragraph(t(v), E["v"])] for k, v in filas_det], colWidths=[38 * mm, ANCHO - 38 * mm])
    tab.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, LINEA), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    st.append(tab)

    # fotos, de a dos por fila
    fs = h["fotos"]
    if fs:
        st.append(Paragraph(f"F O T O S &nbsp;({len(fs)})", E["sec"]))
        celdas = []
        cw = (ANCHO - 6 * mm) / 2
        for k, f in enumerate(fs, 1):
            img = _foto(f["archivo"], cw - 2 * mm, 62 * mm)
            marco = Table([[img or Paragraph("(foto no disponible)", E["nota"])]], colWidths=[cw], rowHeights=[64 * mm])
            marco.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINEA), ("BACKGROUND", (0, 0), (-1, -1), VERDE_CLARO),
                                       ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
            pie = Table([[Paragraph(t(f"Foto {k} · {f['momento']} · {fmt(f['fecha'])}" + (f" · {f['nro_visita']}" if f["nro_visita"] else "")), E["pie"]),
                          Paragraph(f'<a href="{escape(base_url)}/api/fotos/{t(f["nro_foto"])}" color="#4E8A2E"><u><b>Descargar foto</b></u></a>',
                                    ParagraphStyle("lk", parent=E["pie"], alignment=TA_RIGHT))]], colWidths=[cw * 0.68, cw * 0.32])
            pie.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 2)]))
            celdas.append([marco, pie])
        filas_f = [celdas[i:i + 2] for i in range(0, len(celdas), 2)]
        for par in filas_f:
            fila_t = Table([[par[0], par[1] if len(par) > 1 else ""]], colWidths=[cw + 3 * mm, cw + 3 * mm])
            fila_t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            st.append(fila_t)

    # historial
    hs = h["historial"]
    st.append(Paragraph(f"H I S T O R I A L &nbsp;({len(hs)})", E["sec"]))
    datos_h = [[Paragraph(x, E["th"]) for x in ("Fecha", "Movimiento", "Nota", "Visita")]]
    for x in hs:
        datos_h.append([Paragraph(fmt(x["fecha"]), E["td"]), Paragraph(t(x["cambio"]), E["td"]), Paragraph(t(x["nota"] or ""), E["td"]),
                        Paragraph(t(x["nro_visita"] or ""), E["td"])])
    if not hs:
        datos_h.append([Paragraph("—", E["td"]), Paragraph("Sin movimientos.", E["td"]), "", ""])
    th = Table(datos_h, colWidths=[22 * mm, 68 * mm, ANCHO - 22 * mm - 68 * mm - 22 * mm, 22 * mm], repeatRows=1)
    th.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), VERDE_CLARO), ("BOX", (0, 0), (-1, -1), 0.6, LINEA),
                            ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINEA), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    st.append(th)

    if fs:
        nota = Table([[Paragraph(t(f"Cada foto tiene su link \"Descargar foto\": abre la foto en la app de inspección (hay que iniciar sesión). "
                                   f"Además, {'la foto va adjunta' if len(fs) == 1 else f'las {len(fs)} fotos van adjuntas'} a este PDF (JPG): en la compu "
                                   "se descargan desde el panel de adjuntos del visor (ícono del clip)."), E["nota"])]], colWidths=[ANCHO])
        nota.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), VERDE_CLARO), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                                  ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        st += [Spacer(1, 10), nota]
    firma = Table([["", [Spacer(1, 26), Paragraph("Inspección técnica · firma y aclaración", E["firma"])]]],
                  colWidths=[ANCHO - 72 * mm, 72 * mm])
    firma.setStyle(TableStyle([("LINEABOVE", (1, 0), (1, 0), 0.8, VERDE), ("TOPPADDING", (1, 0), (1, 0), 3)]))
    st += [Spacer(1, 30), KeepTogether([firma])]

    doc.build(st, canvasmaker=_lienzo(n))

    # adjuntar las fotos en tamaño completo y fijar metadatos
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(buf.getvalue())))
    for k, f in enumerate(fs, 1):
        try:
            with open(F.ruta(f["archivo"]), "rb") as fh:
                w.add_attachment(f"{n}_foto{k:02d}.jpg", fh.read())
        except Exception:
            pass
    w.add_metadata({"/Title": f"Ficha de falta {n}", "/Producer": "Herramienta de inspeccion CCBP"})
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()
