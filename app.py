from flask import Flask, render_template, request, jsonify, send_file
import os, re, io, json, time, html, zipfile, unicodedata
from pathlib import Path
import pandas as pd
import requests
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

from utils.api_clients import (
    search_openalex, search_crossref, dedupe,
    buscar_openalex_simple, buscar_crossref_simple, deduplicar_fuentes, limpiar_texto
)
from citations import generar_referencia_apa, generar_cita_apa
from groq_service import (
    expand_query_with_groq, analyze_with_groq, analyze_category_with_groq
)
from exports.export_handlers import export_to_excel, export_to_word, export_to_pdf
from routes.analysis_routes import analysis_bp
from routes.analysis_individual_routes import individual_bp
from routes.compare_routes import compare_bp
from routes.conclusion_routes import conclusion_bp

app = Flask(__name__)

# Registrar blueprint de análisis
app.register_blueprint(analysis_bp)
app.register_blueprint(individual_bp)
app.register_blueprint(compare_bp)
app.register_blueprint(conclusion_bp)

# Configuration
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "ScientificSearch/1.0 (academic metadata client)"})

LANGS = {
    "any": None,
    "es": "Español",
    "en": "Inglés",
    "pt": "Portugués",
    "fr": "Francés",
    "de": "Alemán",
    "it": "Italiano",
}

# Analysis categories
CATEGORIAS = {
    "antecedentes": "antecedentes y contexto de la investigación",
    "modelos": "modelos, arquitecturas, modelos conceptuales o modelos matemáticos",
    "metodologias": "metodologías y enfoques de investigación",
    "metodos": "métodos, procedimientos y estrategias utilizadas",
    "experimentos": "experimentos, pruebas, escenarios experimentales y evaluación",
    "replicas": "replicabilidad, reproducción de experimentos y estudios de réplica",
    "tecnicas": "técnicas utilizadas para resolver el problema",
    "herramientas": "herramientas, software, plataformas y tecnologías utilizadas",
    "resultados": "resultados, hallazgos y principales descubrimientos",
    "limitaciones": "limitaciones, problemas y restricciones de las investigaciones",
    "recomendaciones": "recomendaciones, trabajos futuros y líneas futuras de investigación"
}

def norm(text):
    text = unicodedata.normalize("NFKD", str(text or ""))
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).lower().split())

@app.route('/')
def index():
    return render_template('index.html', langs=LANGS)

@app.route('/search', methods=['POST'])
def search():
    data = request.json
    query = data.get('query', '').strip()
    y0 = data.get('year_from', 2020)
    y1 = data.get('year_to', 2026)
    lang = data.get('language')
    limit = data.get('limit', 25)
    require_doi = data.get('require_doi', True)
    openalex_key = data.get('openalex_key')
    
    if not query:
        return jsonify({"error": "Por favor ingrese un tema de búsqueda"}), 400
    
    if y0 > y1:
        return jsonify({"error": "El año inicial no puede ser mayor que el final"}), 400
    
    rows = []
    errors = []
    
    try:
        rows.extend(search_openalex(query, y0, y1, lang, limit, openalex_key))
    except Exception as e:
        errors.append(f"OpenAlex: {str(e)}")
    
    try:
        rows.extend(search_crossref(query, y0, y1, lang, limit))
    except Exception as e:
        errors.append(f"Crossref: {str(e)}")
    
    rows = dedupe(rows)
    
    if require_doi:
        rows = [r for r in rows if r.get("doi") or r.get("url")]
    
    rows = sorted(rows, key=lambda x: (x.get("citas", 0), x.get("anio", 0)), reverse=True)
    
    return jsonify({
        "results": rows[:100],
        "count": len(rows),
        "errors": errors
    })

@app.route('/export', methods=['POST'])
def export():
    data = request.json
    results = data.get('results', [])
    
    if not results:
        return jsonify({"error": "No hay resultados para exportar"}), 400
    
    output = export_to_excel(results)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='articulos_cientificos.xlsx'
    )

