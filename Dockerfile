FROM python:3.14-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /build/
COPY src/ariadne /build/src/ariadne
RUN pip install --no-cache-dir '/build[mcp]' && rm -rf /build

ENV PYTHONUNBUFFERED=1 HOME=/tmp
WORKDIR /project
USER 1000:1000

ENTRYPOINT ["ariadne-serve"]
CMD ["--project", "/project", "--http", "--http-container", "--http-host", "0.0.0.0", "--http-allowed-host", "ariadne:8000"]
