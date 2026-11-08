# Source-authored benchmark

`golden.yaml` contains 20 real-corpus questions authored from PDF/HTML sources:
10 ordinary, 4 version-sensitive, 3 exact-term, 2 must-abstain and 1 user-injection case.
No ranked retrieval or threshold/chunk-size experiments were used to choose the
questions or expected facts. The 400/50 setting was selected after the measured Phase 5 sweep.

## Source oracle and chunk projection

Each answerable question records source filename, version, physical page alternatives,
original clause/heading and short evidence anchors. `answer_facts` is the human answer
oracle; `expect` is only a short review hint. Exact substring matching is not a measure
of correctness. The API receives the `question` text; other fields are evaluator
annotations, not instructions to send to the model.

Source annotations were written first. `prepare_golden.py` then mapped them to the
existing unranked chunk export by source, version, page and anchor content.
`relevance.current.json` contains the chunk-ID alternatives. All 18 answerable questions
map in the current 950-chunk export. A duplicated clause on two pages is one source
evidence unit with alternative support IDs, not two required answers. The two
abstentions intentionally have no relevant passages.

```bash
python3 eval/prepare_golden.py
python3 eval/prepare_golden.py --check-lock
```

Validation checks counts/types, question lengths, IDs, source versions/pages, explicit
intent for superseded sources, version-pair coverage and cache labels. It uses committed
source metadata, so these static checks need no cluster, model or downloads.

For later chunking experiments, keep the primary oracle fixed and write a separate
projection rather than overwriting the frozen default:

```bash
python3 eval/prepare_golden.py --chunks path/to/new-chunks.jsonl \
  --projection-out eval/projections/new-configuration.json
```

A missing projection is a support/mapping problem to investigate, not permission to
drop a difficult question or change its answer. If smaller chunks split an annotated
span, review how the pieces represent its source support before computing recall.
Scoring uses the projected chunk IDs. The evaluator verifies the golden hash and
matches the live index fingerprint to the projection on every response. Preparation
produces no retrieval-quality metric.

## Actual version changes

Two paired changes were checked against complete rendered pages:

| Pair | 2023 source | 2026 source | Difference under test |
| --- | --- | --- | --- |
| Summer electives | PDF page 20, clause 6.4(iii) | PDF pages 28–29, clause 6.2 | Graduating-student exception versus repeat-only summer courses |
| Extra regular courses | PDF page 14, clause 4.3 | PDF page 19, clause 4.3 | Not-ahead-of-batch condition versus one extra course for final-year students |

Both editions are tested. Old-edition questions explicitly permit superseded documents;
default/current questions do not. Source dates are annotations, not an assumption that
every question containing a year refers to the same kind of document.

## Absence and injection

The absent topic is the current Islamabad campus shuttle stop/departure timetable.
General transport descriptions exist, so a generic transport question would be an
invalid abstention test. Source review is documented in `docs/CORPUS.md`.

The injection question places an instruction override in user text and still expects
the prerequisite rule. This does not replace the query-stage test that indexes a
poisoned passage. The query integration test checks a poisoned passage with real Chroma and a
simulated Ollama reply.

## Cache labels before threshold selection

`cache_tests.yaml` labels 6 equivalent paraphrases and 6 near misses. Difficult cases
reverse theory/lab outcomes, confuse employment with licensing duration, confuse fees
with deposits, or change policy edition. One pair shares the answer number 2.00 while
asking about different rules: returning the seed's wording/citation is still a false hit.

Version pairs need filter/scope isolation in the cache key as well as semantic similarity.
Three policy cases prohibit caching follow-ups, abstentions and failed validations.
The measured 0.85/0.90/0.95 sweep selected 0.85 with the runtime guards: zero false
hits and one of six equivalent paraphrases reused. See PIPELINE.md and
`docs/evidence/phase5-cache-sweep.json`; this small sample is not a universal guarantee.

## Freeze and remaining work

`golden.lock.json` records hashes for questions, cache tests, manifest and default
projection, plus the input chunk hash. UTF-8 line endings are normalized for Windows,
WSL and CI. The golden set was committed locally before tuning. The lock records that commit.
Team review remains pending and GitHub setup is deferred.
Explain and review any intentional oracle change before recording a replacement snapshot.

The real query/evaluation run produced `results.json` and `baseline.json`. Keep these
historical real-corpus outputs distinct from `fixtures/baseline.json`: the question
sets cannot be compared as one benchmark. The revised generation prompt requires a
fresh real-model run; preserve the existing baseline until that run has been reviewed.

## Run Phase 5

Verify the frozen inputs before starting the benchmark.

```bash
python eval/prepare_golden.py --check-lock
```

Rebuild the indexer and API images from the current code, then publish the same
hash-pinned corpus to three separate logical collections. Use a separate evaluation
stack or unused collection names so the experiment does not replace a deployed
collection. Keep the embedding model, OCR settings, software versions and corpus
constant. Use the indexer's `--chunks-out` option on each publication and retain
the associated JSONL in an ignored directory. Suggested experiment inputs are:

| Label | Logical collection | Size / overlap |
| --- | --- | --- |
| 300-30 | rahbar-eval-300 | 300 / 30 |
| 400-50 | rahbar-eval-400 | 400 / 50 |
| 550-75 | rahbar-eval-550 | 550 / 75 |

For each export, run `prepare_golden.py --chunks <export> --projection-out <projection>`.
The default projection can be reused if the 400/50 export reproduces its fingerprint.
From an environment with the API dependencies and access to Chroma, Redis and Ollama,
set the same `CHROMA_HOST`, `CHROMA_PORT`, `REDIS_URL`, `OLLAMA_URL`,
`EMBED_MODEL` and `EMBED_DIMENSION` used by the API. Then run:

```bash
output=corpus/raw/pipeline
PYTHONPATH=api python eval/sweep.py \
  --case 300-30 rahbar-eval-300 "$output/phase5-300-30-projection.json" \
  --case 400-50 rahbar-eval-400 eval/relevance.current.json \
  --case 550-75 rahbar-eval-550 "$output/phase5-550-75-projection.json" \
  --cache-case 400-50 --threshold 0.85 0.90 0.95 \
  --out "$output/phase5-sweep.json"
```

The sweep reports overall and per-type recall at 3 and 5, per-question best
retrieval scores, and false and true cache hits for each tested threshold. Repeat
the cache sweep on the selected collection if it changes. The threshold sweep
assumes each seed answer passed validation. Verify live bypass for follow-ups and
abstentions separately. The API tests simulate invalid generation and verify that
a response that required a retry is never cached. Review best scores alongside the two abstention cases when
tuning the relevance floor.

Point the API at the selected collection with host Ollama enabled, then run the
full evaluator against that API. Omit `--projection` for the frozen 400/50 projection.

```bash
python eval/run_eval.py --api http://127.0.0.1:8000 --projection <selected-projection>
```

The report contains generated answers and source-authored facts for manual
correctness review. Compare the report to the benchmark and rerun with
`--update-baseline` only once the shipped configuration and results are accepted.
Exit codes are 0 for passing gates, 1 for gate failures and 2 for an invalid run.
For the fictional CI corpus, use `--golden eval/fixtures/golden.fixture.yaml`
and an explicit fixture-specific `--baseline` when comparing regressions.
