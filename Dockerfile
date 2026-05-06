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

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "from pathlib import Path; raise SystemExit(0 if Path('/tmp/spot-bot-ready').exists() else 1)"

CMD ["python", "bot.py"]
