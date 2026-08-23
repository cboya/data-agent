# Open Implementation Questions

These questions are intentionally **not** architecture blockers. Codex may choose an implementation inside the stated constraints and record the choice in the active execution plan.

## OQ-001 Chat model name

Choose through configuration, not hard-coded behavior.

Required characteristics:

- runs through local Ollama;
- sufficiently reliable with JSON Schema structured output;
- suitable for Chinese/English mixed schema and user requests.

The architecture must not depend on a specific model family.

## OQ-002 Embedding model name

Choose through configuration.

Required characteristics:

- served by local Ollama `/api/embed`;
- suitable for Chinese and English catalog descriptions;
- the same model/configuration must be used for indexing and querying.

Persist an embedding-index fingerprint that includes model name and relevant index version.

## OQ-003 Ollama client implementation

Either:

- official Python client; or
- direct HTTP adapter.

The rest of the application must depend on internal `ChatModel` / `EmbeddingModel` ports.

## OQ-004 Lexical retrieval library

Choose a small, deterministic BM25/full-text implementation appropriate for the MVP corpus.

Do not introduce a distributed search service.

## OQ-005 Hybrid fusion algorithm

Default recommendation: Reciprocal Rank Fusion (RRF) for simple score-scale independence.

A weighted normalized merge is acceptable if tests demonstrate stability.

Record the choice and parameters.

## OQ-006 Reranker

MVP options:

- structured LLM reranking using the chat model;
- deterministic score-only ranking.

Prefer the simplest option that satisfies Golden Dataset retrieval targets.

Do not require a third model runtime without revising this document.

## OQ-007 Persistence implementation

MySQL may store:

- sessions;
- messages;
- runs;
- artifacts.

Choose migration/data-access libraries without changing domain contracts.

## OQ-008 Task runner internals

The public developer interface is frozen as:

```text
task bootstrap
task dev
task quality
task eval
task reset
```

Implementation beneath these commands is open.

## OQ-009 EXPLAIN cost threshold

Calibrate against the synthetic dataset.

Security behavior is frozen: suspicious/unsupported plans fail closed.

Exact cost/row thresholds may be tuned and documented.

## OQ-010 Repair limit

MVP default target is one repair attempt.

If tests justify a different fixed limit, record the decision. Never implement an unbounded loop.
