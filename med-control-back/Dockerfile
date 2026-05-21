FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
  gcc \
  && rm -rf /var/lib/apt/lists/*

# Copiar requirements
COPY requirements.txt .

# Instalar dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY core/ ./core/
COPY api/ ./api/

# Crear directorios necesarios
RUN mkdir -p uploads historiales

# Exponer puerto (Railway inyecta $PORT en runtime)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/health')"

# Railway inyecta $PORT; usar shell form para que se expanda la variable
CMD uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
