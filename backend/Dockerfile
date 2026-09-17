FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 ca-certificates curl \
    && mkdir -p /app/certs \
    && curl --fail --show-error --silent --location \
       https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
       --output /app/certs/rds-bundle.pem \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# An allowlist prevents local secrets and development files entering the image.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini main.py game_tracker.py model_wrappers.py feature_builder.py ./
COPY defense_strategy_engine.py recommendation_engine.py ./
COPY *.pkl ./
COPY scripts ./scripts

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
