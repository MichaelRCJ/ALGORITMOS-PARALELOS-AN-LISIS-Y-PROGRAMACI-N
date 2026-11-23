# INFORME DE PROYECTO FINAL — Sistemas Expertos

## Sistema de Búsqueda y Análisis Bibliográfico Científico Asistido por Inteligencia Artificial
**"Michael Search"**

---

## 1. Introducción

El presente informe documenta el desarrollo de un aplicativo web para la búsqueda, recuperación, análisis y síntesis automatizada de literatura científica. El sistema, denominado internamente **"Michael Search"**, integra en una única plataforma dos grandes capacidades:

1. **Búsqueda bibliográfica** en bases de datos académicas abiertas (OpenAlex y Crossref), con normalización de metadatos, deduplicación, filtrado por año/idioma/disponibilidad de DOI y descarga masiva de PDFs de acceso abierto.
2. **Análisis inteligente con IA** organizado en cinco "agentes" especializados que cubren el ciclo completo de una revisión bibliográfica: búsqueda, análisis agrupado por categorías académicas, análisis individual artículo por artículo, comparación entre autores y síntesis final de conclusiones.

La naturaleza del sistema lo acerca a un **sistema experto aplicado al dominio de la bibliotecología computacional**: la "base de conocimiento" está constituida por los metadatos reales de los artículos, las "reglas de inferencia" por los prompts estructurados que gobiernan a los modelos de lenguaje (Gemini y Groq), y el "motor de inferencia" por la orquestación de endpoints Flask que encadena el procesamiento por lotes, el filtrado y la exportación de resultados.

## 2. Objetivo

Diseñar e implementar una herramienta web que permita al investigador:

- Recuperar artículos científicos de fuentes abiertas con metadatos completos (título, autores, año, revista, DOI, resumen, conteo de citas, URL y PDF de acceso abierto).
- Filtrar y exportar resultados en Excel, Word, PDF, CSV y ZIP de PDFs.
- Analizar la literatura por **11 categorías académicas** (antecedentes, modelos, metodologías, métodos, experimentos, réplicas, técnicas, herramientas, resultados, limitaciones y recomendaciones).
- Generar **fichas de análisis individual** por artículo, seleccionando aspectos específicos y filtrando por autores, texto libre y rango de años.
- **Comparar artículos** entre sí y responder preguntas sobre el conjunto analizado.
- Producir un **documento final de conclusiones** integrando todos los análisis previos.

## 3. Materiales

### 3.1 Tecnologías

| Capa | Tecnología | Versión / Detalle |
|---|---|---|
| Lenguaje backend | Python | 3.x |
| Framework web | Flask | 3.0 (`flask==3.0.0` en `requirements.txt`) |
| Procesamiento de datos | pandas + openpyxl | lectura de Excel `.xlsx/.xls` |
| Generación de documentos | python-docx, ReportLab | exportación Word y PDF |
| Lectura de documentos | python-docx, PyPDF2 | extracción de texto de Word/PDF |
| Cliente HTTP | requests | sesión reutilizable con User-Agent propio |
| Configuración | python-dotenv | `.env` (global) y `analysis_api.env` (API dedicada del Agente 2) |
| Frontend | HTML5 + CSS3 + JavaScript | diseño responsive, animaciones, DataTables 2.1.8, jQuery 3.7.1 |

### 3.2 APIs externas utilizadas

| API | Proveedor | Función en el sistema |
|---|---|---|
| OpenAlex | OurResearch | metadatos completos de trabajos científicos, resumen reconstruido desde `abstract_inverted_index`, conteo de citas, flag de acceso abierto |
| Crossref | Crossref | metadatos DOI, autores, fechas, revistas y resúmenes (fallback de OpenAlex) |
| Gemini API | Google | `gemini-3.5-flash-lite` como modelo principal + lista de 10 modelos de respaldo; generación de texto académico estructurado en JSON y Markdown |
| Groq API | Groq | `openai/gpt-oss-20b`; expansión de consultas con sinónimos y análisis complementario |

