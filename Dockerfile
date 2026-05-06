FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH=/data/spot_bot.db

WORKDIR /app

RUN adduser --disabled-password --gecos "" appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

USER appuser

CMD ["python", "bot.py"]
