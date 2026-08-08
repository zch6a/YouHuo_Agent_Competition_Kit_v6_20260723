FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    YOUHUO_DB_PATH=/app/data/youhuo.db \
    YOUHUO_DEMO_MODE=true

WORKDIR /app

RUN useradd --create-home --uid 10001 youhuo
COPY requirements.lock.txt /app/requirements.lock.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /app/requirements.lock.txt

COPY --chown=youhuo:youhuo backend /app/backend
COPY --chown=youhuo:youhuo xiaoyi /app/xiaoyi
RUN mkdir -p /app/data && chown -R youhuo:youhuo /app/data

USER youhuo
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()" || exit 1

CMD ["python", "-m", "uvicorn", "youhuo.api:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "backend"]