### 3.3 Estructura del proyecto

```
app.py                        # Aplicación Flask principal, rutas /search, /export, /download_pdfs
routes/
  analysis_routes.py          # Agente 2: análisis por categorías (/analysis/)
  analysis_individual_routes.py  # Agente 3: análisis individual (/analysis-individual/)
  compare_routes.py           # Agente 4: comparación (/compare/)
  conclusion_routes.py        # Agente 5: conclusiones (/conclusion/)
services/
  gemini_service.py           # Cliente Gemini: analyze_article, compare_articles, Q&A
  analysis_window.py          # Lógica del Agente 2 con fallback de modelos
utils/api_clients.py          # Clientes OpenAlex/Crossref, deduplicación, normalización
groq_service.py               # Cliente Groq
exports/                      # Generadores Excel/Word/PDF/CSV
citations.py                  # Generación de referencias APA 7
templates/                    # 5 plantillas HTML (una por agente)
analysis_api.env              # API key dedicada del Agente 2 (ignorada por .gitignore)
```

### 3.4 Arquitectura general

```
┌─────────────┐     HTTP/JSON      ┌──────────────────────────────────────────┐
│  Navegador  │ ◄──────────────► │  Flask (app.py + 4 Blueprints)           │
│  (5 vistas) │                   │                                          │
└─────────────┘                   │  Agente 1: /search  → OpenAlex+Crossref  │
                                  │  Agente 2: /analysis → Gemini (fallback) │
                                  │  Agente 3: /analysis-individual → Gemini│
                                  │  Agente 4: /compare → Gemini             │
                                  │  Agente 5: /conclusion → Gemini          │
                                  └──────┬───────────┬───────────┬───────────┘
                                         │           │           │
                              ┌──────────▼──┐  ┌─────▼─────┐  ┌──▼──────────┐
                              │ OpenAlex /  │  │ Gemini /  │  │  Groq API   │
                              │ Crossref    │  │ Groq APIs │  │ (opcional)  │
                              └─────────────┘  └───────────┘  └─────────────┘
```

El flujo de datos entre agentes es deliberadamente **basado en archivos**: el Agente 1 produce un Excel (`articulos_cientificos.xlsx`); ese mismo archivo alimenta los Agentes 2, 3 y 4; los textos exportados por estos alimentan el Agente 5. Esto desacopla los módulos y permite que cada agente se use de forma independiente.

---

## 4. Desarrollo

### Agente 1 — Motor de búsqueda bibliográfica (`/`)

#### 4.1.1 Qué usó

- **OpenAlex API** (`https://api.openalex.org/works`) como fuente principal.
- **Crossref API** (`https://api.crossref.org/works`) como fuente complementaria.
- **Groq API** (opcional) para expansión de la consulta con sinónimos.
- pandas/openpyxl para exportación a Excel; `requests.Session` reutilizable; `zipfile` para empaquetar PDFs.

#### 4.1.2 Cómo funciona

**a) Consulta paralela y normalización de metadatos** (`utils/api_clients.py`)

Cada fuente devuelve estructuras JSON distintas; el código las normaliza a un esquema común:

```python
def search_openalex(query, y0, y1, lang, limit, api_key=None):
    filters = [f"from_publication_date:{y0}-01-01",
               f"to_publication_date:{y1}-12-31"]
    if lang:
        filters.append(f"language:{lang}")
    params = {"search": query, "filter": ",".join(filters),
              "per-page": min(int(limit), 100),
              "sort": "relevance_score:desc"}
    ...
    for x in r.json().get("results", []):
        rows.append({
            "titulo": x.get("title", ""), "autores": authors,
            "anio": x.get("publication_year"), ...,
            "citas": x.get("cited_by_count", 0), "fuente": "OpenAlex",
            "resumen": reconstruct_abstract(x.get("abstract_inverted_index")),
        })
```

Detalle técnico relevante: OpenAlex no entrega el resumen como texto, sino como un **índice invertido** (`abstract_inverted_index`: palabra → posiciones). El sistema lo reconstruye con `reconstruct_abstract()`:

