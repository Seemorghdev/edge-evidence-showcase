FROM python:3.12-slim-bookworm AS tools

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       ca-certificates \
       ffmpeg \
       git \
       make \
       sqlite3 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir \
       "setuptools==82.0.1" \
       "pytest==8.4.1"

RUN groupadd --gid 10001 showcase \
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash showcase

FROM tools AS runtime
WORKDIR /workspace/showcase
COPY . .
RUN bash scripts/setup.sh \
    && chown -R showcase:showcase /workspace/showcase
USER showcase
ENTRYPOINT ["bash", "scripts/container-entrypoint.sh"]
CMD ["demo"]

FROM tools AS dev
USER showcase
WORKDIR /workspaces/edge-evidence-showcase
CMD ["bash"]
