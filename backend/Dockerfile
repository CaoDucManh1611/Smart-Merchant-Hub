FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

# Browser microphone recordings are commonly WebM/Opus, while Zalo Bot's
# sendVoice endpoint requires an AAC file URL.  Keep transcoding in the
# backend so every browser and supported channel gets the same behavior.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY alembic-platform.ini .
COPY alembic_platform ./alembic_platform
COPY alembic-tenant.ini .
COPY alembic_tenant ./alembic_tenant
COPY scripts ./scripts
RUN python scripts/generate_seed_dataset.py

COPY app ./app
COPY artifacts ./artifacts

CMD ["sh", "-c", "python -m alembic -c alembic.ini upgrade head && python -m alembic -c alembic-platform.ini upgrade head && python -m app.scripts.upgrade_active_tenants --apply && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
