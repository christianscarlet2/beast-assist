# One image for every Python service; SERVICE picks what runs.
#   docker build -t beast-assist .        then SERVICE=agile-mcp | college-mcp | registry | mock-entra | demo
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 FASTEMBED_CACHE=/models
WORKDIR /app
COPY pyproject.toml ./
COPY libs ./libs
RUN pip install ".[agent]" && useradd -r -u 10001 beast && mkdir /models && chown beast /models
COPY . .
# bake the embedding model into the image so pods start without internet access
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/models')" \
    && chown -R beast /models
USER beast
EXPOSE 8000
ENV SERVICE=agile-mcp
CMD ["sh", "-c", "case $SERVICE in \
  registry) exec uvicorn registry.app:app --host 0.0.0.0 --port 8000 ;; \
  mock-entra) exec uvicorn auth.mock_entra:app --host 0.0.0.0 --port 8000 ;; \
  demo) exec uvicorn demo.app:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*' ;; \
  *-mcp) exec uvicorn --app-dir servers/$SERVICE/src main:app --host 0.0.0.0 --port 8000 ;; \
  *) echo unknown SERVICE $SERVICE; exit 2 ;; esac"]
