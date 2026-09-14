FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY workers/qeo-voice/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY workers/qeo-voice/app.py ./app.py
COPY workers/qeo-voice/engine.py ./engine.py
COPY workers/qeo-voice/registry.py ./registry.py
COPY workers/qeo-voice/voices.json ./voices.json
COPY workers/qeo-voice/healthcheck.py ./healthcheck.py

EXPOSE 8765
CMD ["python", "app.py"]
