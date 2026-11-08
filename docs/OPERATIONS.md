# Local operational and failure tools

Run these tools against a dedicated lab cluster. Supply its context explicitly.
The operational tool scales the API to at least three replicas, measures ready
Service endpoints, rolls out the supplied alternate image, rolls back, and deletes
one API pod while sending requests through Ingress. It saves the traffic samples,
pod replacement, resource usage and HPA output. A failed HTTP request, an
unrecovered pod, an unknown HPA metric, or a failed restore causes a nonzero exit.

Import both image references into the lab cluster before running the demo.
For example, from the repository root after installing the project dependencies:

```bash
python scripts/operational_demo.py --context k3d-rahbar-lab --namespace rahbar \
  --api http://127.0.0.1:18087 --host rahbar.local \
  --image rahbar-api:previous --out docs/evidence/operations.json
```

The tool temporarily fixes the target HPA bounds at the demonstration replica
count and restores the original image, replica count and HPA settings in a
finally block. Inspect `restore_errors` in the report if the
cluster becomes unreachable during cleanup. Request continuity is sampled over
the finite demonstration interval. The API manifest gives endpoint withdrawal
15 seconds before process termination and a 330-second total termination grace,
covering the default embedding call and two generation attempts.

Four experiments are implemented in `eval/failure_experiments.py`. They read
source files or the current index and write observations to the supplied output
path. Keep the source oracle and deployed index unchanged during a comparison.

```bash
export PYTHONPATH=api:indexer:eval

python eval/failure_experiments.py extraction \
  --scanned-pdf corpus/raw/faculty-entrepreneurship-and-technical-start-ups-policy.pdf \
  --ocr-cache corpus/raw/pipeline/ocr-cache --out docs/evidence/failure-extraction.json

python eval/failure_experiments.py chunking --corpus corpus/raw \
  --ocr-cache corpus/raw/pipeline/ocr-cache --out docs/evidence/failure-chunking.json

python eval/failure_experiments.py pin --out docs/evidence/failure-pin.json
python eval/failure_experiments.py source --out docs/evidence/failure-source.json
```

The live cases use the same `CHROMA_HOST`, `CHROMA_PORT`, `CHROMA_COLLECTION`,
`REDIS_URL`, `OLLAMA_URL`, `EMBED_MODEL` and `EMBED_DIMENSION` as the API.
Use port forwarding or run the script inside the lab network.

Extraction compares text coverage with and without OCR. Chunking compares
source evidence mapping under the normal chunker and fixed 100-token windows
with zero overlap. That mapping measurement can locate lost evidence before
a ranked recall experiment. The pin case proves an incompatible embedding
configuration is rejected and the original configuration still retrieves.
The source case compares the same query vector with and without the
superseded filter, recording which retired passages become eligible.

The saved observations are interpreted in FAILURE-ANALYSIS.md, including symptoms,
diagnosis, remedies and limits of each measurement. Real-model answer quality still needs a new
evaluation after prompt changes.
