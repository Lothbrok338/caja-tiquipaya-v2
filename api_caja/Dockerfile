# Contexto de build = raíz del repo. En Railway: RAILWAY_DOCKERFILE_PATH=api_caja/Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY api_caja/requirements.txt /app/api_caja/requirements.txt
RUN pip install --no-cache-dir -r api_caja/requirements.txt
COPY *.py /app/
COPY api_caja /app/api_caja
CMD ["sh", "-c", "uvicorn api_caja.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
