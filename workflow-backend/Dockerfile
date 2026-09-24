FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD python -c "import asyncio; from db import apply_schema; asyncio.run(apply_schema())" && \
    celery -A celery_app worker --loglevel=info
