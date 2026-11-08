# Real-model evaluation after the prompt revision

The run-real-evaluation label on a same-repository PR into dev opts into the
hosted real workflow. It creates a fresh corpus/cluster/model environment, runs
acceptance, clears only answer-cache keys in its own ephemeral Redis, and evaluates
the unchanged frozen 20 questions against the existing baseline and projection.
Normal application thresholds, prompts, timeouts and model settings are retained.
Cache states are recorded for each question; normal within-run reuse is possible.

The artifact contains real-model-results.json, or a partial checkpoint if an API
request fails. A failed gate remains a failed run; baseline and questions are never
rewritten to pass it. Review all answer_facts against actual responses, including
missing qualifications, reversed rules, fallbacks and unsupported answers. Valid
citation structure alone is not semantic correctness. Commit results only with the
exact run and source revision, preserving historical evidence and baseline.

Status: hosted run pending. This PR depends on PR #7 and targets dev; merge in that
order after checks and partner approval. Remove the heavy label once results are
collected so evidence-only commits do not repeat OCR/model downloads.
