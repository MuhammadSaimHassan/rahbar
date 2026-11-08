# Indexing and retrieval pipeline

The five production indexing stages are implemented in `indexer/pipeline/`. Real-corpus
preprocessing and fixture publication are separate checks: the latter uses a synthetic
embedding service to verify mechanics, not retrieval quality. Real-model publication and the historical Phase 5 evaluation were completed using host
Ollama with `nomic-embed-text`; the revised prompt still needs a fresh live evaluation.

## Extraction
PDF extraction uses pdfplumber, physical 1-based page numbers, font/layout heading hints
and table bounding boxes. Text inside detected tables is replaced by Markdown rows at
the same reading-order position, so cells are not duplicated in both prose and tables.
Pages without extracted text are rendered individually at 200 DPI in grayscale and
OCR'd with Tesseract English. Images are closed immediately and page layout caches are
released after each page. OCR cache identities include source SHA-256, page, language,
DPI and an algorithm version; cached diagnostic OCR from the earlier audit is not used.

The 2023 rules need OCR on 24 of 26 pages; the startup policy needs OCR on all 8 pages.
The current handbooks also contain textless covers/backs/blanks. An OCR attempt that
returns no text remains an empty page in the processing report. `OCR_ENABLED=false`
is available for the later extraction-failure experiment; it is not the shipped default.

HTML extraction keeps headings, lists and table cells while removing navigation,
scripts, styles and site header/footer elements. HTML uses page 1 for citations. Markdown
front matter supplies metadata through discovery and is removed from evidence text.

The reviewed grade table on Academic Rules 2026 PDF page 12 has two Grade/Points pairs.
A plain text line such as `A+ 4.00 C+ 2.33` lacks cell labels; the structured result keeps
the row under `| Grade | Points | Grade | Points |`. The locally captured before/after
example is recorded with the implementation evidence. Image-only tables are OCR text:
the implementation does not claim perfect reconstruction of scanned table geometry.
OCR may confuse punctuation, clause numbers, symbols and low-resolution text. Complex
merged cells and multi-column layouts still require source spot checks.

## Cleaning
Cleaning normalizes Unicode ligatures, soft/zero-width characters and whitespace. It
joins wrapped prose and retains hyphens across wraps. Repeated margin lines are counted
only in the first/last two non-empty lines; at least three pages and half the non-empty
pages must repeat a line before it is a margin-removal candidate. Page numbers must be
plausible for the document; standalone edition years are preserved.

Table rows, bullets, numbered clauses and meaningful section headings are protected.
Known repeated book/university headers can still be removed when font hints mark them
as headings. Deliberately retained: clause punctuation, course codes, decimal thresholds,
grade signs and definition subclauses. A test caught a repeated table row being treated
as a footer; structured rows are now explicitly exempt. Input Document objects are not
modified in place.

## Chunking
The selected target is 400 lexical tokens with up to 50 tokens of overlap, justified
by the three-configuration Phase 5 comparison below.
Lexical tokens are Unicode words and punctuation, defined in `pipeline/text.py`; they
are not the model's BPE tokens. A section title prefix counts against the hard cap.
Split order is section/clause → paragraph → sentence → lexical-token fallback. Tables
keep rows together when possible and repeat column headers when split. An oversized
single row may require a hard split; this limitation is not reported as lossless table
recovery.

Chunks never cross physical pages, keeping the single `page` citation unambiguous.
Section context carries across page boundaries, but overlap does not cross a page or
section boundary. Whole structural units take priority over obtaining exactly 50 shared
tokens. IDs hash source, version, page, section, ordinal and text, making repeated runs
with the same inputs/settings stable. Every chunk has `source`, `section`, `page`,
`doc_version` and boolean `superseded` metadata.

Reports count extracted source tokens, cleaned tokens and stored chunk tokens.
`storage_amplification = stored / extracted`; `overlap_amplification = stored / cleaned`
also includes repeated section context. Neither value is a disk/vector-storage ratio.
Measured counts from the real-corpus dry run are recorded in the accompanying evidence.

The final offline pass prepared **950 chunks** from all 9 documents: 113,362 extracted
lexical tokens, 112,074 cleaned tokens and 118,733 stored-chunk tokens. Thus active-index
token amplification is **1.0474×** relative to extraction, or **1.0594×** relative to
cleaned text. All chunk IDs were unique and every chunk was at most 400 lexical tokens.
This is the planned chunk representation; dry-run mode does not store these 950 chunks
or call Ollama. Retained database generations add physical storage beyond this ratio.
The measured parent-process peak RSS was about 159 MiB with a warm OCR cache; it is not
the whole-container peak or a justification of the final Kubernetes memory limit.