```python
def reconstruct_abstract(index):
    words = []
    for word, positions in index.items():
        words.extend((p, word) for p in positions)
    return " ".join(w for _, w in sorted(words))
```

Crossref entrega el abstract con etiquetas HTML que se eliminan con `re.sub(r"<[^>]+>", " ", ...)`.

**b) Deduplicación** — los mismos artículos aparecen en ambas APIs; se eliminan por DOI (prioridad) o por título normalizado (minúsculas, sin acentos vía `unicodedata.normalize("NFKD")`):

```python
def dedupe(rows):
    seen, out = set(), []
    for r in rows:
        key = ("doi", r["doi"].lower()) if r.get("doi") else ("title", norm(r.get("titulo")))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out
```

**c) Orquestación** (`app.py`, ruta `/search`): consulta ambas APIs capturando errores de forma independiente (si una falla, la otra igual responde), aplica dedupe, filtro opcional `require_doi`, ordena por `(citas, año)` descendente y devuelve máx. 100 resultados más la lista de errores parciales.

**d) Reintentos con backoff exponencial** ante HTTP 429 en OpenAlex:

```python
for attempt in range(max_retries):
    try:
        r = SESSION.get("https://api.openalex.org/works", params=params, timeout=35)
        r.raise_for_status(); break
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429 and attempt < max_retries - 1:
            time.sleep(2 ** attempt); continue
        raise
```

**e) Descarga de PDFs** (`/download_pdfs`): itera resultados, valida que la respuesta sea realmente PDF (`content-type` o firma `%PDF`), sanitiza el nombre del archivo con regex y empaqueta todo en un ZIP en memoria (`io.BytesIO`) sin tocar disco.

#### 4.1.3 Qué hace

Convierte una consulta en lenguaje natural en un conjunto limpio de artículos científicos ordenados por impacto (citas), exportables a Excel y con PDFs descargables. Es la fuente de datos de toda la plataforma.

---

### Agente 2 — Análisis bibliográfico por categorías (`/analysis/`)

#### 4.2.1 Qué usó

- **Google Gemini API** con modelo configurable (`gemini-3.5-flash-lite` por defecto) y **lista de 10 modelos de respaldo** automática.
- API key dedicada en `analysis_api.env` (prioridad sobre `GEMINI_API_KEY` del `.env`).
- pandas para leer el Excel; `services/analysis_window.py` para la lógica.
- Exportación Word/PDF/Excel vía `exports/export_handlers.py`.

#### 4.2.2 Cómo funciona

**a) Base de conocimiento: taxonomía de categorías**

```python
CATEGORIAS = {
    "antecedentes": "antecedentes y contexto de la investigación",
    "modelos": "modelos, arquitecturas, modelos conceptuales o modelos matemáticos",
    "metodologias": "metodologías y enfoques de investigación",
    ...  # 11 categorías en total
}
```

Actúa como la "tabla de reglas" del sistema: cada categoría tiene una descripción semántica que se inyecta en el prompt.

**b) Extracción de artículos y fuentes** — `preparar_articulos_excel(df)` detecta la columna de título por alias (`titulo`/`title`, normalizado sin acentos), toma máximo 12 artículos y extrae autores/año/DOI/abstract por coincidencia de nombres de columna. Las "fuentes" para el análisis son los propios artículos del Excel (evita re-consultar APIs y respetar cuotas).

**c) Ingeniería de prompts** — el corazón del agente. `generar_parrafo_gemini()` construye un prompt que prohíbe invención de datos y exige estructura académica:

```
Reglas clave del prompt:
- Solo español, tono académico formal.
- NO inventar resultados, metodologías, estadísticas, autores ni DOI.
- Citas APA 7 dentro del texto: (Apellido, año) / (Apellido & Apellido, año) / (Apellido et al., año).
- Analizar TODAS las fuentes y relacionarlas entre sí.
- 500–800 palabras.

Formato obligatorio:
## 1. Panorama general
## 2. Análisis de las fuentes
## 3. Coincidencias y discrepancias
## 4. Vacíos y oportunidades de investigación
## 5. Síntesis
## Referencias
```

