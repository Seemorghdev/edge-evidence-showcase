FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates git make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/replication-worker
COPY . .
RUN python -m pip install --no-cache-dir -e '.[dev]'

CMD ["bash"]