@app.route('/download_pdfs', methods=['POST'])
def download_pdfs():
    data = request.json
    results = data.get('results', [])
    
    if not results:
        return jsonify({"error": "No hay resultados para descargar"}), 400
    
    zip_buffer = io.BytesIO()
    ok = 0
    failed = []
    
    with zipfile.ZipFile(zip_buffer, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for i, row in enumerate(results, 1):
            url = str(row.get("pdf_oa") or "").strip()
            if not url:
                failed.append((row.get("titulo", ""), "sin PDF abierto"))
                continue
            
            try:
                r = SESSION.get(url, timeout=45, allow_redirects=True)
                ctype = (r.headers.get("content-type") or "").lower()
                if r.status_code != 200 or ("pdf" not in ctype and not r.content.startswith(b"%PDF")):
                    raise ValueError(f"respuesta no PDF ({r.status_code}, {ctype[:40]})")
                
                safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", norm(row.get("titulo", "")))[:90].strip("_")
                filename = f"{i:03d}_{safe_name or 'articulo'}.pdf"
                zf.writestr(filename, r.content)
                ok += 1
            except Exception as e:
                failed.append((row.get("titulo", ""), str(e)))
    
    zip_buffer.seek(0)
    
    return jsonify({
        "ok": ok,
        "failed": failed,
        "total": len(results)
    })

@app.route('/expand_query', methods=['POST'])
def expand_query():
    data = request.json
    query = data.get('query', '').strip()
    model = data.get('model', os.environ.get('GROQ_MODEL', 'openai/gpt-oss-20b'))
    
    if not query:
        return jsonify({"error": "Por favor ingrese un tema de búsqueda"}), 400
    
    try:
        expanded = expand_query_with_groq(query, model)
        return jsonify({"expanded": expanded, "original": query})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.json
    results = data.get('results', [])
    model = data.get('model', os.environ.get('GROQ_MODEL', 'openai/gpt-oss-20b'))
    
    if not results:
        return jsonify({"error": "No hay resultados para analizar"}), 400
    
    try:
        analysis = analyze_with_groq(results, model)
        return jsonify({"analysis": analysis})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/analyze_category', methods=['POST'])
def analyze_category():
    data = request.json
    results = data.get('results', [])
    category = data.get('category', '')
    model = data.get('model', os.environ.get('GROQ_MODEL', 'openai/gpt-oss-20b'))
    
    if not results:
        return jsonify({"error": "No hay resultados para analizar"}), 400
    
    if category not in CATEGORIAS:
        return jsonify({"error": "Categoría no válida"}), 400
    
    try:
        category_desc = CATEGORIAS[category]
        analysis = analyze_category_with_groq(results, category_desc, model)
        return jsonify({"analysis": analysis, "category": category})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/generate_citations', methods=['POST'])
def generate_citations():
    data = request.json
    results = data.get('results', [])
    
    if not results:
        return jsonify({"error": "No hay resultados para generar citas"}), 400
    
    citations = []
    for article in results:
        try:
            ref = generar_referencia_apa(article)
            citations.append({
                "titulo": article.get("titulo", ""),
                "referencia": ref
            })
        except Exception as e:
            citations.append({
                "titulo": article.get("titulo", ""),
                "referencia": f"Error: {str(e)}"
            })
    
    return jsonify({"citations": citations})

@app.route('/export_analysis', methods=['POST'])
def export_analysis():
    data = request.json
    content = data.get('content', '')
    format_type = data.get('format', 'word')
    title = data.get('title', 'Análisis Bibliográfico')
    
    if not content:
        return jsonify({"error": "No hay contenido para exportar"}), 400
    
    try:
        if format_type == 'word':
            output = export_to_word(content, title)
            return send_file(
                output,
                mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                as_attachment=True,
                download_name='analisis_bibliografico.docx'
            )
        elif format_type == 'pdf':
            output = export_to_pdf(content, title)
            return send_file(
                output,
                mimetype='application/pdf',
                as_attachment=True,
                download_name='analisis_bibliografico.pdf'
            )
        else:
            return jsonify({"error": "Formato no soportado"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/categories', methods=['GET'])
def get_categories():
    return jsonify({"categories": CATEGORIAS})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
