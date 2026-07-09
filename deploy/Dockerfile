# Optional container for a future cloud move (Fly.io / Hetzner) — NOT used by the default
# Mac always-on deploy. Ships the core pipeline only (no SDXL/torch: cloud image gen or the
# stock-only path is used off-Mac; local SDXL wants Apple Silicon / a GPU host).
#
#   docker build -f deploy/Dockerfile -t ai-operator .
#   docker run --env-file .env -v "$PWD/data:/app/data" -v "$PWD/output:/app/output" ai-operator
#
FROM python:3.11-slim

# ffmpeg is required by the encoder; software (libx264) encode off-Mac (no videotoolbox).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

ENV PYTHONPATH=/app/src \
    AI_OPERATOR_ENCODER=libx264

# Host must mount data/ (sqlite db) and output/ so state + renders survive container restarts.
CMD ["python", "-m", "ai_operator.cli", "run-scheduler"]