**d) Resiliencia multinivel** — tres mecanismos encadenados:

1. **Reintentos por modelo**: cada modelo se intenta hasta 2 veces (solo para errores de red/timeout; los errores HTTP pasan directo al siguiente).
2. **Fallback de modelos**: lista ordenada `_MODELOS_FALLBACK` de 11 modelos (`gemini-3.5-flash-lite`, `gemini-3.5-flash`, `gemini-3.1-flash-lite`, `gemini-2.5-flash-lite`, `gemini-2.5-flash`, `gemini-flash-lite-latest`, `gemini-flash-latest`, `gemini-3-flash-preview`, `gemini-3.6/3.7/3.8-flash`). El modelo configurado en `analysis_api.env` se prueba primero.
3. **Timeout amplio**: 120 s por intento (antes 60 s), con `time.sleep(3)` entre reintentos del mismo modelo.

```python
for modelo in _gemini_modelos():
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
    for intento in range(2):
        try:
            response = requests.post(url, params={"key": api_key},
                                     json=payload, timeout=120)
            response.raise_for_status()
            ...
            return text.strip()
        except requests.HTTPError as e:
            ultimo_error = e; break          # siguiente modelo
        except Exception as e:
            ultimo_error = e
            if intento == 0: time.sleep(3)  # reintenta mismo modelo
```

**e) Renderizado** — el frontend convierte el Markdown devuelto por Gemini a HTML con `renderMarkdown()` (escape de HTML primero — seguridad ante inyección — luego `#`→encabezados, `**`→negritas, `-`→listas, `---`→separadores) con estilos propios integrados al tema visual.

#### 4.2.3 Qué hace

Genera por cada categoría seleccionada un análisis narrativo completo de nivel "revisión bibliográfica" (~500–800 palabras) que relaciona las fuentes entre sí, identifica vacíos y produce referencias APA. Procesa las categorías secuencialmente en el cliente para no saturar la API.

---

### Agente 3 — Análisis individual por artículo (`/analysis-individual/`)

#### 4.3.1 Qué usó

- **Google Gemini API** vía `services/gemini_service.py::analyze_article()` — análisis campo por campo en **JSON estructurado**.
- pandas para leer el Excel; **hilos en segundo plano** (`threading.Thread`) con estado en memoria (`JOBS` dict + `threading.Lock`) para procesar sin bloquear el servidor.
- Frontend con DataTables, barra de progreso animada y polling cada 1.2 s.

#### 4.3.2 Cómo funciona

**a) Selección de autores** — al cargar el Excel, el backend extrae autores únicos separando la cadena por `;`, `|`, `•`, saltos de línea, `&` e `y` (`_split_authors`), y los devuelve para que el usuario marque en una tabla cuáles quiere analizar:

```python
def _split_authors(value):
    parts = re.split(r"[;|•\n]+|\s+(?:&|y)\s+", str(value or ""))
    ...

def _unique_authors(articles, limit=300):
    seen, authors = set(), []
    for article in articles:
        for name in _split_authors(article.get("autores", "")):
            key = _normalize_column(name)   # sin acentos, minúsculas
            if key and key not in seen:
                seen.add(key); authors.append(name)
    return authors
```

En `/start`, los filtros se aplican en cadena (texto + años + autores) con coincidencia por substring normalizada:

```python
if selected_authors:
    article_authors = _normalize_column(article.get("autores", ""))
    if not any(author in article_authors for author in selected_authors):
        continue
```

