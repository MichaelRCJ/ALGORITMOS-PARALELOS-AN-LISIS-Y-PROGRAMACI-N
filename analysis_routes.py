# -*- coding: utf-8 -*-
"""
Rutas Flask específicas para la ventana de análisis
Maneja las solicitudes de análisis bibliográfico avanzado
"""

from flask import Blueprint, render_template, request, jsonify, send_file
import pandas as pd
import io
import json

from analysis_window import (
    CATEGORIAS, investigar_categoria, investigar_todo, 
    limpiar_resultados, RESULTADOS_ANALISIS
)
from export_handlers import export_to_word, export_to_pdf, export_analysis_to_excel

# Crear Blueprint para las rutas de análisis
analysis_bp = Blueprint('analysis', __name__, url_prefix='/analysis')


@analysis_bp.route('/')
def index():
    """Página principal de análisis"""
    return render_template('analysis.html', categories=CATEGORIAS)


@analysis_bp.route('/load_excel', methods=['POST'])
def load_excel():
    """Carga un archivo Excel para análisis"""
    if 'file' not in request.files:
        return jsonify({"error": "No se proporcionó ningún archivo"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No se seleccionó ningún archivo"}), 400
    
    try:
        df = pd.read_excel(file)
        
        if df.empty:
            return jsonify({"error": "El Excel está vacío"}), 400
        
        # Verificar que tenga columna de título
        columnas = [str(c).lower() for c in df.columns]
        tiene_titulo = any("titulo" in c or "title" in c for c in columnas)
        
        if not tiene_titulo:
            return jsonify({"error": "El Excel no tiene columna 'Titulo' o 'Title'"}), 400
        
        # Convertir DataFrame a formato JSON para el frontend
        articulos = []
        for _, row in df.iterrows():
            articulo = {}
            for col in df.columns:
                articulo[col] = str(row[col]) if pd.notna(row[col]) else ""
            articulos.append(articulo)
        
        return jsonify({
            "success": True,
            "message": f"✅ Excel cargado correctamente. {len(df)} artículos.",
            "articulos": articulos,
            "columnas": list(df.columns)
        })
    
    except Exception as e:
        return jsonify({"error": f"Error leyendo Excel: {str(e)}"}), 500


@analysis_bp.route('/investigate_category', methods=['POST'])
def investigate_category():
    """Investiga una categoría específica"""
    data = request.json
    articulos = data.get('articulos', [])
    categoria = data.get('category', '')
    
    if not articulos:
        return jsonify({"error": "No hay artículos para analizar"}), 400
    
    if categoria not in CATEGORIAS:
        return jsonify({"error": "Categoría no válida"}), 400
    
    try:
        # Convertir articulos a DataFrame
        df = pd.DataFrame(articulos)
        
        # Investigar categoría
        mensaje, tabla = investigar_categoria(df, categoria)
        
        # Convertir tabla a formato JSON
        fuentes_json = []
        if not tabla.empty:
            for _, row in tabla.iterrows():
                fuentes_json.append({
                    "Título": row.get("Título", ""),
                    "Autores": row.get("Autores", ""),
                    "Año": row.get("Año", ""),
                    "Revista": row.get("Revista", ""),
                    "DOI": row.get("DOI", ""),
                    "Fuente": row.get("Fuente", ""),
                    "URL": row.get("URL", "")
                })
        
        return jsonify({
            "success": True,
            "mensaje": mensaje,
            "fuentes": fuentes_json,
            "categoria": categoria
        })
    
    except Exception as e:
        return jsonify({"error": f"Error en investigación: {str(e)}"}), 500


@analysis_bp.route('/investigate_all', methods=['POST'])
def investigate_all():
    """Investiga todas las categorías"""
    data = request.json
    articulos = data.get('articulos', [])
    
    if not articulos:
        return jsonify({"error": "No hay artículos para analizar"}), 400
    
    try:
        # Convertir articulos a DataFrame
        df = pd.DataFrame(articulos)
        
        # Investigar todas las categorías
        mensaje, tabla = investigar_todo(df)
        
        # Convertir tabla a formato JSON
        fuentes_json = []
        if not tabla.empty:
            for _, row in tabla.iterrows():
                fuentes_json.append({
                    "Categoría": row.get("Categoría", ""),
                    "Título": row.get("Título", ""),
                    "Autores": row.get("Autores", ""),
                    "Año": row.get("Año", ""),
                    "Revista": row.get("Revista", ""),
                    "DOI": row.get("DOI", ""),
                    "Fuente": row.get("Fuente", ""),
                    "URL": row.get("URL", "")
                })
        
        return jsonify({
            "success": True,
            "mensaje": mensaje,
            "fuentes": fuentes_json
        })
    
    except Exception as e:
        return jsonify({"error": f"Error en investigación completa: {str(e)}"}), 500


@analysis_bp.route('/export_word', methods=['POST'])
def export_word():
    """Exporta el análisis a Word"""
    data = request.json
    content = data.get('content', '')
    title = data.get('title', 'Análisis Bibliográfico')
    
    if not content:
        return jsonify({"error": "No hay contenido para exportar"}), 400
    
    try:
        output = export_to_word(content, title)
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name='analisis_bibliografico.docx'
        )
    except Exception as e:
        return jsonify({"error": f"Error exportando Word: {str(e)}"}), 500


@analysis_bp.route('/export_pdf', methods=['POST'])
def export_pdf():
    """Exporta el análisis a PDF"""
    data = request.json
    content = data.get('content', '')
    title = data.get('title', 'Análisis Bibliográfico')
    
    if not content:
        return jsonify({"error": "No hay contenido para exportar"}), 400
    
    try:
        output = export_to_pdf(content, title)
        return send_file(
            output,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='analisis_bibliografico.pdf'
        )
    except Exception as e:
        return jsonify({"error": f"Error exportando PDF: {str(e)}"}), 500


@analysis_bp.route('/export_excel', methods=['POST'])
def export_excel():
    """Exporta el análisis a Excel"""
    data = request.json
    fuentes = data.get('fuentes', [])
    
    if not fuentes:
        return jsonify({"error": "No hay fuentes para exportar"}), 400
    
    try:
        output = export_analysis_to_excel(fuentes)
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='analisis_bibliografico.xlsx'
        )
    except Exception as e:
        return jsonify({"error": f"Error exportando Excel: {str(e)}"}), 500


@analysis_bp.route('/clear_results', methods=['POST'])
def clear_results():
    """Limpia los resultados almacenados"""
    try:
        limpiar_resultados()
        return jsonify({"success": True, "message": "Resultados limpiados correctamente"})
    except Exception as e:
        return jsonify({"error": f"Error limpiando resultados: {str(e)}"}), 500


@analysis_bp.route('/categories', methods=['GET'])
def get_categories():
    """Obtiene las categorías disponibles"""
    return jsonify({"categories": CATEGORIAS})