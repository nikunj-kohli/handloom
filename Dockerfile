# ---- stage 1: build the frontend ----
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- stage 2: runtime ----
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HANDOVER_DATA_DIR=/app/data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY scripts ./scripts
COPY --from=frontend /app/frontend/dist ./frontend/dist
# Writable data dir for any UID: managed hosts run images as a non-root user.
RUN mkdir -p /app/data && chmod 777 /app/data
EXPOSE 7860
# Managed hosts inject their own PORT; 7860 is the default when none is set.
CMD ["sh", "-c", "exec uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
