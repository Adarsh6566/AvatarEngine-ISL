# Backend — production image
FROM python:3.13-slim AS backend
WORKDIR /app
# System deps for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY config.yaml ./
EXPOSE 8000
ENV BACKEND_HOST=0.0.0.0 BACKEND_PORT=8000 LOG_LEVEL=INFO
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fs http://127.0.0.1:8000/ready || exit 1
CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
