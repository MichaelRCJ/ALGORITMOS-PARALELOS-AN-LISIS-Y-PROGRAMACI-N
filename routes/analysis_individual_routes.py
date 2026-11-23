import re
import threading
import time
import uuid
from datetime import datetime

import pandas as pd
from flask import Blueprint, jsonify, render_template, request, send_file

from utils.api_clients import buscar_crossref_simple, buscar_openalex_simple
from exports.export_individual import (
    export_individual_csv,
    export_individual_excel,
    export_individual_pdf,
    export_individual_word,
)
from services.gemini_service import analyze_article, compare_articles


individual_bp = Blueprint("analysis_individual", __name__, url_prefix="/analysis-individual")
JOBS = {}
JOBS_LOCK = threading.Lock()

FIELDS = {
    "titulo": ("titulo", "title"),
    "abstract": ("abstract", "resumen"),
    "autores": ("authors", "autor", "autores", "author"),
    "anio": ("año", "anio", "year"),
    "doi": ("doi",),
}
ANALYSIS_FIELDS = (
    "objetivo", "problema", "metodologia", "tecnicas", "herramientas",
    "resultados", "hallazgos", "limitaciones", "contribuciones", "palabras_clave",
)
DEFAULT_ANALYSIS_FIELDS = list(ANALYSIS_FIELDS)


def _normalize_column(value):
    value = str(value or "").strip().lower()
    return re.sub(r"[áàäâ]", "a", value).replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")


def _find_columns(columns):
    normalized = {_normalize_column(column): column for column in columns}
    found = {}
    for field, aliases in FIELDS.items():
        for alias in aliases:
            candidate = normalized.get(_normalize_column(alias))
            if candidate is not None:
                found[field] = candidate
                break
    return found


def _text(value):
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _fallback_comparison(articles, selected_fields):
    stopwords = {
        "para", "como", "los", "las", "una", "uno", "del", "con", "por", "que", "sus",
        "sobre", "entre", "desde", "este", "esta", "más", "menos", "artículo", "información",
        "disponible", "no", "se", "en", "de", "y", "o", "el", "la", "un", "al", "es",
    }
    comparisons = []
    for field in selected_fields:
        tokens_by_article = []
        for article in articles:
            value = _text(article.get(field, ""))
            tokens = {word.lower() for word in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]{5,}", value) if word.lower() not in stopwords}
            if tokens:
                tokens_by_article.append(tokens)
        common = set.intersection(*tokens_by_article) if len(tokens_by_article) > 1 else set()
        common_text = ", ".join(sorted(common)[:8])
        authors = "; ".join(
            f"{article.get('autores') or 'Autor no indicado'} ({article.get('titulo', '')})"
            for article in articles
        )
        comparisons.append({
            "aspecto": field,
            "articulos_autores": authors,
            "semejanzas": f"Términos compartidos en los registros: {common_text}." if common_text else "No se detectó coincidencia textual suficiente entre los registros.",
            "diferencias": "Los artículos presentan contenidos específicos diferentes; se requiere una respuesta de Gemini para describir diferencias conceptuales con mayor precisión.",
            "conclusion": "Comparación local generada con los análisis disponibles porque Gemini alcanzó temporalmente el límite de solicitudes.",
        })
    return comparisons


def _fallback_analysis(article, selected_fields):
    """Extrae evidencia textual del resumen cuando Gemini está temporalmente limitado."""
    abstract = _text(article.get("abstract", ""))
    if not abstract:
        return {
            field: "El registro no incluye resumen; se requiere consultar el texto completo del artículo para determinar este aspecto con mayor precisión."
            for field in selected_fields
        }
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", abstract) if part.strip()]
    keywords = {
        "objetivo": ("objetivo", "propósito", "purpose", "aim", "evaluar", "analizar"),
        "problema": ("problema", "necesidad", "limitación", "problem", "challenge"),
        "metodologia": ("método", "metodología", "estudio", "revisión", "method", "study"),
        "tecnicas": ("técnica", "análisis", "búsqueda", "simulación", "technique", "analysis"),
        "herramientas": ("software", "herramienta", "base de datos", "platform", "tool"),
        "resultados": ("resultado", "se encontró", "mostró", "demostró", "result", "found"),
        "hallazgos": ("hallazgo", "evidencia", "concluye", "indica", "evidence", "suggest"),
        "limitaciones": ("limitación", "limitada", "falta", "limitation", "lack"),
        "contribuciones": ("contribuye", "aporte", "propone", "contribution", "propose"),
        "palabras_clave": (),
    }
    fallback = {}
    for field in selected_fields:
        matches = [sentence for sentence in sentences if any(word in sentence.lower() for word in keywords.get(field, ()))]
        if field == "palabras_clave":
            fallback[field] = "Extraer del resumen disponible: " + "; ".join(sentences[:2])[:300]
        elif matches:
            fallback[field] = "Según el resumen: " + " ".join(matches[:2])[:600]
        else:
            fallback[field] = "El resumen disponible no detalla explícitamente este aspecto; el análisis se basa en la evidencia parcial del registro y se recomienda consultar el texto completo del artículo para mayor profundidad."
    return fallback


