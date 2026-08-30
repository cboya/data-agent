# Data Agent — Codex Development Handoff

**Version:** v0.1.0
**Status:** Phase-1 harness validated; Product behavioral verdict rejected; Phase-2 portability active
**Date:** 2026-08-30
**Target:** Conversational, read-only Data Agent harness with replaceable model/data adapters

## 1. Purpose

This repository packet is the implementation source of truth for an MVP that turns a user's natural-language data request into a verified data result.

The MVP is intentionally constrained:

- provider-neutral model Ports use local Ollama by default and an M16 OpenAI-compatible profile
  when explicitly configured;
- Docker MySQL 8.4 provides a deterministic synthetic business dataset;
- the application owns conversation/session state;
- the system supports multi-turn clarification;
- schema discovery uses hybrid semantic retrieval;
- SQL execution is read-only and deterministically guarded;
- query results are verified before answer synthesis;
- every run is traceable and evaluable;
- the MVP is a **single-agent harness**, not a multi-agent platform.

The implementation objective is not “build a Text-to-SQL demo.” It is:

> Build a small, controlled, observable Data Agent harness in which the model reasons, the harness governs, MySQL provides facts, and verification closes the loop.

## HTTP API

The complete HTTP contract, endpoint examples, response envelopes, error behavior, and client
integration guidance are documented in [`docs/API.md`](./docs/API.md). A running development
server also exposes Swagger UI at `http://127.0.0.1:8000/docs`, ReDoc at
`http://127.0.0.1:8000/redoc`, and the generated OpenAPI schema at
`http://127.0.0.1:8000/openapi.json`.

Windows users should run the repository through WSL2 and Docker Desktop. The complete setup,
model-runtime options, networking checks, troubleshooting steps, and security notes are in
[`docs/WINDOWS.md`](./docs/WINDOWS.md).

## 2. Read order

Codex MUST read these documents before implementation:

1. [`AGENTS.md`](./AGENTS.md) — working rules and repository map.
2. [`ARCHITECTURE.md`](./ARCHITECTURE.md) — system boundary and architecture laws.
3. [`docs/product/MVP.md`](./docs/product/MVP.md) — product behavior and acceptance scope.
4. [`docs/architecture/DECISIONS.md`](./docs/architecture/DECISIONS.md) — decisions already frozen.
5. [`docs/architecture/CONTRACTS.md`](./docs/architecture/CONTRACTS.md) — core data contracts.
6. [`docs/architecture/LLM_INTERACTIONS.md`](./docs/architecture/LLM_INTERACTIONS.md) — model call boundaries.
7. [`docs/architecture/CATALOG_SPEC.md`](./docs/architecture/CATALOG_SPEC.md) — schema/capability discovery.
8. [`docs/architecture/SECURITY.md`](./docs/architecture/SECURITY.md) — non-negotiable safety invariants.
9. [`docs/architecture/EVAL_SPEC.md`](./docs/architecture/EVAL_SPEC.md) — evaluation authority.
10. [`docs/exec-plans/EP-001-MVP.md`](./docs/exec-plans/EP-001-MVP.md) — frozen Phase-1 evidence.
11. [`docs/exec-plans/EP-002-PORTABILITY.md`](./docs/exec-plans/EP-002-PORTABILITY.md) — active
    Phase-2 sequence.

## 3. Document precedence

When documents conflict, use this precedence:

1. `SECURITY.md`
2. `DECISIONS.md`
3. `CONTRACTS.md`
4. `ARCHITECTURE.md`
5. `MVP.md`
6. active execution plan
7. implementation-local comments

Do not silently resolve a conflict by inventing a new architecture. Record the conflict in the active execution plan.

## 4. Expected repository shape after implementation

```text
data-agent/
├── AGENTS.md
├── ARCHITECTURE.md
├── README.md
├── docs/
├── catalog/
├── database/
├── evals/
├── src/
├── tests/
├── compose.yaml
├── Taskfile.yml
├── pyproject.toml
└── .env.example
```

## 5. Required top-level developer commands

Implementation MUST converge on these stable entry points:

```bash
task bootstrap
task dev
task quality
task eval
task reset
```

Semantics:

- `task bootstrap`: validate local prerequisites, start/rebuild MySQL, migrate, seed deterministic fixtures, introspect schema, build retrieval index, run smoke checks.
- `task dev`: run the API in local development mode.
- `task quality`: formatter check + lint + type check + unit/integration/architecture/security tests.
- `task eval`: run the deterministic Golden Dataset evaluation.
- `task m10-eval`: run the standalone SQL guard and JSON EXPLAIN admission evaluation.
- `task reset`: destroy local generated state and reconstruct a clean deterministic environment.

The implementation details behind these commands are intentionally not frozen.

## 6. Definition of implementation readiness

This handoff is ready for Codex because the following are already fixed:

- system scope and non-goals;
- local model runtime: Ollama;
- local data runtime: Docker MySQL 8.4;
- session memory ownership;
- multi-turn clarification model;
- semantic catalog contract;
- hybrid retrieval strategy;
- single-agent architecture;
- SQL safety boundaries;
- trace requirements;
- deterministic test world;
- Golden Dataset as acceptance authority.

Codex is expected to choose implementation details **inside** these boundaries, not redesign them.
