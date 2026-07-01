FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend /app/backend
COPY workers /app/workers

ENV PYTHONPATH=/app/backend:/app
WORKDIR /app/backend

CMD ["celery", "-A", "workers.tasks:celery_app", "worker", "--loglevel=info", "--concurrency=2"]
