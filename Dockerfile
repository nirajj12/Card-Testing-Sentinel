FROM python:3.11.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements-runtime.lock pyproject.toml README.md ./
RUN python -m pip install --upgrade pip==26.2.1 setuptools==84.0.0 \
    && python -m pip install --no-deps -r requirements-runtime.lock

COPY src ./src
COPY configs ./configs
COPY artifacts ./artifacts
COPY scripts/run_app.py ./scripts/run_app.py
RUN python -m pip install --no-deps --no-build-isolation . \
    && addgroup --system sentinel \
    && adduser --system --ingroup sentinel sentinel \
    && mkdir -p /app/data/runtime \
    && chown -R sentinel:sentinel /app/data/runtime

USER sentinel
VOLUME ["/app/data/runtime"]
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import json,urllib.request; payload=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=2)); raise SystemExit(0 if payload.get('ready') else 1)"

CMD ["python", "scripts/run_app.py"]