def _split_authors(value):
    """Separa una cadena de autores en nombres individuales."""
    parts = re.split(r"[;|•\n]+|\s+(?:&|y)\s+", str(value or ""))
    names = []
    for part in parts:
        name = re.sub(r"\s+", " ", part).strip().strip(".")
        if name and len(name) > 2 and not name.lower().startswith(("and ", "et al")):
            names.append(name)
    return names


def _unique_authors(articles, limit=300):
    """Autores únicos en orden de aparición, sin duplicados (sin acentos/mayúsculas)."""
    seen = set()
    authors = []
    for article in articles:
        for name in _split_authors(article.get("autores", "")):
            key = _normalize_column(name)
            if key and key not in seen:
                seen.add(key)
                authors.append(name)
                if len(authors) >= limit:
                    return authors
    return authors


def _articles_from_dataframe(dataframe):
    columns = _find_columns(dataframe.columns)
    articles = []
    for _, row in dataframe.iterrows():
        article = {field: _text(row.get(column, "")) if column else "" for field, column in columns.items()}
        if article.get("titulo"):
            articles.append(article)
    return articles, columns


def _enrich_article(article):
    """Completa metadatos ausentes consultando fuentes bibliográficas públicas."""
    if article.get("abstract") and article.get("autores") and article.get("anio"):
        return article

    title = article.get("titulo", "").strip()
    if not title:
        return article

    candidates = []
    try:
        candidates.extend(buscar_openalex_simple(title, cantidad=3))
    except Exception:
        pass
    try:
        candidates.extend(buscar_crossref_simple(title, cantidad=3))
    except Exception:
        pass
    if not candidates:
        return article

    normalized_title = _normalize_column(title)
    best = next(
        (candidate for candidate in candidates if _normalize_column(candidate.get("titulo")) == normalized_title),
        candidates[0],
    )
    enriched = dict(article)
    for key in ("abstract", "autores", "anio", "doi"):
        if not enriched.get(key) and best.get(key):
            enriched[key] = best[key]
    return enriched


def _new_job(articles):
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "ready",
            "total": len(articles),
            "completed": 0,
            "started_at": None,
            "finished_at": None,
            "current_title": "",
            "results": [],
            "errors": [],
            "articles": articles,
        }
    return job_id


def _run_analysis(job_id, batch_size=3):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job["status"] = "running"
        job["started_at"] = time.time()
        articles = list(job["articles"])
        selected_fields = list(job.get("selected_fields") or DEFAULT_ANALYSIS_FIELDS)

    try:
        for start in range(0, len(articles), batch_size):
            batch = articles[start:start + batch_size]
            for article in batch:
                with JOBS_LOCK:
                    JOBS[job_id]["current_title"] = article.get("titulo", "")
                try:
                    analysis = analyze_article(article, selected_fields=selected_fields)
                    result = {**article, **analysis}
                except Exception as exc:
                    result = {**article, **_fallback_analysis(article, selected_fields), "error": str(exc)}
                    with JOBS_LOCK:
                        JOBS[job_id]["errors"].append({"titulo": article.get("titulo", ""), "error": str(exc)})
                with JOBS_LOCK:
                    JOBS[job_id]["results"].append(result)
                    JOBS[job_id]["completed"] += 1
    finally:
        with JOBS_LOCK:
            if job_id in JOBS:
                JOBS[job_id]["status"] = "completed"
                JOBS[job_id]["finished_at"] = time.time()
                JOBS[job_id]["current_title"] = ""
                JOBS[job_id].pop("articles", None)


def _status_payload(job):
    elapsed = 0
    if job["started_at"]:
        elapsed = (job["finished_at"] or time.time()) - job["started_at"]
    rate = job["completed"] / elapsed if elapsed and job["completed"] else 0
    remaining = (job["total"] - job["completed"]) / rate if rate else None
    return {
        "status": job["status"],
        "total": job["total"],
        "completed": job["completed"],
        "percent": round(job["completed"] * 100 / job["total"], 1) if job["total"] else 100,
        "estimated_seconds": round(remaining) if remaining is not None else None,
        "current_title": job.get("current_title", ""),
        "errors": job["errors"],
        "results": job["results"],
    }


@individual_bp.route("/")
def index():
    return render_template("analysis_individual.html")


