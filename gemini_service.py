import json
import os
import re
import time

import requests


GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.5-flash-lite"
MISSING_INFO = "No disponible"


class GeminiServiceError(RuntimeError):
    """Error controlado al comunicarse con Gemini."""


def _extract_json(text):
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise GeminiServiceError("Gemini no devolvió un JSON válido")
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise GeminiServiceError("Gemini no devolvió un JSON válido") from exc

    if not isinstance(value, dict):
        raise GeminiServiceError("La respuesta de Gemini no es un objeto JSON")
    return value


FIELD_LABELS = {
    "objetivo": "Objetivo",
    "problema": "Problema de investigación",
    "metodologia": "Metodología",
    "tecnicas": "Técnicas utilizadas",
    "herramientas": "Herramientas empleadas",
    "resultados": "Resultados principales",
    "hallazgos": "Hallazgos relevantes",
    "limitaciones": "Limitaciones",
    "contribuciones": "Contribuciones científicas",
    "palabras_clave": "Palabras clave",
}


def _prompt(article, selected_fields):
    requested = "\n".join(f"{index}. {FIELD_LABELS[field]}" for index, field in enumerate(selected_fields, 1))
    keys = ", ".join(selected_fields)
    # Buscar resumen con diferentes nombres posibles
    resumen = article.get('resumen') or article.get('abstract') or article.get('summary') or ''
    return f"""Analiza el siguiente artículo científico utilizando únicamente la información proporcionada. Extrae de forma objetiva y académica:

{requested}

Devuelve exclusivamente un objeto JSON válido, sin Markdown ni texto adicional, con exactamente estas claves:
{keys}.
Usa la información del Excel. Si no encuentras información suficiente para un aspecto, escribe exactamente "No disponible". No repitas el título como respuesta ni inventes datos.

TÍTULO:
{article.get('titulo', '')}

RESUMEN:
{resumen}

AUTORES:
{article.get('autores', '')}

AÑO:
{article.get('anio', '')}

DOI:
{article.get('doi', '')}"""


def analyze_article(article, selected_fields=None, model=None, timeout=60, max_retries=3):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise GeminiServiceError("La variable GEMINI_API_KEY no está configurada")

    selected_fields = selected_fields or list(FIELD_LABELS)
    selected_fields = [field for field in selected_fields if field in FIELD_LABELS]
    if not selected_fields:
        raise GeminiServiceError("No se seleccionaron aspectos para analizar")
    
    # Usar solo el modelo que funciona
    model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL).strip()
    if model not in ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-flash-latest", "gemini-pro-latest"]:
        model = "gemini-3.5-flash-lite"
    
    url = GEMINI_API_URL.format(model=model)
    payload = {
        "contents": [{"parts": [{"text": _prompt(article, selected_fields)}]}],
        "generationConfig": {
            "temperature": 0.1,
        },
    }

    last_error = None
    for attempt in range(max_retries):
        try:
            response = requests.post(
                url,
                params={"key": api_key},
                json=payload,
                timeout=timeout,
            )
            if response.status_code == 429:
                # Rate limit - esperar más tiempo
                if attempt < max_retries - 1:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 30
                    print(f"Rate limit (429), esperando {delay} segundos...")
                    time.sleep(min(delay, 60))
                    continue
            if response.status_code >= 500:
                if attempt < max_retries - 1:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 2 ** attempt
                    time.sleep(min(delay, 30))
                    continue
            if response.status_code == 404:
                raise GeminiServiceError(f"Modelo {model} no encontrado")
            response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            result = _extract_json(text)
            print(f"Éxito con modelo: {model}")
            return {key: result.get(key) or MISSING_INFO for key in selected_fields}
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError, GeminiServiceError) as exc:
            last_error = exc
            if attempt < max_retries - 1 and isinstance(exc, requests.RequestException):
                time.sleep(min(2 ** attempt, 30))
                continue
            break

    raise GeminiServiceError(str(last_error or "No fue posible analizar el artículo"))