| Source | Prepared chunks |
| --- | ---: |
| Academic Rules 2023 | 127 |
| Academic Rules 2026 | 291 |
| Prospectus rules 2026 | 15 |
| Student Handbook 2026 | 122 |
| Annual Report 2019-20 | 44 |
| Annual Report 2023-24 | 314 |
| Fee HTML snapshot | 8 |
| Grading HTML snapshot | 8 |
| Scanned startup policy | 21 |

The source-authored golden set was frozen and committed before tuning. All 18
answerable source units project onto the default chunk export without ranked retrieval.
The measured three-configuration comparison and cache sweep below supersede the initial
untuned settings. See `eval/README.md` for oracle/projection separation.

## Embedding
The shared ConfigMap pins `EMBED_MODEL` and `EMBED_DIMENSION`; production uses
`nomic-embed-text` and 768 dimensions. The stub overlay keeps `dummy-768`. The indexer
batches at most 16 texts into Ollama `/api/embed` calls with `truncate=false`. Nomic
document inputs receive `search_document: `; the query embedder uses
`search_query: `. Returned model names, vector counts, dimensions, numeric finiteness
and non-zero norms are validated. Vectors are normalized before storage. Transient
transport/429/5xx failures retry twice with backoff; malformed results fail immediately.
The model/dimension preflight runs before expensive OCR.

