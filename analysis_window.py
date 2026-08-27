# -*- coding: utf-8 -*-
"""
Módulo de ventana de análisis avanzado
Basado en la funcionalidad de análisis bibliográfico inteligente
"""

import re
import json
import os
import pandas as pd
from datetime import datetime

from api_clients import (
    buscar_openalex_simple, buscar_crossref_simple, 
    deduplicar_fuentes, limpiar_texto
)
from citations import generar_referencia_apa, generar_cita_apa
from groq_service import get_groq_key


# Categorías de análisis
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


# Variables globales para almacenar estado del análisis
RESULTADOS_ANALISIS = {}
FUENTES_ACTUALES = []
ARTICULOS_BUSCADOS = []
CATEGORIA_ACTUAL = ""


def preparar_articulos_excel(df):
    """Prepara artículos desde un DataFrame para análisis"""
    if df is None:
        return []
    
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(df)
    
    columnas = list(df.columns)
    columna_titulo = None
    
    for columna in columnas:
        nombre = str(columna).lower()
        if "titulo" in nombre or "title" in nombre:
            columna_titulo = columna
            break
    
    if columna_titulo is None:
        return []
    
    articulos = []
    # máximo 12 artículos
    df = df.head(12)
    
    for _, fila in df.iterrows():
        titulo = limpiar_texto(fila.get(columna_titulo, ""))
        if not titulo:
            continue
        
        autores = ""
        anio = ""
        doi = ""
        abstract = ""
        
        for columna in columnas:
            nombre = str(columna).lower()
            if "autor" in nombre or "author" in nombre:
                autores = limpiar_texto(fila.get(columna, ""))
            if "anio" in nombre or "año" in nombre or "year" in nombre:
                anio = limpiar_texto(fila.get(columna, ""))
            if "doi" in nombre:
                doi = limpiar_texto(fila.get(columna, ""))
            if "abstract" in nombre or "resumen" in nombre:
                abstract = limpiar_texto(fila.get(columna, ""))
        
        articulos.append({
            "titulo": titulo,
            "autores": autores,
            "anio": anio,
            "doi": doi,
            "abstract": abstract
        })
    
    return articulos


