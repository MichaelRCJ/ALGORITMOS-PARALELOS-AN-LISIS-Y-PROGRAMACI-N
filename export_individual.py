import io
from datetime import datetime
from xml.sax.saxutils import escape

import pandas as pd
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


FIELDS = (
    ("titulo", "Título"),
    ("objetivo", "Objetivo"),
    ("problema", "Problema"),
    ("metodologia", "Metodología"),
    ("tecnicas", "Técnicas"),
    ("herramientas", "Herramientas"),
    ("resultados", "Resultados"),
    ("hallazgos", "Hallazgos"),
    ("limitaciones", "Limitaciones"),
    ("contribuciones", "Contribuciones"),
    ("palabras_clave", "Palabras clave"),
    ("autores", "Autores"),
    ("anio", "Año"),
    ("doi", "DOI"),
)


def _dataframe(results):
    return pd.DataFrame([{label: article.get(key, "") for key, label in FIELDS} for article in results])


def export_individual_excel(results):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        _dataframe(results).to_excel(writer, index=False, sheet_name="Análisis individual")
    output.seek(0)
    return output


def export_individual_csv(results):
    output = io.BytesIO()
    _dataframe(results).to_csv(output, index=False, encoding="utf-8-sig")
    output.seek(0)
    return output


def export_individual_word(results):
    document = Document()
    title = document.add_heading("Análisis Individual de Artículos", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    date = document.add_paragraph(f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    date.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for index, article in enumerate(results, 1):
        document.add_heading(f"Artículo {index}: {article.get('titulo', '')}", level=1)
        for key, label in FIELDS[1:]:
            paragraph = document.add_paragraph()
            paragraph.add_run(f"{label}: ").bold = True
            paragraph.add_run(str(article.get(key, "")))

    output = io.BytesIO()
    document.save(output)
    output.seek(0)
    return output


def export_individual_pdf(results):
    output = io.BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=1.5 * cm, leftMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("IndividualTitle", parent=styles["Heading1"], fontSize=16, textColor=colors.darkblue, alignment=TA_CENTER, spaceAfter=16)
    heading_style = ParagraphStyle("ArticleHeading", parent=styles["Heading2"], fontSize=12, textColor=colors.darkred, spaceBefore=10, spaceAfter=8)
    body_style = ParagraphStyle("ArticleBody", parent=styles["BodyText"], fontSize=9, leading=12, spaceAfter=5)
    story = [Paragraph("Análisis Individual de Artículos", title_style), Paragraph(escape(f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}"), body_style)]

    for index, article in enumerate(results, 1):
        story.append(Paragraph(escape(f"Artículo {index}: {article.get('titulo', '')}"), heading_style))
        for key, label in FIELDS[1:]:
            value = escape(str(article.get(key, ""))).replace("\n", "<br/>")
            story.append(Paragraph(f"<b>{escape(label)}:</b> {value}", body_style))

    document.build(story)
    output.seek(0)
    return output
