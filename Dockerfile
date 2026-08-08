FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    YOUHUO_DB_PATH=/app/data/youhuo.db \
    YOUHUO_DEMO_MODE=true \
    PORT=8000

WORKDIR /app

# uid 1000: Hugging Face Spaces runs Docker containers as that id, and a data
# directory owned by anyone else leaves the app unable to create its database.
RUN useradd --create-home --uid 1000 youhuo
COPY requirements.lock.txt /app/requirements.lock.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /app/requirements.lock.txt

COPY --chown=youhuo:youhuo backend /app/backend
COPY --chown=youhuo:youhuo xiaoyi /app/xiaoyi
RUN mkdir -p /app/data && chown -R youhuo:youhuo /app/data

USER youhuo
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.getenv('PORT','8000')}/health\", timeout=3).read()" || exit 1

# Shell form so $PORT expands: Render, Railway, Fly and Cloud Run all inject the
# port they expect the process to listen on, and a hardcoded 8000 fails health
# checks on every one of them.
CMD python -m uvicorn youhuo.api:app --host 0.0.0.0 --port ${PORT:-8000} --app-dir backend --timeout-keep-alive 120
