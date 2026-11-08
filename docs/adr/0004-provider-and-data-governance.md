# 0004 — Keep the provider replaceable and configure hosted data transfer explicitly

## Decision

Ollama and the hosted Chat Completions provider share the evidence prompt and the
Answer Pydantic contract. The API validates citations, retries an invalid result
once, and returns the safe fallback after repeated failure. The hosted provider
requests strict JSON Schema decoding from a compatible model. It rejects missing
credentials and non-HTTPS base URLs and does not follow redirects.

Set `LLM_PROVIDER=hosted`, `HOSTED_BASE_URL` to the API root (for example,
`https://openrouter.ai/api/v1`), and `LLM_MODEL` to a model that supports strict
structured outputs. Supply `LLM_API_KEY` through the existing Kubernetes Secret.
The base URL is followed by `/chat/completions` by the provider. A cluster
using the default-deny policies also needs TCP 443 egress to the selected
provider before this mode can serve requests.

A hosted request transfers the question and eligible retrieved passages, including
their source, section and page metadata, to that configured service. Enabling this
mode is an explicit deployment choice. The source corpus contains public university
material, but user questions may contain personal information. Provider retention
and processing policies must be reviewed for the actual account used.

Cache keys include the provider mode, hosted endpoint, model, temperature, prompt
revision, requested edition and index generation. A provider change therefore
cannot reuse an answer from another endpoint. Tokens are counted in Prometheus
and in request-scoped logs. API keys and raw question text are excluded from those
request logs.

## Verification

Offline tests check the request schema and authorization header, missing credentials,
malformed responses, retry and fallback behavior. A hosted account and a compatible
configured model are required for a live hosted test. The recorded real-model
baseline uses Ollama.