def generar_parrafo_groq(articulo, fuentes, categoria, descripcion):
    """Genera un párrafo académico usando Groq para análisis de categoría"""
    key = get_groq_key()

    if not key:
        return "⚠️ **Groq no está configurado.** Configura la variable GROQ_API_KEY."
    
    contexto = ""
    for i, fuente in enumerate(fuentes, start=1):
        autores = fuente.get("autores", [])
        if isinstance(autores, list):
            autores = ", ".join(autores)
        
        contexto += f"""
FUENTE {i}
Título: {fuente.get('titulo', '')}
Autores: {autores}
Año: {fuente.get('anio', '')}
Revista: {fuente.get('revista', '')}
DOI: {fuente.get('doi', '')}
Resumen: {fuente.get('abstract', '')}
URL: {fuente.get('url', '')}
"""
    
    prompt = f"""
Actúa como un investigador académico especializado en revisión bibliográfica.

ARTÍCULO PRINCIPAL:
Título: {articulo.get('titulo', '')}
Autores: {articulo.get('autores', '')}
Año: {articulo.get('anio', '')}
Resumen: {articulo.get('abstract', '')}

CATEGORÍA QUE DEBO ANALIZAR:
{categoria}

DESCRIPCIÓN:
{descripcion}

FUENTES ACADÉMICAS ENCONTRADAS:
{contexto}

==================================================
OBJETIVO
==================================================
Necesito que redactes un texto académico que EXPLIQUE
qué dicen las investigaciones encontradas respecto
a la categoría solicitada.

NO quiero solamente una referencia bibliográfica.
NO quiero una lista.
NO quiero que repitas solamente el título.

Quiero un PÁRRAFO ACADÉMICO redactado de manera natural,
coherente y formal.

==================================================
REGLAS
==================================================
1. Escribe exclusivamente en español.
2. Utiliza únicamente información presente en los títulos, autores, años y resúmenes proporcionados.
3. NO inventes resultados.
4. NO inventes metodologías.
5. NO inventes estadísticas.
6. NO inventes conclusiones.
7. NO inventes autores.
8. NO inventes DOI.
9. Si el resumen no contiene información suficiente, indícalo de manera prudente.
10. Relaciona la información de las fuentes con la categoría solicitada.
11. El texto debe tener aproximadamente entre 120 y 200 palabras.
12. Utiliza citas APA 7 dentro del texto.
13. Una fuente: (Apellido, año)
14. Dos autores: (Apellido & Apellido, año)
15. Tres o más: (Apellido et al., año)
16. No coloques una cita si no puedes identificar correctamente la fuente.
17. No coloques referencias inventadas.

==================================================
FORMATO
==================================================
PÁRRAFO:
[Escribe aquí el párrafo académico]

SÍNTESIS:
[Escribe una síntesis de 2 o 3 oraciones]

REFERENCIAS:
[Escribe únicamente las referencias correspondientes a las fuentes realmente utilizadas]
"""
    
    try:
        from groq import Groq
        client = Groq(api_key=key)
        
        respuesta = client.chat.completions.create(
            model=os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"),
            messages=[
                {
                    "role": "system",
                    "content": "Eres un investigador académico. Debes redactar información basada únicamente en las fuentes entregadas. Nunca inventes información."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.15,
            max_completion_tokens=2500
        )
        
        return respuesta.choices[0].message.content
    
    except Exception as e:
        return f"❌ **Error al generar el párrafo con Groq.** `{str(e)}`"


def investigar_categoria(df, categoria):
    """Investiga una categoría específica para los artículos cargados"""
    global RESULTADOS_ANALISIS, FUENTES_ACTUALES, CATEGORIA_ACTUAL
    
    articulos = preparar_articulos_excel(df)
    if not articulos:
        return "❌ No se encontraron artículos en el Excel.", pd.DataFrame()
    
    descripcion = CATEGORIAS.get(categoria, categoria)
    
    # El Excel ya contiene las fuentes recuperadas durante la búsqueda.
    # Reutilizarlas evita repetir consultas y activar los límites de las APIs.
    todas_fuentes = articulos[:20]
    
    FUENTES_ACTUALES = todas_fuentes
    CATEGORIA_ACTUAL = categoria
    
    if not todas_fuentes:
        return "❌ No se encontraron fuentes académicas.", pd.DataFrame()
    
    # Crear tabla de fuentes
    filas = []
    for fuente in todas_fuentes:
        autores = fuente.get("autores", [])
        if isinstance(autores, list):
            autores = ", ".join(autores)
        
        filas.append({
            "Título": fuente.get("titulo", ""),
            "Autores": autores,
            "Año": fuente.get("anio", ""),
            "Revista": fuente.get("revista", ""),
            "DOI": fuente.get("doi", ""),
            "Fuente": fuente.get("fuente", ""),
            "URL": fuente.get("url", "")
        })
    
    tabla = pd.DataFrame(filas)
    
    # Usar el primer artículo como referencia principal
    articulo_principal = articulos[0]
    texto = generar_parrafo_groq(articulo_principal, todas_fuentes, categoria, descripcion)
    
    # Guardar resultados
    RESULTADOS_ANALISIS[categoria] = {
        "texto": texto,
        "fuentes": todas_fuentes,
        "articulo": articulo_principal
    }
    
    mensaje = (
        f"# {categoria}\n\n"
        f"Se encontraron **{len(todas_fuentes)} fuentes académicas**.\n\n"
        "---\n\n"
        + texto
    )
    
    return mensaje, tabla


def investigar_todo(df):
    """Investiga todas las categorías para los artículos cargados"""
    if df is None:
        return "⚠️ Primero carga el Excel.", pd.DataFrame()
    
    resultados = []
    tablas = []
    
    for categoria in CATEGORIAS:
        try:
            texto, tabla = investigar_categoria(df, categoria)
            resultados.append(texto)
            
            if isinstance(tabla, pd.DataFrame) and not tabla.empty:
                temp = tabla.copy()
                temp.insert(0, "Categoría", categoria)
                tablas.append(temp)
        
        except Exception as e:
            resultados.append(
                f"## {categoria}\n\n"
                f"❌ Error: {str(e)}"
            )
    
    if tablas:
        tabla_final = pd.concat(tablas, ignore_index=True)
    else:
        tabla_final = pd.DataFrame()
    
    texto_final = (
        "# REVISIÓN BIBLIOGRÁFICA COMPLETA\n\n"
        + "\n\n---\n\n".join(resultados)
    )
    
    return texto_final, tabla_final


def limpiar_resultados():
    """Limpia los resultados almacenados"""
    global RESULTADOS_ANALISIS, FUENTES_ACTUALES, ARTICULOS_BUSCADOS, CATEGORIA_ACTUAL
    RESULTADOS_ANALISIS = {}
    FUENTES_ACTUALES = []
    ARTICULOS_BUSCADOS = []
    CATEGORIA_ACTUAL = ""