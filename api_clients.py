import re
import os
import time
import unicodedata
import requests
import pandas as pd

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "ScientificSearch/1.0 (academic metadata client)"})


def clean_doi(value):
    if not value:
        return ""
    value = str(value).strip()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value, flags=re.I)
    return value.strip()


def norm(text):
    text = unicodedata.normalize("NFKD", str(text or ""))
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).lower().split())


def reconstruct_abstract(index):
    if not index:
        return ""
    words = []
    for word, positions in index.items():
        words.extend((p, word) for p in positions)
    return " ".join(w for _, w in sorted(words))


def search_openalex(query, y0, y1, lang, limit, api_key=None):
    filters = [f"from_publication_date:{y0}-01-01", f"to_publication_date:{y1}-12-31"]
    if lang:
        filters.append(f"language:{lang}")
    params = {
        "search": query,
        "filter": ",".join(filters),
        "per-page": min(int(limit), 100),
        "sort": "relevance_score:desc",
    }
    if api_key:
        params["api_key"] = api_key
    
    # Retry logic with exponential backoff for rate limiting
    max_retries = 3
    for attempt in range(max_retries):
        try:
            r = SESSION.get("https://api.openalex.org/works", params=params, timeout=35)
            r.raise_for_status()
            break
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429 and attempt < max_retries - 1:
                wait_time = 2 ** attempt
                time.sleep(wait_time)
                continue
            raise
    rows = []
    for x in r.json().get("results", []):
        best = x.get("best_oa_location") or {}
        primary = x.get("primary_location") or {}
        source = primary.get("source") or {}
        doi = clean_doi(x.get("doi"))
        landing = best.get("landing_page_url") or primary.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else x.get("id", ""))
        pdf = best.get("pdf_url") or ""
        authors = "; ".join(a.get("author", {}).get("display_name", "") for a in x.get("authorships", []))
        rows.append({
            "titulo": x.get("title", ""), "autores": authors,
            "anio": x.get("publication_year"), "idioma": x.get("language") or "",
            "revista": source.get("display_name", ""), "doi": doi, "url": landing or "",
            "pdf_oa": pdf, "acceso_abierto": bool((x.get("open_access") or {}).get("is_oa")),
            "citas": x.get("cited_by_count", 0), "fuente": "OpenAlex",
            "resumen": reconstruct_abstract(x.get("abstract_inverted_index")),
        })
    return rows


def search_crossref(query, y0, y1, lang, limit):
    params = {
        "query.bibliographic": query,
        "filter": f"from-pub-date:{y0}-01-01,until-pub-date:{y1}-12-31,type:journal-article",
        "rows": min(int(limit), 100),
    }
    r = SESSION.get("https://api.crossref.org/works", params=params, timeout=35)
    r.raise_for_status()
    rows = []
    for x in r.json().get("message", {}).get("items", []):
        item_lang = x.get("language", "")
        if lang and item_lang and item_lang.lower() != lang:
            continue
        parts = ((x.get("published") or {}).get("date-parts") or [[None]])[0]
        year = parts[0] if parts else None
        authors = "; ".join(" ".join(filter(None, [a.get("given"), a.get("family")])) for a in x.get("author", []))
        links = x.get("link") or []
        pdf = next((z.get("URL", "") for z in links if "pdf" in (z.get("content-type") or "").lower()), "")
        doi = clean_doi(x.get("DOI"))
        rows.append({
            "titulo": " ".join(x.get("title") or []), "autores": authors,
            "anio": year, "idioma": item_lang, "revista": " ".join(x.get("container-title") or []),
            "doi": doi, "url": x.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
            "pdf_oa": pdf, "acceso_abierto": bool(pdf), "citas": x.get("is-referenced-by-count", 0),
            "fuente": "Crossref", "resumen": re.sub("<[^>]+>", " ", x.get("abstract", "")),
        })
    return rows


