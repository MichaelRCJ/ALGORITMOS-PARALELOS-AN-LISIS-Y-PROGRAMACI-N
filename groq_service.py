import os
import json

GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b").strip()

def get_groq_key():
    return os.environ.get("GROQ_API_KEY", "").strip()


def expand_query_with_groq(query, model=None):
    key = get_groq_key()
    model = model or GROQ_MODEL
    
    try:
        from groq import Groq
    except ImportError:
        raise RuntimeError("La librería groq no está instalada. Ejecute: pip install groq")
    
    client = Groq(api_key=key)
    prompt = f"""Devuelve exclusivamente una consulta académica breve para buscar literatura científica.
Tema original: {query}
Incluye sinónimos útiles en español e inglés unidos con OR. No inventes títulos, autores ni DOI.
Máximo 45 palabras."""
    
    out = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=160,
    )
    return out.choices[0].message.content.strip().strip('"')


def analyze_with_groq(articles, model=None):
    key = get_groq_key()
    model = model or GROQ_MODEL
    
    try:
        from groq import Groq
    except ImportError:
        raise RuntimeError("La librería groq no está instalada. Ejecute: pip install groq")
    
    client = Groq(api_key=key)
    
    records = []
    for article in articles[:30]:
        records.append({
            "titulo": article.get("titulo", ""),
            "autores": article.get("autores", ""),
            "anio": article.get("anio", ""),
            "revista": article.get("revista", ""),
            "doi": article.get("doi", ""),
            "resumen": article.get("resumen", "") or article.get("abstract", "")
        })
    
    prompt = "Analiza únicamente estos metadatos reales. En español, identifica tendencias, vacíos y 5 artículos prioritarios con su DOI. Declara limitaciones si faltan resúmenes:\n" + json.dumps(records, ensure_ascii=False)[:24000]
    
    ans = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=1200
    )
    return ans.choices[0].message.content


def analyze_category_with_groq(articles, category_description, model=None):
    key = get_groq_key()
    model = model or GROQ_MODEL
    
    try:
        from groq import Groq
    except ImportError:
        raise RuntimeError("La librería groq no está instalada. Ejecute: pip install groq")
    
    client = Groq(api_key=key)
    
    records = []
    for article in articles[:20]:
        records.append({
            "titulo": article.get("titulo", ""),
            "autores": article.get("autores", ""),
            "anio": article.get("anio", ""),
            "revista": article.get("revista", ""),
            "doi": article.get("doi", ""),
            "resumen": article.get("resumen", "") or article.get("abstract", "")
        })
    
    prompt = f"""Analiza estos artículos académicos enfocándote específicamente en: {category_description}

Genera:
1. Un párrafo académico coherente (150-200 palabras) que sintetice los hallazgos principales
2. Referencias en formato APA 7 para los artículos más relevantes

Datos:\n""" + json.dumps(records, ensure_ascii=False)[:24000]
    
    ans = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=1500
    )
    return ans.choices[0].message.content
