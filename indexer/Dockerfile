FROM python:3.12.16-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp \
    OMP_THREAD_LIMIT=1 \
    ANONYMIZED_TELEMETRY=False

RUN apt-get update \
    && apt-get install --no-install-recommends -y tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 rahbar \
    && useradd --uid 10001 --gid rahbar --no-create-home rahbar \
    && mkdir /corpus \
    && chown 10001:10001 /corpus

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=10001:10001 pipeline/ ./pipeline/

USER 10001:10001
CMD ["python", "-m", "pipeline.run"]

# Optional self-contained corpus image. The default build does not read this context.
# docker build --target with-corpus --build-context corpus_files=./corpus -f indexer/Dockerfile ...
FROM runtime AS with-corpus
COPY --from=corpus_files --chown=10001:10001 /raw/*.pdf /raw/*.html /raw/_index.json /corpus/

FROM runtime AS default