Chroma collection metadata records model, dimension, generation, expected count, chunk
configuration and token unit. API startup/readiness resolves the active generation and
checks its metadata against the API pin. API retrieval reuses that resolver once per request. See the [Ollama embedding API](https://docs.ollama.com/api/embed).

## Storage and publication

The indexer is the only Chroma writer. It builds `rahbar-v-<uuid>`, writes batches of
128 chunks and validates the final count. A Redis writer lease is renewed between
batches. WATCH guards the lease through an atomic transaction that switches the JSON
catalog at `rahbar:index:rahbar:active` and unlinks the previous generation's cache keys.
The API only reads the catalog and Chroma. With no catalog, it can still use the original
bootstrap collection during the stub milestone.

Old collections stay available to in-flight requests. Failed uploads/count checks leave
the catalog unchanged. Timed-out publication never triggers collection deletion because
the transaction might have committed. Old/orphan collections need deliberate cleanup;
there is no automatic garbage collector. Redis is persistent and uses `noeviction`
because its catalog is essential metadata. Never use `FLUSHDB` as a cache reset.
See ADR 0002 for tradeoffs.

## Corpus delivery and execution

The default indexer image contains code only. An optional `with-corpus` build target
copies just the 9 verified raw source files and `_index.json` into `/corpus`, so a Job
needs no download egress or developer-machine mount. The corpus build context excludes
OCR text, previews, reports and secrets. PDFs remain ignored by Git.

```bash
python3 corpus/fetch.py --verify
docker build --target with-corpus --build-context corpus_files=./corpus \
  -f indexer/Dockerfile -t rahbar-indexer:corpus-dev indexer
```

For a local offline dry run, create `corpus/raw/pipeline`, mount it as `/output`, set
`OCR_CACHE_DIR=/output/ocr-cache`, and run the corpus image with:

```text
python -m pipeline.run --dry-run --report /output/preprocessing-report.json \
  --chunks-out /output/chunks.jsonl
```

The optional `k8s/overlays/real-indexer` uses that image, the real model pin, a two-hour
deadline and restricted indexer-to-Redis/Ollama paths. Its initial Job is suspended and
the host IP policy uses TEST-NET as an inert placeholder. Configure the actual Ollama
host `/32`, verify the model is pulled, then resume the Job. The scheduled CronJob also
stays suspended during development; manual Jobs can be created from its template.

After the first transition from dummy to real model, restart API replicas to load the
new shared ConfigMap pin. Subsequent same-model re-indexing needs no API restart.
Use the real-query overlay to activate host Ollama generation.

## Semantic cache
Publication invalidates the old index generation's namespace:
`rahbar:cache:<logical>:<generation>:*`. The query path uses the generation captured for the request and a finite TTL.
Later requests resolve the new generation and cannot see entries written by an older
request. The selected cosine cutoff is 0.85 with runtime guards; the measured sweep below
records both false-hit prevention and limited paraphrase reuse.

## Evaluation method

Recall treats each source-annotated evidence unit as one target. Any projected chunk
ID for that unit satisfies it. Recall at 3 and 5 is the mean across answerable
questions, overall and by type. The fixture suite uses exact source and section pairs
when no projection is supplied. Citation validity is the fraction of emitted citations
whose source, section and page match a retrieved chunk. Must-abstain questions must
decline without citations or a service fallback.

The evaluator checks each response against the live generation and the SHA-256 of the
indexed chunk export. The gates fail for a recall@5 regression greater than five
percentage points, citation validity below 95%, or any failed required abstention.
Per-question output includes the answer and reference facts for manual review.

### Phase 5 chunk comparison

Each index used the same nine verified sources, Ollama 0.6.5 with
`nomic-embed-text:latest` (model ID `0a109f422b47`), and Chroma 1.0.12. The
frozen golden projection matched the live chunk fingerprint for each run. All
18 answerable questions had mapped source evidence for every configuration.

| Size / overlap | Chunks | Stored tokens | Recall@3 | Recall@5 |
| --- | ---: | ---: | ---: | ---: |
| 300 / 30 | 1,037 | 122,370 | 77.8% | 88.9% |
| 400 / 50 | 950 | 118,733 | 77.8% | 88.9% |
| 550 / 75 | 902 | 116,323 | 72.2% | 88.9% |

Keep 400/50. It ties for best recall at both ranks while using 87 fewer chunks
than 300/30. The 550/75 index uses 48 fewer chunks but loses a relevant hit in
the first three ranks. For 400/50, recall@5 was 90% on ordinary questions, 75%
on version-sensitive questions, and 100% on both the three exact-term questions
and the single injection question. On this sample, exact-term retrieval
performed better than ordinary retrieval. Two evidence units missed the top
five in every configuration, the repeated-course grading rule (o04) and the
June 2026 extra-course rule (v04).

The strongest passage for a must-abstain question scored 0.6972. Among the
retrieved relevant passages, the weakest per-question best match scored 0.7073.
A relevance floor of 0.70 separates those scores on this benchmark. Both
abstention questions concern the same shuttle timetable, so this separation
still needs validation on other absent topics.

### Cache threshold comparison

The selected 400/50 index used a 0.70 relevance floor for this run. The
12 labeled pairs were evaluated with real Ollama embeddings and the runtime
edition, evidence, and lexical guards. The comparison assumes each seed
answer was validated and eligible for caching.

| Cosine threshold | False hits with cosine alone | False hits with runtime guards | True hits with runtime guards |
| --- | --- | ---: | ---: |
| 0.85 | c08, c10 | 0 | 1 |
| 0.90 | c08, c10 | 0 | 1 |
| 0.95 | c08 | 0 | 1 |

Use 0.85, the lowest tested threshold with zero guarded false hits. Cosine alone
confused a theory/lab reversal (c08) and two editions of the summer electives
rule (c10). The remaining true hit was a tuition paraphrase (c06). The guards
missed five equivalent paraphrases, so this result shows limited cache reuse
on the labeled sample.

### Live answer run environment

The answer run uses `llama3.2:3b` (model ID `a80c4f17acd5`) through the
Ollama 0.6.5 CPU build. The first direct runs hit model-load and inference
timeouts. For the quality run, a local adapter reuses the pinned Nomic
vectors computed in advance for the 20 exact benchmark questions. Chroma
still ranks the passages for each API request, and Llama generates answers
on cache misses. The restarted run reused some validated answers from an
earlier attempt on the same generation. The adapter keeps Llama resident
and avoids repeatedly loading the embedding model. The timings describe this
CPU setup and include a mix of cache hits and misses.

The CPU run enabled memory mapping, a 3,072-token context, an inference
batch of 64 and a 320-token generation limit. The API timeout was extended
to 360 seconds per generation attempt. The API can render inline markers for
a single sentence when its structured citations already match the retrieved
evidence. Answers with multiple sentences still require per-sentence
citation markers from the model.

### Live quality gate and manual review

The 20-question run passed the configured gates. Recall@3 was 77.8%, recall@5
was 88.9%, all 10 emitted citations matched retrieved passages, and both
required abstentions passed. This run establishes the initial baseline for
future recall regressions.

The API answered 7 of the 18 answerable questions and returned a safe fallback
on the other 11. Manual review found that 5 of those 7 answers covered the
reference facts. The attendance answer (o02) omitted the F/A grade. The
lab/theory answer (o05) cited the right section but reversed which component
the student passed. All four version-sensitive questions and all three
exact-term questions returned fallback responses. The injection question
also returned a fallback and did not repeat the injected instruction.

Citation validity measures whether references match retrieved passages.
The incorrect lab/theory answer and the low answer coverage show why the
automated gate needs to be read alongside the per-question results.

## Current verification boundary

The Phase 5 answer results are historical and remain unchanged in `eval/results.json`
and `eval/baseline.json`. The shared prompt changed during the final coding pass;
a new real-model answer run has not been recorded. Later fixture results validate
mechanics, edition filtering and poison handling, not an improvement over real Llama.
The four independent failure measurements are explained in FAILURE-ANALYSIS.md.
