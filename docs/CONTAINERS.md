# Container images

Build from the repository root (Docker Desktop must be running):

```bash
docker build -t rahbar-api:dev api
docker build -t rahbar-indexer:dev indexer
docker build -t rahbar-ui:dev ui
python3 scripts/smoke_images.py
```

The smoke checks need Python's standard library only. They run temporary containers,
publish no host ports, disable external networking, drop capabilities and use a read-only
root filesystem with writable `/tmp`. The script removes service containers when it exits
normally or when a check raises an error.

| Image | Runtime user | Entrypoint behavior |
| --- | --- | --- |
| `rahbar-api:dev` | UID/GID 10001 | Uvicorn on port 8000; default stub retriever and provider |
| `rahbar-indexer:dev` | UID/GID 10001 | Runs `python -m pipeline.run`, then exits |
| `rahbar-ui:dev` | UID/GID 101 | nginx on port 8080, with temporary files in `/tmp` |

The indexer includes Tesseract (English OCR) and Poppler (PDF utilities). Its corpus is
supplied separately at `/corpus`; no downloaded documents are baked into this image.
The five-stage pipeline is implemented. The Kubernetes stub overlay overrides its
command with `python -m pipeline.run --dummy`; the real-indexer overlay runs the normal
pipeline against a self-contained corpus image. The latter needs Ollama and Redis.

Each `.dockerignore` permits only the runtime files needed by its build. Tests, local
environments, secrets and raw corpus documents are excluded from the build contexts.
Base images have explicit version tags. The Phase 6 local Trivy scan found zero
fixable HIGH/CRITICAL findings after dependency/base updates; see evidence/phase6-local.txt.
That is a historical scan result, not a claim about a future vulnerability database.

Kubernetes Deployments and Jobs must also set `runAsNonRoot`, read-only root filesystems,
resource requests and limits, and mount a writable `/tmp`. Those settings are present in k8s/base/. This smoke check does not test cluster networking or persistence.
