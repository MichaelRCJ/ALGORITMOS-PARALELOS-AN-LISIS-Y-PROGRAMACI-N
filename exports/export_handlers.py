import io
import re
from datetime import datetime
import pandas as pd
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import cm


def export_to_excel(results):
    if not results:
        raise ValueError("No hay resultados para exportar")
    
    df = pd.DataFrame(results)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Artículos')
    output.seek(0)
    return output


def export_to_word(content, title="Análisis Bibliográfico"):
    doc = Document()
    
    # Title
    title_para = doc.add_heading(title, 0)
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    # Date
    date_para = doc.add_paragraph(f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    date_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    doc.add_paragraph()
    
    # Content
    for line in content.split('\n'):
        if line.strip():
            p = doc.add_paragraph(line)
            p.style = 'Normal'
    
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    return output


def export_to_pdf(content, title="Análisis Bibliográfico"):
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.darkblue,
        alignment=TA_CENTER,
        spaceAfter=20
    )
    
    story = []
    
    # Title
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 0.3*cm))
    
    # Date
    story.append(Paragraph(f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
    story.append(Spacer(1, 0.5*cm))
    
    # Content
    for line in content.split('\n'):
        if line.strip():
            # Clean HTML tags if present
            clean_line = re.sub(r'<[^>]+>', '', line)
            story.append(Paragraph(clean_line, styles['Normal']))
            story.append(Spacer(1, 0.2*cm))
    
    doc.build(story)
    output.seek(0)
    return output


def export_analysis_to_excel(analysis_data):
    if not analysis_data:
        raise ValueError("No hay datos de análisis para exportar")
    
    df = pd.DataFrame(analysis_data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Análisis')
    output.seek(0)
    return output
