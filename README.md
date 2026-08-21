# Buscador Científico Inteligente

Interfaz web futurista para consultar OpenAlex y Crossref, filtrar por tema, período e idioma, exigir DOI o URL, y exportar resultados.

## 🚀 Despliegue Web

### Despliegue en Vercel

1. **Instalar Vercel CLI** (opcional):
   ```bash
   npm install -g vercel
   ```

2. **Desplegar desde el directorio del proyecto**:
   ```bash
   vercel
   ```
   
   O si prefieres usar el dashboard:
   - Ve a [vercel.com](https://vercel.com)
   - Importa tu repositorio de GitHub
   - Vercel detectará automáticamente que es un proyecto Python
   - Configura las variables de entorno si es necesario
   - Haz clic en "Deploy"

3. **Variables de entorno** (opcional):
   - `PORT`: 5000 (configurado por defecto)

4. **Tu aplicación estará disponible** en un URL como:
   ```
   https://tu-proyecto.vercel.app
   ```

### Despliegue Local

```bash
# Clonar el repositorio
git clone https://github.com/MichaelRCJ/ALGORITMOS-PARALELOS-AN-LISIS-Y-PROGRAMACI-N.git
cd ALGORITMOS-PARALELOS-AN-LISIS-Y-PROGRAMACI-N

# Instalar dependencias
pip install -r requirements.txt

# Ejecutar la aplicación
python app.py
```

La aplicación estará disponible en `http://localhost:5000`

## 📋 Características

- **Búsqueda en OpenAlex y Crossref** simultáneamente
- **Filtros avanzados**: año, idioma, DOI/URL
- **Exportación a Excel** de resultados
- **Descarga de PDFs** de acceso abierto
- **Interfaz futurista-académica** con diseño moderno
- **Estadísticas en tiempo real** de resultados

## 🛠️ Instalación Local

```bash
# Clonar el repositorio
git clone https://github.com/MichaelRCJ/ALGORITMOS-PARALELOS-AN-LISIS-Y-PROGRAMACI-N.git
cd ALGORITMOS-PARALELOS-AN-LISIS-Y-PROGRAMACI-N

# Instalar dependencias
pip install -r requirements.txt

# Ejecutar la aplicación
python app.py
```

La aplicación estará disponible en `http://localhost:5000`

## 📦 Dependencias

- Flask 3.0.0
- Pandas 2.1.4
- Requests 2.31.0
- OpenPyXL 3.1.2
- Gunicorn 21.2.0

## 🔧 Configuración

- **OpenAlex API Key**: Opcional, ingresa en la interfaz si tienes una
- **Puerto**: Por defecto 5000, configurable con variable de entorno `PORT`

## 📄 Licencia

Este proyecto es de código abierto para uso académico.
