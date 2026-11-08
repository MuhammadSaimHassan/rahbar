# ADR 0002: Publish complete index generations through a Redis catalog

## Status

Implemented, 2026-11-05. AI-assisted draft pending team review.

## Context

Deleting the live collection before re-indexing makes readiness fail. Upserting into
the live collection exposes a mixture of old and new chunks, and removing stale chunks
can invalidate a request already retrieving evidence. Chroma 1.0.12 does not provide an
atomic cross-collection alias swap for this use case.

## Decision

The indexer writes a new `rahbar-v-<generation>` collection, with pinned model/dimension
metadata and the expected chunk count. A short Redis writer lease serializes publication.
After all batches are uploaded and count validation passes, a Redis transaction publishes
one JSON catalog value at `rahbar:index:rahbar:active` and removes the previous
generation's cache keys. WATCH protects the lease through the transaction. An expired or
replaced lock aborts publication.

API readers resolve this catalog at readiness and once per request. They retain that generation throughout retrieval and cache lookup/write. Cache
keys follow `rahbar:cache:<logical>:<generation>:<question-key>`. A request that finishes
after a re-index may write an old-generation key, but future requests cannot hit it.

The old collection is retained. A failed stage never deletes the active index. A timed-out
publication can have committed, so the indexer never deletes a new collection merely
because the client observed an error. Orphaned and old collections require deliberate
cleanup after checking the active catalog and allowing in-flight requests to finish.

## Alternatives

Deleting/recreating was suitable only for the dummy wiring milestone. In-place upserts
would serve partial replacements. Two collection renames would leave a gap and are not
an atomic swap. A dedicated external catalog could avoid using the cache store, but Redis
is already durable and required for readiness in this assignment.

## Consequences

Same-model re-indexing can publish without restarting the API. Initial migration to a
different model still requires the API configuration to match before readiness succeeds.
Storage grows with retained generations; the current implementation does not claim an
automatic garbage collector. Redis now contains essential index metadata and must not
be flushed as a cache reset. AOF/PVC persistence and `noeviction` protect the catalog.
Cache writes must tolerate memory-pressure errors rather than evicting catalog metadata.

The distributed stores do not share a transaction: Chroma finishes first, and Redis is
the publication commit point. Real-model retrieval quality and Kubernetes continuity
remain separate acceptance checks from the fixture integration test.
