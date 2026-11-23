from flask import Blueprint, render_template, request, jsonify
import pandas as pd
import os
import re
from services.gemini_service import analyze_article, compare_articles, ask_question_about_comparison, FIELD_LABELS

compare_bp = Blueprint('compare', __name__, url_prefix='/compare')


def _local_comparison(articles, selected_fields):
    """Comparación de respaldo local cuando Gemini no está disponible."""
    stopwords = {
        "para", "como", "los", "las", "una", "uno", "del", "con", "por", "que", "sus",
        "sobre", "entre", "desde", "este", "esta", "más", "menos", "artículo", "información",
        "disponible", "no", "se", "en", "de", "y", "o", "el", "la", "un", "al", "es",
    }
    comparisons = []
    for field in selected_fields:
        token_sets = []
        for article in articles:
            value = str(article.get(field) or "")
            tokens = {w.lower() for w in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]{5,}", value) if w.lower() not in stopwords}
            if tokens:
                token_sets.append(tokens)
        common = set.intersection(*token_sets) if len(token_sets) > 1 else set()
        common_text = ", ".join(sorted(common)[:8])
        authors = "; ".join(
            f"{a.get('autores') or 'Autor no indicado'} ({a.get('titulo', '')})"
            for a in articles
        )
        comparisons.append({
            "aspecto": FIELD_LABELS.get(field, field),
            "articulos_autores": authors,
            "semejanzas": f"Términos compartidos en los registros: {common_text}." if common_text else "No se detectó coincidencia textual suficiente entre los registros.",
            "diferencias": "Los artículos presentan contenidos específicos diferentes; se requiere una respuesta de Gemini para describir diferencias conceptuales con mayor precisión.",
            "conclusion": "Comparación local generada automáticamente porque el servicio de Gemini no estuvo disponible.",
        })
    return comparisons

@compare_bp.route('/')
def index():
    return render_template('compare.html', field_labels=FIELD_LABELS)

@compare_bp.route('/upload', methods=['POST'])
def upload_excel():
    """Carga el archivo Excel y extrae los artículos"""
    if 'file' not in request.files:
        return jsonify({"error": "No se envió ningún archivo"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No se seleccionó ningún archivo"}), 400
    
    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({"error": "El archivo debe ser un Excel (.xlsx o .xls)"}), 400
    
    try:
        df = pd.read_excel(file)
        
        # Convertir DataFrame a lista de diccionarios, reemplazando NaN con None
        articles = []
        for _, row in df.iterrows():
            article = {}
            for col in df.columns:
                # Normalizar nombre de columna a minúsculas
                col_name = str(col).lower().strip()
                value = row[col]
                # Reemplazar NaN con None o string vacío
                if pd.isna(value):
                    article[col_name] = None
                elif isinstance(value, (int, float)) and pd.isna(value):
                    article[col_name] = None
                else:
                    article[col_name] = value
            articles.append(article)
        
        return jsonify({
            "success": True,
            "articles": articles,
            "count": len(articles),
            "columns": list(df.columns)
        })
    except Exception as e:
        import traceback
        return jsonify({"error": f"Error al leer el archivo Excel: {str(e)}\n{traceback.format_exc()}"}), 500

@compare_bp.route('/analyze', methods=['POST'])
def analyze_missing_info():
    """Analiza artículos con Gemini para completar información faltante"""
    data = request.json
    articles = data.get('articles', [])
    selected_fields = data.get('selected_fields', [])
    
    if not articles:
        return jsonify({"error": "No hay artículos para analizar"}), 400
    
    if not selected_fields:
        return jsonify({"error": "No se seleccionaron campos para analizar"}), 400
    
    try:
        analyzed_articles = []
        for i, article in enumerate(articles):
            try:
                # Analizar el artículo con Gemini
                analysis = analyze_article(article, selected_fields)
                # Combinar información existente con la nueva
                analyzed_articles.append({**article, **analysis})
            except Exception as e:
                print(f"Error analizando artículo {i}: {str(e)}")
                analyzed_articles.append(article)
        
        return jsonify({
            "success": True,
            "articles": analyzed_articles
        })
    except Exception as e:
        return jsonify({"error": f"Error al analizar artículos: {str(e)}"}), 500

@compare_bp.route('/compare', methods=['POST'])
def compare():
    """Genera la tabla comparativa usando Gemini"""
    data = request.json
    articles = data.get('articles', [])
    selected_fields = data.get('selected_fields', [])
    
    print(f"Recibidos {len(articles)} artículos para comparar")
    print(f"Campos seleccionados: {selected_fields}")
    
    if not articles:
        return jsonify({"error": "No hay artículos para comparar"}), 400
    
    if not selected_fields:
        return jsonify({"error": "No se seleccionaron campos para comparar"}), 400
    
    try:
        # Verificar si faltan campos en los artículos
        missing_fields = []
        for field in selected_fields:
            for article in articles:
                if not article.get(field) or article.get(field) == "No disponible":
                    missing_fields.append(field)
                    break
        
        # Si faltan campos, completarlos con Gemini primero
        if missing_fields:
            print(f"Faltan campos: {missing_fields}. Completando con Gemini...")
            enriched_articles = []
            for i, article in enumerate(articles):
                print(f"Analizando artículo {i+1}/{len(articles)}...")
                try:
                    analysis = analyze_article(article, missing_fields)
                    enriched_articles.append({**article, **analysis})
                except Exception as e:
                    print(f"Error analizando artículo {i+1}: {str(e)}")
                    enriched_articles.append(article)
            articles = enriched_articles
            print("Información completada con Gemini")
        
        # Usar Gemini para comparar los artículos
        try:
            comparisons = compare_articles(articles, selected_fields)
        except Exception as gemini_error:
            print(f"Gemini no disponible para comparar, usando respaldo local: {gemini_error}")
            comparisons = _local_comparison(articles, selected_fields)
            return jsonify({
                "success": True,
                "comparisons": comparisons,
                "enriched": len(missing_fields) > 0,
                "source": "local",
                "notice": "Gemini no estuvo disponible; se generó una comparación local con los datos disponibles."
            })
        
        return jsonify({
            "success": True,
            "comparisons": comparisons,
            "enriched": len(missing_fields) > 0
        })
    except Exception as e:
        import traceback
        print(f"Error al comparar: {str(e)}")
        print(traceback.format_exc())
        return jsonify({"error": f"Error al comparar artículos: {str(e)}"}), 500

@compare_bp.route('/ask', methods=['POST'])
def ask_question():
    """Responde una pregunta basada en el análisis comparativo"""
    data = request.json
    articles = data.get('articles', [])
    comparisons = data.get('comparisons', [])
    question = data.get('question', '').strip()

    if not articles:
        return jsonify({"error": "No hay artículos para responder la pregunta"}), 400

    if not comparisons:
        return jsonify({"error": "No hay análisis comparativo disponible. Primero genera la comparación."}), 400

    if not question:
        return jsonify({"error": "Por favor ingresa una pregunta"}), 400

    try:
        answer = ask_question_about_comparison(articles, comparisons, question)
        return jsonify({
            "success": True,
            "answer": answer
        })
    except Exception as e:
        import traceback
        print(f"Error al responder pregunta: {str(e)}")
        print(traceback.format_exc())
        return jsonify({"error": f"Error al responder pregunta: {str(e)}"}), 500