def compare_articles(articles, selected_fields, model=None, timeout=90, max_retries=4):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise GeminiServiceError("La variable GEMINI_API_KEY no está configurada")
    selected_fields = [field for field in (selected_fields or []) if field in FIELD_LABELS]
    if not articles or not selected_fields:
        raise GeminiServiceError("Se necesitan artículos y aspectos seleccionados para comparar")

    records = []
    for article in articles:
        records.append({
            "titulo": article.get("titulo", ""),
            "autores": article.get("autores", ""),
            "anio": article.get("anio", ""),
            **{field: article.get(field, MISSING_INFO) for field in selected_fields},
        })
    prompt = f"""Compara académicamente estos artículos usando únicamente la información entregada.
Analiza cómo se asemejan y diferencian los autores en cada aspecto seleccionado: {', '.join(FIELD_LABELS[field] for field in selected_fields)}.

Devuelve exclusivamente un objeto JSON válido con esta estructura exacta:
{{"comparaciones": [{{"aspecto": "...", "articulos_autores": "...", "semejanzas": "...", "diferencias": "...", "conclusion": "..."}}]}}

Debe existir una fila por cada aspecto seleccionado. No inventes datos ni atribuyas información a autores que no aparezca en los registros. Si no hay evidencia suficiente, escribe "No disponible".

REGISTROS:
{json.dumps(records, ensure_ascii=False)[:30000]}"""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1},
    }
    
    # Usar solo el modelo que funciona
    model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL).strip()
    if model not in ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-flash-latest", "gemini-pro-latest"]:
        model = "gemini-3.5-flash-lite"
    
    url = GEMINI_API_URL.format(model=model)
    last_error = None
    for attempt in range(max_retries):
        try:
            response = requests.post(url, params={"key": api_key}, json=payload, timeout=timeout)
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 30
                    print(f"Rate limit (429), esperando {delay} segundos...")
                    time.sleep(min(delay, 60))
                    continue
            if response.status_code >= 500:
                if attempt < max_retries - 1:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 2 ** attempt
                    time.sleep(min(delay, 30))
                    continue
            if response.status_code == 404:
                raise GeminiServiceError(f"Modelo {model} no encontrado")
            response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            print(f"Respuesta de Gemini (primeros 500 caracteres): {text[:500]}")
            result = _extract_json(text)
            print(f"JSON extraído: {result}")
            print(f"Tipo de result: {type(result)}")
            print(f"Claves en result: {result.keys() if isinstance(result, dict) else 'no es dict'}")
            comparisons = result.get("comparaciones") if isinstance(result, dict) else None
            print(f"Tipo de comparisons: {type(comparisons)}")
            if not isinstance(comparisons, list):
                print(f"ERROR: 'comparisons' no es una lista, es: {type(comparisons)}")
                raise GeminiServiceError("Gemini no devolvió una lista comparativa válida")
            print(f"Éxito con modelo: {model}")
            return comparisons
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError, GeminiServiceError) as exc:
            last_error = exc
            if attempt < max_retries - 1 and isinstance(exc, requests.RequestException):
                time.sleep(min(5 * (attempt + 1), 30))
                continue
            break
    raise GeminiServiceError(str(last_error or "No fue posible comparar los artículos"))


def ask_question_about_comparison(articles, comparisons, question, model=None, timeout=60, max_retries=3):
    """Responde una pregunta basada en el análisis comparativo de los artículos"""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise GeminiServiceError("La variable GEMINI_API_KEY no está configurada")

    if not articles or not comparisons:
        raise GeminiServiceError("Se necesitan artículos y comparaciones para responder preguntas")

    # Construir contexto con la información de los artículos y las comparaciones
    articles_context = []
    for i, article in enumerate(articles, 1):
        articles_context.append(f"""
Artículo {i}:
- Título: {article.get('titulo', 'No disponible')}
- Autores: {article.get('autores', 'No disponible')}
- Año: {article.get('anio', 'No disponible')}
""")

    comparisons_context = []
    for comp in comparisons:
        comparisons_context.append(f"""
Aspecto: {comp.get('aspecto', 'N/A')}
Semejanzas: {comp.get('semejanzas', 'N/A')}
Diferencias: {comp.get('diferencias', 'N/A')}
Conclusión: {comp.get('conclusion', 'N/A')}
""")

    prompt = f"""Basándote EXCLUSIVAMENTE en la siguiente información de artículos científicos y su análisis comparativo, responde a la pregunta del usuario.

INFORMACIÓN DE LOS ARTÍCULOS:
{''.join(articles_context)}

ANÁLISIS COMPARATIVO:
{''.join(comparisons_context)}

PREGUNTA DEL USUARIO:
{question}

INSTRUCCIONES:
1. Responde SOLO con la información proporcionada en los artículos y el análisis comparativo
2. Si la información no está disponible en los datos proporcionados, indícalo claramente diciendo "No hay información disponible en los artículos sobre este aspecto"
3. NO inventes ni supongas información que no esté en los datos
4. Sé conciso y directo en tu respuesta
5. Si necesitas información adicional que no está en los datos, menciona qué datos faltan"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3},
    }

    model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL).strip()
    if model not in ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-flash-latest", "gemini-pro-latest"]:
        model = "gemini-3.5-flash-lite"

    url = GEMINI_API_URL.format(model=model)
    last_error = None

    for attempt in range(max_retries):
        try:
            response = requests.post(url, params={"key": api_key}, json=payload, timeout=timeout)
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 30
                    print(f"Rate limit (429), esperando {delay} segundos...")
                    time.sleep(min(delay, 60))
                    continue
            if response.status_code >= 500:
                if attempt < max_retries - 1:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 2 ** attempt
                    time.sleep(min(delay, 30))
                    continue
            if response.status_code == 404:
                raise GeminiServiceError(f"Modelo {model} no encontrado")
            response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            print(f"Éxito respondiendo pregunta con modelo: {model}")
            return text.strip()
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError, GeminiServiceError) as exc:
            last_error = exc
            if attempt < max_retries - 1 and isinstance(exc, requests.RequestException):
                time.sleep(min(2 ** attempt, 30))
                continue
            break

    raise GeminiServiceError(str(last_error or "No fue posible responder la pregunta"))
