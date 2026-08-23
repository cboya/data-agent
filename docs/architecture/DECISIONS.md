# Architecture Decision Register

**Status:** Binding for MVP implementation

This file records choices that Codex should not independently redesign while implementing the MVP.

## D-001 — Harness-centric single-agent architecture

**Decision:** Use one stateful Data Agent harness with deterministic components.

**Rejected for MVP:** multi-agent planner/reviewer/catalog-agent decomposition.

**Reason:** The current problem requires controlled iteration, not agent-to-agent coordination.

---

## D-002 — Python application boundary

**Decision:** Implement the application in Python.

**Expected HTTP boundary:** FastAPI.

**Reason:** Strong LLM/data tooling ecosystem and low MVP implementation cost.

---

## D-003 — Ollama is the local model runtime

**Decision:** Chat and embeddings are both provided by local Ollama.

**Configuration, not code, owns model names.**

Expected environment:

```text
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_CHAT_MODEL=<configured>
OLLAMA_EMBED_MODEL=<configured>
```

The domain layer must depend on internal model interfaces, not Ollama-specific types.

---

## D-004 — Structured outputs are mandatory for control decisions

**Decision:** Model calls that affect control/data contracts use JSON Schema structured output.

At minimum:

- `DialogueDecision`
- retrieval rerank output if LLM-based;
- `QueryPlan`
- SQL repair output.

Free-form text parsing is not an acceptable primary contract.

---

## D-005 — Docker MySQL 8.4 is the deterministic data test world

**Decision:** Codex creates and owns the local synthetic MySQL schema, migrations, and seed data.

**Production database connectivity is out of scope.**

---

## D-006 — Deterministic synthetic fixtures

**Decision:** Test-world fixture generation must be deterministic.

Repeated clean rebuilds must produce the same logical dataset and Golden Dataset answers.

Randomized generation may be used only with a fixed seed and deterministic algorithms.

---

## D-007 — No external vector database in the MVP

**Decision:** Store catalog embeddings locally and search them in-process.

Expose an internal semantic-index abstraction so the storage/search implementation can later be replaced.

---

## D-008 — Hybrid retrieval

**Decision:** Relevant schema discovery combines:

- lexical retrieval;
- embedding retrieval;
- deterministic merge/fusion;
- optional LLM reranking;
- relationship graph expansion.

Pure vector search is not the target architecture.

---

## D-009 — RequirementState is the canonical conversational memory

**Decision:** Current user requirements live in structured `RequirementState`.

Raw message history is audit/context material, not the authoritative requirement model.

---

## D-010 — No automatic semantic promotion from chat

**Decision:** A user statement can change current session requirements but cannot automatically modify curated catalog truth.

---

## D-011 — Read-only SQL runtime

**Decision:** The runtime Data Agent can only read MySQL.

Defense in depth:

1. SELECT-only database principal;
2. deterministic SQL AST policy;
3. resource limits;
4. EXPLAIN gate.

---

## D-012 — SQL is untrusted

**Decision:** LLM-generated SQL must be parsed and inspected before execution.

String/regex-only “contains DELETE” filtering is insufficient.

---

## D-013 — No unrestricted runtime tool

**Decision:** The runtime Data Agent receives no arbitrary shell, filesystem, or Python execution capability.

---

## D-014 — Verification precedes answer generation

**Decision:** Query execution success does not directly transition to answer synthesis. A verification phase is mandatory.

---

## D-015 — Trace and eval from the beginning

**Decision:** Runs, decisions, and evidence must be structured so they can be replayed/evaluated.

Golden Dataset evaluation is part of MVP completion.

---

## D-016 — Repository-local knowledge is authoritative for Codex

**Decision:** Architecture, product intent, plans, contracts, and tests belong in this repository.

`AGENTS.md` is a map, not an encyclopedia.

---

## D-017 — Protocols are adapters, not architecture

**Decision:** MCP/A2A are not part of the MVP core domain model.

If added later, they adapt existing capabilities/contracts rather than redefine them.