def dedupe(rows):
    seen, out = set(), []
    for r in rows:
        key = ("doi", r["doi"].lower()) if r.get("doi") else ("title", norm(r.get("titulo")))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def limpiar_texto(valor):
    if valor is None:
        return ""
    if pd.isna(valor):
        return ""
    texto = str(valor)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def formatear_autores_openalex(authorships):
    autores = []
    for item in authorships or []:
        autor = item.get("author", {})
        nombre = autor.get("display_name", "")
        if nombre:
            autores.append(nombre)
    return autores


def buscar_openalex_simple(consulta, anio_desde=2020, anio_hasta=2026, cantidad=10):
    params = {
        "search": consulta,
        "filter": f"from_publication_date:{anio_desde}-01-01,to_publication_date:{anio_hasta}-12-31",
        "per-page": cantidad,
        "sort": "relevance_score:desc"
    }
    api_key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if api_key:
        params["api_key"] = api_key

    try:
        respuesta = SESSION.get("https://api.openalex.org/works", params=params, timeout=30)
        respuesta.raise_for_status()
        data = respuesta.json()
    except Exception as e:
        print("Error OpenAlex:", e)
        return []
    
    resultados = []
    for item in data.get("results", []):
        titulo = limpiar_texto(item.get("title"))
        if not titulo:
            continue
        autores = formatear_autores_openalex(item.get("authorships"))
        doi = item.get("doi") or ""
        url = doi if doi else item.get("id", "")
        abstract = reconstruct_abstract(item.get("abstract_inverted_index"))
        primary_location = item.get("primary_location") or {}
        source = primary_location.get("source") or {}
        revista = source.get("display_name", "")
        anio = item.get("publication_year", "")
        citas = item.get("cited_by_count", 0)
        resultados.append({
            "titulo": titulo,
            "autores": autores,
            "anio": anio,
            "revista": revista,
            "doi": doi,
            "url": url,
            "abstract": abstract,
            "citas": citas,
            "fuente": "OpenAlex"
        })
    return resultados


def buscar_crossref_simple(consulta, anio_desde=2020, anio_hasta=2026, cantidad=10):
    filtros = f"from-pub-date:{anio_desde}-01-01,until-pub-date:{anio_hasta}-12-31"
    params = {
        "query.bibliographic": consulta,
        "filter": filtros,
        "rows": cantidad,
        "select": "DOI,title,author,published,container-title,URL,abstract"
    }
    headers = {"User-Agent": "BuscadorCientificoIA/2.0"}
    try:
        respuesta = SESSION.get("https://api.crossref.org/works", params=params, headers=headers, timeout=30)
        respuesta.raise_for_status()
        data = respuesta.json()
    except Exception as e:
        print("Error Crossref:", e)
        return []
    
    resultados = []
    for item in data.get("message", {}).get("items", []):
        titulo_lista = item.get("title", [])
        titulo = ""
        if titulo_lista:
            titulo = limpiar_texto(titulo_lista[0])
        if not titulo:
            continue
        autores = []
        for autor in item.get("author", []):
            nombre = f"{autor.get('given', '')} {autor.get('family', '')}".strip()
            if nombre:
                autores.append(nombre)
        fecha = item.get("published", {})
        partes = fecha.get("date-parts", [[]])
        anio = ""
        if partes and partes[0]:
            anio = partes[0][0]
        revistas = item.get("container-title", [])
        revista = ""
        if revistas:
            revista = limpiar_texto(revistas[0])
        doi = item.get("DOI", "")
        url = item.get("URL", "")
        if doi:
            url = f"https://doi.org/{doi}"
        abstract = limpiar_texto(item.get("abstract", ""))
        abstract = re.sub(r"<[^>]+>", " ", abstract)
        resultados.append({
            "titulo": titulo,
            "autores": autores,
            "anio": anio,
            "revista": revista,
            "doi": doi,
            "url": url,
            "abstract": abstract,
            "citas": 0,
            "fuente": "Crossref"
        })
    return resultados


def deduplicar_fuentes(fuentes):
    resultado = []
    vistos = set()
    for fuente in fuentes:
        doi = limpiar_texto(fuente.get("doi")).lower()
        titulo = limpiar_texto(fuente.get("titulo")).lower()
        clave = doi if doi else titulo
        if not clave or clave in vistos:
            continue
        vistos.add(clave)
        resultado.append(fuente)
    return resultado
