# Build from the repository root:  docker build -f service/Dockerfile -t command-parser:local .
# No model weights are baked in: the service downloads them from object storage at start-up.
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY service/requirements.txt .
RUN pip install -r requirements.txt
COPY service/app.py .
COPY data/schema.json /app/schema.json
ENV SCHEMA_PATH=/app/schema.json
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
