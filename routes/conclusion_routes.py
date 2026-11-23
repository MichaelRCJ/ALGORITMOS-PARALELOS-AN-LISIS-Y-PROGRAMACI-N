# -*- coding: utf-8 -*-
"""
Rutas Flask para la ventana de conclusiones
Maneja la generación de resumen y conclusiones integradas
"""

import os
import requests
import pandas as pd
import io
from flask import Blueprint, jsonify, render_template, request, send_file
from exports.export_handlers import export_to_word, export_to_pdf, export_to_excel
from services.gemini_service import MODELS_FALLBACK, _candidate_models

# Crear Blueprint para las rutas de conclusiones
conclusion_bp = Blueprint('conclusion', __name__, url_prefix='/conclusion')


@conclusion_bp.route('/')
def index():
    """Página principal de conclusiones"""
    return render_template('conclusion.html')


@conclusion_bp.route('/upload_file', methods=['POST'])
def upload_file():
    """Carga y extrae contenido de archivos Word, PDF o Excel"""
    if 'file' not in request.files:
        return jsonify({"error": "No se proporcionó ningún archivo"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No se seleccionó ningún archivo"}), 400

    try:
        filename = file.filename.lower()

        # Procesar Excel
        if filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file)
            content = df.to_string(index=False)

        # Procesar Word
        elif filename.endswith('.docx'):
            from docx import Document
            doc = Document(file)
            content = '\n'.join([paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip()])

        # Procesar PDF
        elif filename.endswith('.pdf'):
            import PyPDF2
            pdf_reader = PyPDF2.PdfReader(file)
            content = ''
            for page in pdf_reader.pages:
                content += page.extract_text() + '\n'

        else:
            return jsonify({"error": "Formato de archivo no soportado. Use .docx, .pdf, .xlsx o .xls"}), 400

        return jsonify({
            "success": True,
            "content": content
        })

    except ImportError as e:
        return jsonify({"error": f"Falta librería para procesar este formato: {str(e)}. Instala con: pip install python-docx PyPDF2 openpyxl"}), 500
    except Exception as e:
        return jsonify({"error": f"Error procesando archivo: {str(e)}"}), 500


@conclusion_bp.route('/generate', methods=['POST'])
def generate():
    """Genera resumen y conclusiones usando Gemini"""
    data = request.json
    analysis = data.get('analysis', '')
    comparison = data.get('comparison', '')

    if not analysis and not comparison:
        return jsonify({"error": "Se requiere al menos un análisis para generar conclusiones"}), 400

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return jsonify({"error": "La variable GEMINI_API_KEY no está configurada"}), 500

    prompt = f"""Actúa como un investigador académico experto en revisión bibliográfica y síntesis de información.

Tengo dos análisis de artículos científicos que necesito que integres en un resumen coherente y conclusiones significativas.

ANÁLISIS INDIVIDUAL:
{analysis if analysis else '[No proporcionado]'}

TABLA COMPARATIVA:
{comparison if comparison else '[No proporcionada]'}

==================================================
TAREA
==================================================
Debes generar un documento académico que incluya:

1. RESUMEN INTEGRADO (300-400 palabras):
   - Sintetiza la información más relevante de ambos análisis
   - Destaca los hallazgos principales
   - Identifica patrones o tendencias
   - Conecta los hallazgos del análisis individual con las comparaciones

2. CONCLUSIONES (200-300 palabras):
   - Principales hallazgos derivados de la integración de ambos análisis
   - Implicaciones para el campo de estudio
   - Recomendaciones basadas en la evidencia
   - Áreas de investigación futura sugeridas

3. REFERENCIAS INTEGRADAS:
   - Lista consolidada de las fuentes mencionadas en ambos análisis
   - Formato APA 7

==================================================
REGLAS
==================================================
1. Escribe exclusivamente en español
2. Utiliza únicamente la información proporcionada en los análisis
3. NO inventes datos, resultados o conclusiones
4. Sé objetivo y académico en tu tono
5. Si falta información en uno de los análisis, indícalo claramente
6. El documento debe estar bien estructurado con títulos claros

==================================================
FORMATO DE RESPUESTA
==================================================
RESUMEN INTEGRADO
[Escribe aquí el resumen]

CONCLUSIONES
[Escribe aquí las conclusiones]

REFERENCIAS
[Escribe aquí las referencias en formato APA 7]
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3},
    }

    # Cascada de modelos: si uno falla (503, 404, timeout), pasa al siguiente
    ultimo_error = None
    for modelo in _candidate_models():
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
            response = requests.post(
                url,
                params={"key": api_key},
                json=payload,
                timeout=90
            )
            if response.status_code >= 500 or response.status_code == 404:
                ultimo_error = f"Error {response.status_code} del modelo {modelo}"
                continue
            response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()

            return jsonify({
                "success": True,
                "conclusion": text
            })
        except Exception as e:
            ultimo_error = str(e)
            continue

    return jsonify({"error": f"Error generando conclusiones: {ultimo_error}"}), 500


@conclusion_bp.route('/export_word', methods=['POST'])
def export_word():
    """Exporta las conclusiones a Word"""
    data = request.json
    conclusion = data.get('conclusion', '')
    analysis = data.get('analysis', '')
    comparison = data.get('comparison', '')

    if not conclusion:
        return jsonify({"error": "No hay conclusiones para exportar"}), 400

    # Combinar todo el contenido
    full_content = f"""RESUMEN Y CONCLUSIONES INTEGRADAS
====================================

{conclusion}

---

ANÁLISIS INDIVIDUAL ORIGINAL:
{analysis if analysis else '[No proporcionado]'}

---

TABLA COMPARATIVA ORIGINAL:
{comparison if comparison else '[No proporcionada]'}
"""

    try:
        output = export_to_word(full_content, "Resumen y Conclusiones Integradas")
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name='resumen_conclusiones.docx'
        )
    except Exception as e:
        return jsonify({"error": f"Error exportando Word: {str(e)}"}), 500


@conclusion_bp.route('/export_pdf', methods=['POST'])
def export_pdf():
    """Exporta las conclusiones a PDF"""
    data = request.json
    conclusion = data.get('conclusion', '')
    analysis = data.get('analysis', '')
    comparison = data.get('comparison', '')

    if not conclusion:
        return jsonify({"error": "No hay conclusiones para exportar"}), 400

    # Combinar todo el contenido
    full_content = f"""RESUMEN Y CONCLUSIONES INTEGRADAS
====================================

{conclusion}

---

ANÁLISIS INDIVIDUAL ORIGINAL:
{analysis if analysis else '[No proporcionado]'}

---

TABLA COMPARATIVA ORIGINAL:
{comparison if comparison else '[No proporcionada]'}
"""

    try:
        output = export_to_pdf(full_content, "Resumen y Conclusiones Integradas")
        return send_file(
            output,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='resumen_conclusiones.pdf'
        )
    except Exception as e:
        return jsonify({"error": f"Error exportando PDF: {str(e)}"}), 500


@conclusion_bp.route('/export_excel', methods=['POST'])
def export_excel():
    """Exporta las conclusiones a Excel"""
    data = request.json
    conclusion = data.get('conclusion', '')
    analysis = data.get('analysis', '')
    comparison = data.get('comparison', '')

    if not conclusion:
        return jsonify({"error": "No hay conclusiones para exportar"}), 400

    # Crear datos para Excel
    excel_data = [
        {
            "Sección": "Resumen y Conclusiones",
            "Contenido": conclusion
        },
        {
            "Sección": "Análisis Individual",
            "Contenido": analysis if analysis else "[No proporcionado]"
        },
        {
            "Sección": "Tabla Comparativa",
            "Contenido": comparison if comparison else "[No proporcionado]"
        }
    ]

    try:
        output = export_to_excel(excel_data)
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='resumen_conclusiones.xlsx'
        )
    except Exception as e:
        return jsonify({"error": f"Error exportando Excel: {str(e)}"}), 500
