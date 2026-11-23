# -*- coding: utf-8 -*-
"""
Módulo de ventana de análisis avanzado
Basado en la funcionalidad de análisis bibliográfico inteligente
"""

import re
import json
import os
import time
import pandas as pd
from datetime import datetime

from utils.api_clients import (
    buscar_openalex_simple, buscar_crossref_simple,
    deduplicar_fuentes, limpiar_texto
)
from citations import generar_referencia_apa, generar_cita_apa
from services.gemini_service import analyze_article


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

_ANALYSIS_ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "analysis_api.env"
)


def _cargar_analysis_env():
    """Lee analysis_api.env (API dedicada de esta ventana). Prioridad sobre .env."""
    config = {}
    try:
        if os.path.exists(_ANALYSIS_ENV_PATH):
            with open(_ANALYSIS_ENV_PATH, "r", encoding="utf-8") as f:
                for linea in f:
                    linea = linea.strip()
                    if not linea or linea.startswith("#") or "=" not in linea:
                        continue
                    clave, valor = linea.split("=", 1)
                    valor = valor.strip().strip('"').strip("'")
                    if valor and "pega_aqui" not in valor.lower():
                        config[clave.strip()] = valor
    except OSError:
        pass
    return config


def _gemini_api_key():
    dedicada = _cargar_analysis_env().get("GEMINI_API_KEY", "").strip()
    return dedicada or os.environ.get("GEMINI_API_KEY", "").strip()


# Modelos de texto disponibles en la API, en orden de preferencia.
# Si uno falla (404, timeout, error), se pasa automáticamente al siguiente.
_MODELOS_FALLBACK = [
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-3-flash-preview",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
]


def _gemini_modelos():
    """Modelo configurado primero; luego la lista de respaldo (sin duplicados)."""
    modelos = []
    dedicado = _cargar_analysis_env().get("GEMINI_MODEL", "").strip()
    if dedicado:
        modelos.append(dedicado)
    for m in _MODELOS_FALLBACK:
        if m not in modelos:
            modelos.append(m)
    return modelos


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


def generar_parrafo_gemini(articulo, fuentes, categoria, descripcion):
    """Genera un párrafo académico usando Gemini para análisis de categoría"""
    import requests
    import os

    api_key = _gemini_api_key()
    if not api_key:
        return "⚠️ **Gemini no está configurado.** Configura GEMINI_API_KEY en analysis_api.env o en el .env principal."

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
Eres un investigador académico redactando un análisis
bibliográfico SERIO y COMPLETO para una revisión
científica. No quiero una respuesta corta ni superficial:
quiero un análisis estructurado, profundo y bien
organizado que un lector pueda citar en un paper.

==================================================
REGLAS
==================================================
1. Escribe exclusivamente en español, con tono académico formal.
2. Utiliza únicamente información presente en los títulos, autores, años y resúmenes proporcionados.
3. NO inventes resultados, metodologías, estadísticas, conclusiones, autores ni DOI.
4. Si el resumen no contiene información suficiente para un punto, reconócelo de manera prudente.
5. Cita en formato APA 7 dentro del texto:
   - Una fuente: (Apellido, año)
   - Dos autores: (Apellido & Apellido, año)
   - Tres o más: (Apellido et al., año)
6. Analiza TODAS las fuentes proporcionadas, no solo algunas.
7. Establece relaciones entre las fuentes: qué comparten, en qué difieren,
   qué enfoques coexisten y cómo se complementan o contradicen.
8. Identifica vacíos, tendencias y posibles líneas de trabajo futuro
   que se desprendan de las fuentes.
9. Extensión total: entre 500 y 800 palabras de análisis
   (sin contar las referencias).

==================================================
FORMATO OBLIGATORIO
==================================================
Devuelve el texto EXACTAMENTE con esta estructura de secciones:

## 1. Panorama general
[Párrafo introductorio: qué estudia la categoría, qué tan presente
está en las fuentes y qué papel juega en el campo. 80-120 palabras]

## 2. Análisis de las fuentes
[Analiza las fuentes agrupándolas por enfoque, corriente o aporte.
Cada grupo o fuente relevante debe citarse en APA dentro del texto.
Explica QUÉ aporta cada una a la categoría, no solo QUÉ dice su título.
120-250 palabras]

## 3. Coincidencias y discrepancias
[Qué concuerdan las fuentes entre sí y en qué difieren: metodologías,
enfoques, resultados o conclusiones opuestas. Sé específico. 80-150 palabras]

## 4. Vacíos y oportunidades de investigación
[Qué NO cubren las fuentes, qué preguntas quedan abiertas y qué
líneas futuras sugieren los propios textos. 60-120 palabras]

## 5. Síntesis
[Conclusión integradora de 2-4 oraciones que responda: ¿qué se sabe
hoy sobre esta categoría según estas fuentes y por qué importa?]

## Referencias
[Lista ÚNICAMENTE las fuentes realmente utilizadas, en formato APA 7,
una por línea, precedidas por "- "]
"""

    import requests

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }

    # Recorre la lista de modelos: si uno falla, pasa al siguiente.
    # Por modelo: 2 intentos solo para errores de red/timeout;
    # los errores HTTP (404, 429, etc.) pasan directo al siguiente modelo.
    ultimo_error = None
    for modelo in _gemini_modelos():
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        for intento in range(2):
            try:
                response = requests.post(
                    url,
                    params={"key": api_key},
                    json=payload,
                    timeout=120
                )
                response.raise_for_status()
                data = response.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return text.strip()
            except requests.HTTPError as e:
                ultimo_error = e
                break
            except Exception as e:
                ultimo_error = e
                if intento == 0:
                    time.sleep(3)

    return f"❌ **Error al generar el párrafo con Gemini.** `{str(ultimo_error)}`"


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
    texto = generar_parrafo_gemini(articulo_principal, todas_fuentes, categoria, descripcion)
    
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