**b) Extracción estructurada con JSON forzado** — el prompt pide a Gemini un objeto JSON con exactamente las claves de los aspectos seleccionados, validado por `_extract_json()` (limpia fences ```` ``` ````, busca el primer `{...}` si hay texto extra y verifica que sea dict):

```python
result = _extract_json(text)
return {key: result.get(key) or MISSING_INFO for key in selected_fields}
```

**c) Prompt de análisis individual** — pide párrafos académicos completos de 2–4 oraciones por aspecto y prohíbe "No disponible": si la evidencia es escasa, el modelo debe inferir prudentemente del título/autores/año/DOI y declarar la limitación.

**d) Procesamiento por lotes con progreso** — `_run_analysis(job_id, batch_size=3)` corre en hilo daemon; el frontend hace polling a `/status/<job_id>` que devuelve `percent`, `completed`, `current_title` (el título del artículo en curso) y `estimated_seconds` calculado por tasa de procesamiento. Si `analyze_article` lanza excepción, se aplica `_fallback_analysis()` local:

```python
sentences = re.split(r"(?<=[.!?])\s+", abstract)
matches = [s for s in sentences if any(w in s.lower() for w in keywords[field])]
fallback[field] = "Según el resumen: " + " ".join(matches[:2])[:600]
```

El fallback usa **coincidencia de palabras clave por aspecto** sobre las oraciones del resumen — un mecanismo de inferencia local que garantiza que la tabla siempre tenga contenido aunque Gemini esté saturado (429).

**e) Manejo de rate-limit en Gemini** (`analyze_article`): ante HTTP 429 respeta el header `Retry-After` (máx. 60 s) y reintenta hasta 3 veces; ante errores 5xx usa backoff exponencial.

#### 4.3.3 Qué hace

Produce la "ficha analítica" de cada artículo: 10 aspectos (objetivo, problema, metodología, técnicas, herramientas, resultados, hallazgos, limitaciones, contribuciones, palabras clave), filtrables por autor/texto/año, exportables a Excel/Word/PDF/CSV y reutilizables por el Agente 4.

---

### Agente 4 — Comparación entre artículos (`/compare/`)

#### 4.4.1 Qué usó

- **Google Gemini API** (`compare_articles` y `ask_question_about_comparison` en `gemini_service.py`).
- SheetJS (CDN) para leer el Excel directamente en el navegador; pandas en el endpoint `/upload`.
- Mismo esquema de campos que el Agente 3 (`FIELD_LABELS`).

#### 4.4.2 Cómo funciona

**a) Completado previo de campos faltantes** — antes de comparar, el endpoint `/compare` detecta qué campos seleccionados están vacíos o valen "No disponible" y ejecuta `analyze_article()` sobre cada artículo solo para esos campos (enriquecimiento selectivo que ahorra llamadas a la API):

```python
missing_fields = [field for field in selected_fields
                  if any(not a.get(field) or a.get(field) == "No disponible"
                         for a in articles)]
if missing_fields:
    articles = [{**a, **analyze_article(a, missing_fields)} for a in articles]
```

**b) Comparación en JSON** — `compare_articles()` envía los registros (recortados a 30 000 caracteres para controlar tokens) y exige una fila por aspecto con la estructura:

```json
{"comparaciones": [{"aspecto": "...", "articulos_autores": "...",
                    "semejanzas": "...", "diferencias": "...",
                    "conclusion": "..."}]}
```

**c) Preguntas y respuestas** — `ask_question_about_comparison()` construye un prompt con el contexto de artículos + comparaciones previas y ordena a Gemini responder **solo con la evidencia entregada**, declarando explícitamente cuando la información no está disponible (anti-alucinación por instrucción).

#### 4.4.3 Qué hace

Genera la tabla comparativa (aspecto × semejanzas × diferencias × conclusión) y un asistente de preguntas sobre el análisis, cerrando el análisis comparativo del conjunto de autores.

---

### Agente 5 — Síntesis y conclusiones (`/conclusion/`)

#### 4.5.1 Qué usó

- **Google Gemini API** (endpoint directo con `gemini-3.5-flash-lite`, timeout 90 s).
- Extracción de texto de documentos: `python-docx` (Word), `PyPDF2` (PDF), `pandas` (Excel → `to_string`).
- Exportación final Word/PDF/Excel combinando conclusiones + anexos.

#### 4.5.2 Cómo funciona

El usuario aporta el análisis individual y la tabla comparativa **de dos formas**: pegando el texto o subiendo los documentos exportados (el sistema extrae el contenido automáticamente). El prompt exige tres secciones — resumen integrado (300–400 palabras), conclusiones (200–300 palabras) y referencias APA consolidadas — con reglas anti-invención y declaración explícita cuando falte información de alguno de los dos insumos. La exportación Word/PDF incluye el documento de conclusiones **más los análisis originales como anexos**.

#### 4.5.3 Qué hace

Es el agente de cierre: integra todas las salidas previas en el documento científico final exportable, replicando la estructura de "discusión y conclusiones" de un artículo.

---

## 5. Mecanismos transversales del sistema

### 5.1 Ingeniería de prompts como base de conocimiento

Los prompts no son simples peticiones: son **especificaciones formales** que definen rol ("investigador académico"), restricciones duras (prohibición de inventar datos, citas APA 7), formato de salida (JSON exacto / Markdown con secciones obligatorias / texto corrido) y políticas de abstención (declarar limitaciones de evidencia). Esta es la pieza que convierte al LLM en un "experto" del dominio bibliográfico.

### 5.2 Resiliencia y tolerancia a fallos

| Mecanismo | Dónde | Estrategia |
|---|---|---|
| Backoff exponencial | OpenAlex (429), Gemini (5xx) | `2**attempt` con tope |
| `Retry-After` | Gemini (429) | respeta header de la API, máx. 60 s |
| Fallback de modelos | Agente 2 | 11 modelos en cascada |
| Fallback algorítmico | Agente 3 | extracción local por keywords del resumen |
| Fallback comparativo | Agente 3 (compare) | comparación local por tokens compartidos ante 429 |
| Errores parciales | Agente 1 | si una API falla, la otra responde y se reporta el error |
| Aislamiento de archivos | `.gitignore` | `analysis_api.env` excluido del repo |

### 5.3 Seguridad

- Escape HTML en todo contenido dinámico del frontend (`escapeHtml`, `renderMarkdown` escapa antes de convertir).
- Validación de extensión de archivo (`.xlsx/.xls`, `.docx`, `.pdf`).
- API keys solo en variables de entorno / archivos `.env` excluidos de git.
- Sanitización de nombres de archivo PDF con regex antes de escribir al ZIP.

### 5.4 Interfaz

Tema visual unificado en las 5 vistas (paleta violeta/fucsia/cian/dorado, tipografía Orbitron + Rajdhani, animaciones, `prefers-reduced-motion`), navegación cruzada entre agentes y exportación contextual en cada pantalla.

## 6. Conclusión

El sistema desarrollado constituye una plataforma integral de revisión bibliográfica asistida por IA, materializada como un sistema experto aplicado: la base de conocimiento son los metadatos bibliográficos reales, las reglas de inferencia son los prompts estructurados y el motor de inferencia es la orquestación Flask con sus mecanismos de resiliencia. Los cinco agentes cubren de extremo a extremo el flujo del investigador — búsqueda, análisis por categorías, fichas individuales, comparación y conclusiones — con exportación a formatos académicos en cada etapa.

Los resultados obtenidos demuestran la viabilidad de combinar APIs bibliográficas abiertas con LLMs para automatizar tareas de revisión bibliográfica que tradicionalmente requieren horas de trabajo manual, manteniendo rigor académico mediante restricciones explícitas en los prompts y mecanismos de respaldo ante fallos de los servicios externos.

**Limitaciones y trabajo futuro:** dependencia de APIs externas (cuotas, disponibilidad), ausencia de caché de respuestas de Gemini (cada ejecución repite llamadas), cobertura limitada a OpenAlex/Crossref (sin Scopus/Web of Science/SciELO), y procesamiento secuencial de lotes que podría paralelizarse. Como líneas futuras se proponen: caché persistente de análisis, más fuentes bibliográficas, despliegue productivo con WSGI y autenticación de usuarios.
