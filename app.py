from flask import Flask, render_template, request, jsonify, send_file
import os, re, io, json, time, html, zipfile, unicodedata
from pathlib import Path
import pandas as pd
import requests

app = Flask(__name__)

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
    r = SESSION.get("https://api.openalex.org/works", params=params, timeout=35)
    r.raise_for_status()
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
        "select": "DOI,title,author,published,language,container-title,URL,link,is-referenced-by-count,abstract",
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
    
    df = pd.DataFrame(results)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Artículos')
    output.seek(0)
    
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
