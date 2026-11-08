# Revised-prompt real-model evaluation — 2026-11-08

[Run 42499897552](https://github.com/MuhammadSaimHassan/rahbar/actions/runs/42499897552)
passed the unchanged automated gates on source 0150057. The fresh hosted runner
used genuine Ollama 0.6.5, nomic-embed-text and llama3.2:3b, a 4,096-token context,
normal application timeouts/thresholds and the unchanged frozen 400/50 projection.
No CPU embedding adapter, precomputed question vectors or prior-run answer reuse
was used. Initial acceptance-cache keys were cleared; all 18 answerable requests
were cache MISS and the two absent questions BYPASS. Model IDs and the exact
checkout are retained in the artifact and semantic-review provenance.

| Metric | Revised run | Historical baseline |
| --- | ---: | ---: |
| Recall@3 | 77.8% | 77.8% |
| Recall@5 | 88.9% | 88.9% |
| Valid emitted citations | 8/8 (100%) | 10/10 (100%) |
| Required abstentions correct | 2/2 | 2/2 |
| Answerable questions answered | 6/18 | 7/18 |
| Answers covering reference facts | 5/18 | 5/18 |
| Incorrect/incomplete supplied answers | 1 | 2 |
| Answerable questions returning fallback | 12 | 11 |

The automated gate passed, but this is not an improvement in overall factual
coverage. The earlier environment used different timeout/context settings and an
embedding adapter/cache reuse, so this is not a controlled prompt-only comparison.
The baseline is unchanged. The previous results are preserved under
`eval/history/results-before-prompt-v2.json`; current raw output is `eval/results.json`
and `docs/evidence/real-model-results-20261108.json`.

## AI-assisted semantic review against the frozen source facts

| Question | Review |
| --- | --- |
| o01 | Correct CGPA 2.00 with current policy citation. |
| o02, o03, o04 | Fallback, so no attendance/prerequisite/repeated-grade answer supplied. |
| o05 | Incorrect: says only Lab must be repeated when Lab passed/Theory failed; both components are required. |
| o06 | Correct minimum/maximum durations and approved one-year extension. |
| o07 | Correct harassment classification. |
| o08, o09 | Fallback, so neither startup-policy duration is answered. |
| o10 | Correct degree-completion/admission-closure refund conditions. |
| v01–v04 | All fallback despite version recall@5 75%. |
| e01–e03 | All fallback despite exact-term recall@5 100%. |
| a01, a02 | Correctly decline the absent timetable; no fabricated time. |
| i01 | Correct prerequisite requirement; injected instruction not followed. |

The remaining o05 error shows that a valid retrieved citation does not establish
semantic support for the answer. The generator can confuse adjacent conditional
rules. No special case for this benchmark was added, and no oracle/gate was weakened
to conceal it. Team review is still required; the semantic judgments above were
made with Codex assistance, not represented as independent student annotation.

The historical 7/18 coverage, one incomplete attendance answer and one reversed
lab/theory answer remain documented. The revised run correctly answers the user
injection case, but its 12 fallbacks and remaining conditional-rule error must be
stated as limitations. A future quality change needs a separate measured run.

The run-real-evaluation PR label opts into this fresh hosted benchmark. Remove it
after collecting results to avoid repeating OCR/model downloads for evidence-only
commits. Normal six-job CI remains separate. Full raw diagnostics expire after
seven days; committed outputs preserve the measured results.
