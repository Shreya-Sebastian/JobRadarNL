# Single image for every role (api, worker, scheduler, finalize); the command selects the role.
FROM python:3.12-slim AS build
WORKDIR /app
ENV PIP_NO_CACHE_DIR=1
COPY pyproject.toml ./
COPY radar ./radar
RUN pip install --prefix=/install . "uvicorn[standard]"

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RADAR_LOG_JSON=1
RUN useradd --create-home --uid 10001 radar
COPY --from=build /install /usr/local
COPY radar ./radar
COPY web ./web
COPY data/golden ./data/golden
COPY data/seeds ./data/seeds
COPY data/sources.yaml data/source_kinds.yaml data/top100.yaml ./data/
RUN mkdir -p /app/data/enumerated /app/data/raw && chown -R radar:radar /app
USER radar
EXPOSE 8000 9100
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)" || exit 1
CMD ["python", "-m", "radar.cli", "serve", "--host", "0.0.0.0", "--port", "8000"]
