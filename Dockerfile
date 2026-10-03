# Single image for every role (api, worker, scheduler, finalize); the command selects the role.
FROM python:3.12-slim AS build
WORKDIR /app
ENV PIP_NO_CACHE_DIR=1
COPY pyproject.toml ./
COPY radar ./radar
RUN pip install --prefix=/install . "uvicorn[standard]"

# The stylesheet: Tailwind's standalone CLI (pinned, checksum-verified) scans the templates and writes web/app.css.
# It runs on the build machine's own architecture; the CSS it produces is the same for every image.
FROM --platform=$BUILDPLATFORM python:3.12-slim AS css
WORKDIR /app
COPY scripts/build_css.py ./scripts/
COPY radar ./radar
COPY web ./web
RUN python scripts/build_css.py

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RADAR_LOG_JSON=1
# glibc gives every thread its own malloc arena and rarely hands the memory back; with the request threads and the
# row-cache reloads that let the API's memory creep up until the pod limit killed it. Two arenas are plenty here.
ENV MALLOC_ARENA_MAX=2
# the data files live next to the app, also for the installed `radar` command (it would look in site-packages)
ENV RADAR_DATA_DIR=/app/data
RUN useradd --create-home --uid 10001 radar
COPY --from=build /install /usr/local
COPY radar ./radar
COPY web ./web
COPY --from=css /app/web/app.css ./web/app.css
COPY data/golden ./data/golden
COPY data/seeds ./data/seeds
COPY data/sources.yaml data/source_kinds.yaml data/top100.yaml data/company_sizes.tsv data/company_sectors.tsv ./data/
RUN mkdir -p /app/data/enumerated /app/data/raw && chown -R radar:radar /app
USER radar
EXPOSE 8000 9100
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)" || exit 1
CMD ["python", "-m", "radar.cli", "serve", "--host", "0.0.0.0", "--port", "8000"]
