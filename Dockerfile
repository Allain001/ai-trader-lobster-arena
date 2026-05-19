FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV ENVIRONMENT=production

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

COPY service/requirements.txt service/requirements.txt
RUN pip install --no-cache-dir -r service/requirements.txt

COPY service/frontend/package.json service/frontend/package-lock.json service/frontend/
RUN cd service/frontend && npm ci

COPY . .
RUN cd service/frontend && npm run build

WORKDIR /app/service/server

CMD ["sh", "-c", "python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
