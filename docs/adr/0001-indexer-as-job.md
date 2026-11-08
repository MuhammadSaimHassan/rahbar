# ADR 0001: Separate indexing from API startup

## Status

Implemented, updated 2026-11-07. AI-assisted; the team must understand and review
the decision before presenting it as their own engineering work.

## Context

Three API replicas need the same index. Extraction and embedding take longer and consume
different resources from serving requests. Repeating that work on every replica startup
would couple deployment health to a batch task and start concurrent writers.

## Decision

Only an indexer Job writes Chroma. The API starts independently and checks the collection,
its embedding metadata and Redis through readiness. An empty or incompatible index keeps
the API outside Service endpoints without killing it. A CronJob exposes the same writer
command for scheduled and manual indexing without changing the API Deployment.

## Options considered

Indexing in API startup would repeat expensive work on restarts, run several writers and
obstruct rolling updates. A permanent indexer Deployment would need its own scheduler
and lifecycle management for work that naturally finishes and exits. A Job already
provides retries and completion status.

## Consequences

The writer has an independent resource budget and observable success/failure. API replicas
can scale and restart without modifying the index. The initial Job must complete before
readiness succeeds. CronJob `Forbid` protects scheduled runs, and the production Redis writer lease also serializes manual publication attempts.

The dummy writer deletes/recreates its collection for the wiring milestone. The real
writer now stages a versioned collection and atomically publishes a Redis catalog entry;
see ADR 0002. Old collections are retained and cache keys are scoped to generations.
The synthetic publication integration recorded 37 successful readiness samples across
re-indexing. The separate Kubernetes fixture run measured rollout and Pod replacement.
Production-model re-index continuity still needs its own live demonstration.
