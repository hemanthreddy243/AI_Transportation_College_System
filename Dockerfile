# --- 1. build the React frontend ---
FROM node:20-alpine AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- 2. Python backend that also serves the built frontend ---
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=web /app/frontend/dist /app/frontend/dist
# Render sets $PORT; 8000 for local `docker run -p 8000:8000`
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
