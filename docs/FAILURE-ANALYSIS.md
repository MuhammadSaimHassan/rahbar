# Failure analysis

Four stages were changed independently using `eval/failure_experiments.py`.
Extraction and chunking use the verified real corpus. Retrieval-pin and source-filter
experiments use the fictional live fixture index with real Chroma/Redis. These are
read-only comparisons; they do not publish a broken production index. Commands and
environment settings are in [OPERATIONS.md](OPERATIONS.md).

| Stage | Normal observation | Broken observation | Evidence |
| --- | --- | --- | --- |
| A: extraction | 2,264 tokens across eight OCR pages | Zero tokens; eight empty pages | [JSON](evidence/failure-extraction.json) |
| B: chunking | 950 chunks; 18/18 evidence units mapped | 1,257 chunks; 17/18 mapped | [JSON](evidence/failure-chunking.json) |
| C: retrieval pin | Five retrieved hits | Mismatch rejected; zero hits | [JSON](evidence/failure-pin.json) |
| E: source selection | Zero superseded hits among ten | Three superseded hits among ten | [JSON](evidence/failure-source.json) |

## Stage A · Extraction without OCR

**What changed.** Disabled OCR for the eight-page scanned faculty entrepreneurship
and technical startups policy, holding the input file constant.

**Symptom.** The default extractor produced 2,264 lexical tokens and OCR text on pages
1–8. With OCR disabled it produced zero tokens and all eight pages were empty. A
downstream retriever would have no policy evidence to find, regardless of model size.

**Diagnosis without knowing the change.** Start with the indexer's per-source token
counts and `ocr_pages`/`empty_pages`, then inspect the PDF text layer with `pdffonts`
or `pdftotext`. Compare a rendered page to extracted text before changing retrieval
thresholds. A non-empty collection overall would hide a single empty source, so
readiness alone cannot detect this coverage loss.

**Remedy and restoration.** Keep `OCR_ENABLED=true`, render only textless pages,
verify their extracted text and spot-check numerical clauses against the original.
The comparison's normal branch supplies the 2,264-token reference; no deployed
configuration was changed. Blank covers may legitimately stay empty, while an entire
text-bearing policy may not. OCR text availability does not establish character accuracy.

## Stage B · Fixed 100-token chunks with zero overlap

**What changed.** Replaced page/section-aware 400/50 chunking with fixed lexical
100-token windows without overlap, using the same extracted and cleaned real corpus.

**Symptom.** Chunk count rose from 950 to 1,257, but source evidence mapping fell
from 18/18 (100%) to 17/18 (94.4%). The missing unit was `v03:0`, an older-edition
regular extra-course condition. More chunks did not preserve every annotated span.

**Diagnosis without knowing the change.** Run the frozen source oracle's projection
against the new chunk export. Inspect `unmapped`, chunk lengths and the text on both
sides of a boundary. Compare `chunks_sha256` with the intended generation before
blaming embedding quality. Mapping is a preprocessing support measure; these numbers
are not ranked recall@5 and do not claim an end-to-end answer degradation measurement.

**Remedy and restoration.** Restore structure-aware 400-token chunks with up to
50-token overlap, retain headings/table rows, and check all 18 mappings before
publication. The normal export remains the baseline. A live ranked comparison is
already available for 300/30, 400/50 and 550/75 in PIPELINE.md; a live 100/0 retrieval
and generation run was not performed for this failure experiment.

## Stage C · Retrieval with an incompatible embedding pin

**What changed.** Changed the retriever's configured model while leaving the active
catalog and stored collection unchanged. The experiment does not alter the deployment
or write different vectors to the store.

**Symptom.** The normal query returned five hits. The changed pin was rejected with
`Index metadata does not match the active catalog and embedding pin`; restoring the
original settings returned five hits again. Zero hits here means rejection, not a
successful search that happened to find no relevant documents.

**Diagnosis without knowing the change.** Inspect `/readyz` for `embedding_pin`,
compare ConfigMap model/dimension with collection metadata, then inspect the
`dependencies not ready` log. The request-path check also verifies generation before
embedding. The separate dependency smoke test in `kubernetes-stub-validation.txt`
records a 503 readiness response for a mismatched pin; this experiment itself is a
retriever-level test and does not claim a new 0/1 Kubernetes Pod capture.

**Remedy and restoration.** Restore the API pin to the published model. For a real
model migration, build and validate a new index and coordinate configuration. Never
disable the guard to make readiness green. The five-hit restored result establishes
that the read-only experiment left the fixture usable.

## Stage E · Source selection without the superseded filter

**What changed.** Queried the same fixture generation with the same vector and result
limit, once with the normal `superseded=false` condition and once without it.

**Symptom.** Retired passages increased from zero to three among ten hits, including
the 2023 attendance policy at rank one. Current and historical clauses became eligible
for the same current-policy question. This records evidence contamination; no claim
is made that a generated answer necessarily selected the wrong clause in this test.

**Diagnosis without knowing the change.** Inspect retrieved `chunk_id`, source,
`doc_version` and `superseded` metadata alongside the query's edition scope. Compare
current-policy and explicitly historical questions. High similarity and a valid
citation do not prove that the cited edition applies to the question.

**Remedy and restoration.** Keep the default filter, permit superseded sources only
under explicit historical intent, and include edition scope in cache keys. The normal
filtered branch remains unchanged and reports zero retired hits. The seven-question
fixture acceptance check independently verifies historical edition isolation.

## Operational failure · Endpoint draining

The first rollout experiment recorded one 502 in 174 requests. After increasing the
endpoint-drain interval, the final run recorded zero failures in 135 requests across
rollout, rollback and a deleted ready Pod, with three ready endpoint addresses.
Both reports are retained. See [engineering answer 7](ENGINEERING-NOTES.md) for the
diagnosis and [operations evidence](evidence/operations.json) for raw samples and
restoration status. Prompt and temperature failures were not measured; the four
required stage comparisons above should not be described as six experiments.
