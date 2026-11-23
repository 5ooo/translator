FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libvulkan1 \
    && rm -rf /var/lib/apt/lists/*
COPY src/ts /app/src/ts
ENV PYTHONPATH=/app/src:/deps \
    PYTHONNOUSERSITE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    XDG_DATA_HOME=/tmp/ts-data \
    XDG_CACHE_HOME=/tmp/ts-cache
ENTRYPOINT ["python", "-m", "ts.resident"]