@individual_bp.route("/load_excel", methods=["POST"])
def load_excel():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify({"error": "Selecciona un archivo Excel"}), 400
    if not uploaded.filename.lower().endswith((".xlsx", ".xls")):
        return jsonify({"error": "El archivo debe tener extensión .xlsx o .xls"}), 400

    try:
        dataframe = pd.read_excel(uploaded)
        if dataframe.empty:
            return jsonify({"error": "El Excel está vacío"}), 400
        articles, columns = _articles_from_dataframe(dataframe)
        if "titulo" not in columns:
            return jsonify({"error": "El Excel debe incluir una columna Título o Title"}), 400
        if not articles:
            return jsonify({"error": "No se encontraron registros con título"}), 400
        job_id = _new_job(articles)
        return jsonify({
            "success": True,
            "job_id": job_id,
            "total": len(articles),
            "columns": list(dataframe.columns),
            "recognized": columns,
            "authors": _unique_authors(articles),
        })
    except Exception as exc:
        return jsonify({"error": f"Error leyendo Excel: {exc}"}), 500


@individual_bp.route("/start", methods=["POST"])
def start_analysis():
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id", "")
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({"error": "La carga de Excel no existe o expiró"}), 404
        if job["status"] == "running":
            return jsonify({"success": True, "message": "El análisis ya está en ejecución"})
        if job["status"] == "completed":
            return jsonify({"success": True, "message": "El análisis ya fue completado"})
        selected_fields = [field for field in data.get("selected_fields", DEFAULT_ANALYSIS_FIELDS) if field in ANALYSIS_FIELDS]
        if not selected_fields:
            return jsonify({"error": "Selecciona al menos un aspecto para analizar"}), 400
        query = _text(data.get("query", "")).lower()
        year_from = _text(data.get("year_from", ""))
        year_to = _text(data.get("year_to", ""))
        try:
            year_from = int(year_from) if year_from else None
            year_to = int(year_to) if year_to else None
        except ValueError:
            return jsonify({"error": "El rango de años no es válido"}), 400
        selected_authors = [
            _normalize_column(author)
            for author in data.get("authors", [])
            if _normalize_column(author)
        ]
        filtered = []
        for article in job["articles"]:
            article_text = " ".join(str(article.get(key, "")) for key in ("titulo", "abstract", "autores")).lower()
            try:
                article_year = int(float(article.get("anio"))) if article.get("anio") else None
            except (TypeError, ValueError):
                article_year = None
            if query and query not in article_text:
                continue
            if year_from and (article_year is None or article_year < year_from):
                continue
            if year_to and (article_year is None or article_year > year_to):
                continue
            if selected_authors:
                article_authors = _normalize_column(article.get("autores", ""))
                if not any(author in article_authors for author in selected_authors):
                    continue
            filtered.append(article)
        if not filtered:
            return jsonify({"error": "Ningún artículo coincide con los filtros seleccionados"}), 400
        job["articles"] = filtered
        job["total"] = len(filtered)
        job["selected_fields"] = selected_fields
    threading.Thread(target=_run_analysis, args=(job_id,), daemon=True).start()
    return jsonify({"success": True, "message": "Análisis individual iniciado"})


@individual_bp.route("/status/<job_id>", methods=["GET"])
def analysis_status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({"error": "El análisis no existe o expiró"}), 404
        return jsonify(_status_payload(job))


@individual_bp.route("/compare", methods=["POST"])
def compare():
    data = request.get_json(silent=True) or {}
    articles = data.get("results", [])
    selected_fields = data.get("selected_fields", DEFAULT_ANALYSIS_FIELDS)
    if not articles:
        return jsonify({"error": "Primero genera los análisis individuales"}), 400
    try:
        comparisons = compare_articles(articles, selected_fields)
        return jsonify({"success": True, "comparisons": comparisons, "source": "gemini"})
    except Exception as exc:
        if "429" in str(exc) or "Too Many Requests" in str(exc):
            return jsonify({"success": True, "comparisons": _fallback_comparison(articles, selected_fields), "source": "local", "notice": "Comparación local generada por límite temporal de Gemini."})
        return jsonify({"error": f"Error comparando artículos: {exc}"}), 500


@individual_bp.route("/export/<format_type>", methods=["POST"])
def export_analysis(format_type):
    data = request.get_json(silent=True) or {}
    results = data.get("results", [])
    if not results:
        return jsonify({"error": "No hay análisis para exportar"}), 400

    exporters = {
        "excel": (export_individual_excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "analisis_individual.xlsx"),
        "csv": (export_individual_csv, "text/csv; charset=utf-8", "analisis_individual.csv"),
        "word": (export_individual_word, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "analisis_individual.docx"),
        "pdf": (export_individual_pdf, "application/pdf", "analisis_individual.pdf"),
    }
    exporter = exporters.get(format_type)
    if not exporter:
        return jsonify({"error": "Formato no soportado"}), 400
    try:
        output = exporter[0](results)
        return send_file(output, mimetype=exporter[1], as_attachment=True, download_name=exporter[2])
    except Exception as exc:
        return jsonify({"error": f"Error exportando resultados: {exc}"}), 500
