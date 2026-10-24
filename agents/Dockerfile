# PlainPath agents (Navigator, Crawler, Answer, Form in one Bureau). Build context: repo root.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
COPY agents/requirements.txt agents/requirements.txt
RUN pip install --no-cache-dir -r agents/requirements.txt

COPY backend backend
COPY agents agents

CMD ["python", "agents/run_all.py"]
