# 0003 — Scope the Redis answer cache to verified evidence

## Decision

Use the Redis service already available to all API replicas. Redis supports expiring
entries and atomic bounded list updates, and keeps cache writes separate from the
indexer's Chroma write path. Each cache key includes the logical collection, immutable
generation, provider settings, requested edition, and ranked evidence IDs. Look up at
most 32 candidates per key and expire inactive keys after an hour. Compare normalized
query embeddings by cosine similarity and require matching numeric and polarity anchors.

Check Redis after embedding and retrieval so that cache hits can skip generation while
still verifying every citation against the current request's evidence. This orders the
cache differently from the assignment's numbered query sequence. Publication switches the
generation in the key immediately, and the indexer's cleanup removes entries from
previous generations. Concurrent requests already using an old generation can finish
against their snapshot. Any old entries they write expire and are unreachable by later
requests that resolve the new generation.

The API accepts an optional `previous_question` field. The chat UI keeps the last
successful question in page memory and sends it with the next request. A short list of
follow-up patterns controls when the API uses that context and bypasses the shared cache.
The existing question-only request and response body still work. `X-Cache` exposes
`HIT`, `MISS`, or `BYPASS` without changing the response body.

## Alternatives

A second Chroma collection could store question vectors and support vector search,
but would give API replicas a Chroma write path and introduce another collection's
publication, expiry and cleanup lifecycle. Redis already supplies shared persistence,
TTL and atomic list operations; bounded candidate comparison avoids another vector
store writer. The tradeoff is a strict candidate bound and conservative evidence keys
that reduce paraphrase reuse. Redis also carries the index catalog, so it must not be
flushed as a disposable cache.

## Verification

The indexed poison fixture exercises prompt separation and answer validation with
simulated Ollama output. Citation validation checks the evidence references and inline
format. The historical golden run measured real-model behavior; manual review found one
incorrect answer despite valid references. The 0.70 floor and guarded 0.85 cosine
threshold were selected from Phase 5 measurements. The revised prompt still needs a
new live-model evaluation; see PIPELINE.md for the limited cache reuse observed.

Use `sum(rate(rahbar_cache_total{outcome="hit"}[5m])) / sum(rate(rahbar_cache_total[5m]))`
for the cache hit ratio over a five-minute window with traffic.
