# Serving image: API + built frontend. No Spark / Java needed: gold tables are pre-loaded in SQLite.
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.115.6 "uvicorn[standard]==0.32.1" pandas openpyxl
COPY src/ ./src/
COPY data/serving/aapurti.db ./data/serving/aapurti.db
COPY --from=web /web/dist ./frontend/dist
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["sh", "-c", "uvicorn aapurti.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
