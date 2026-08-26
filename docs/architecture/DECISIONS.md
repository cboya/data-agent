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

---

## D-018 — Control persistence is isolated from analytics data

**Decision:** Store sessions, messages, runs, and artifacts in a dedicated control schema with
a dedicated runtime principal, even when control and analytics schemas share one MySQL server.

The analytics reader has no control-schema privileges. The control runtime principal has no
analytics-schema privileges. Version-controlled migrations own control-schema evolution.

**Reason:** Future catalog introspection must not treat harness state as business data, and the
two capabilities require materially different least-privilege policies.

---

## D-019 — A Run processes one inbound user message

**Decision:** A Run is one bounded processing lifecycle for one inbound user message. `CLARIFYING`
is terminal for that Run; a later user reply creates a new Run in the same active Session.

All Run transitions are validated by deterministic application code. Terminal Runs have no
outgoing transitions.

**Reason:** Conversation continuity belongs to Session, while Run remains a finite, auditable
execution record that never waits for or resumes on later user input.

---

## D-020 — RequirementPatch v0.2 uses explicit scalar mutation operations

**Decision:** Keep persisted `RequirementState` at v0.1 and version its mutation protocol
independently as `RequirementPatch` v0.2. Scalar fields use typed `NO_CHANGE`, `SET`, and `CLEAR`
operations. Omitted scalar operations normalize to `NO_CHANGE`; a bare `null` is never the clear
protocol.

`SET` requires a contract-valid value. `CLEAR` and `NO_CHANGE` reject any non-null value.
Collection replacement fields retain `None = NO_CHANGE`, empty collection = clear, and non-empty
collection = replace. Metric and dimension corrections add explicit remove keys alongside upsert
values; deterministic merge code never infers that one item semantically replaces another.

**Reason:** Mutation intent must survive structured model output, trace/persistence boundaries, and
JSON round-trips without depending on incidental field-presence metadata.

---

## D-021 — Successful dialogue turns commit through one persistence transaction

**Decision:** M8 introduces a narrow dialogue-turn persistence boundary that atomically commits
the inbound user `Message`, optimistic `Session`/`RequirementState` update, and optional assistant
clarification `Message` in one short control-schema transaction.

The model call occurs before the transaction. A stale expected Session revision rolls back the
entire commit and is surfaced to the caller; M8 does not hide the conflict with an automatic retry.

**Reason:** Independent message/session repository writes permit partial durable turns. Holding a
database transaction open during local-model inference is also unsafe and unnecessary.

---

## D-022 — Provider dialogue grammar is normalized before domain merge

**Decision:** The public M8 result remains `DialogueDecision v0.1` carrying
`RequirementPatch v0.2`. The Ollama structured-output boundary uses a narrower
`DialogueProposal v0.1` adapter grammar: scalar/collection mutations are separated from an
action-discriminated `resolution`, ASK requires at least one normalized blocking ambiguity, and
READY permits only non-blocking ambiguity entries. Core time/grain/comparison and
metric/dimension operations are explicit in the provider response. Provider grain/comparison enum
values are deterministically normalized into the public `NO_CHANGE`/`SET`/`CLEAR` scalar union.

Every provider blocking item carries a provider-only `subject_term`; normalization removes it
before constructing the public ambiguity contract. If a proposal marks a scalar field blocking,
the Harness conservatively suppresses that scalar mutation to `NO_CHANGE`. For metric and
dimension collections, only an upsert whose user-facing `term` exactly matches the normalized
blocking `subject_term` is suppressed; unrelated explicit members of the same collection are
retained. A collection remove that cannot be attributed safely while the collection is blocked,
and a whole-list filter replacement proposed with a filter blocker, fail closed rather than
silently losing facts.

**Reason:** Ollama `0.32.15` did not reliably enforce a root discriminated union or choose nested
generic scalar branches for the frozen `gemma4:latest` model. A provider adapter is allowed to be
narrower than the domain contract, while the normalized public contract and deterministic merge
remain provider-neutral. Suppressing a self-contradictory blocking-field mutation prevents guessed
values from entering durable state without introducing natural-language heuristics. Provider-only
subject identity prevents one ambiguous collection member from erasing resolved sibling facts
that bounded future context can recover only from canonical `RequirementState`.

---

## D-023 — Planner sees only the accepted bounded semantic world

**Decision:** M9 admits only a READY `RequirementState` and builds one deterministic planner
context from exactly the final M7 retrieval-hit tables, their matching M6 `CatalogDocument`
values, and only relationships already present in the accepted `RetrievalResult`. The model gets
no full catalog, raw M5 foreign keys, `information_schema`, database credentials, database tools,
or execution capability.

The Harness validates that declared `QueryPlan.tables` is non-empty, unique, and a subset of the
accepted retrieved tables. The SQL string remains opaque and untrusted in M9. M10 exclusively
owns SQL parsing, referenced-table extraction, and enforcement of
`Tables(SQL) ⊆ QueryPlan.tables` plus read-only policy.

**Reason:** Retrieval is a context-authorization boundary. Adding schema outside its final result
would silently bypass M7, while parsing SQL early would blur the separately reviewable M9 semantic
proposal and M10 deterministic security authorities.

---

## D-024 — Planner prompt is domain-neutral

**Decision:** The planner system prompt defines only reasoning discipline, structured-output
requirements, bounded-schema behavior, SQL-dialect constraints, and generic aggregation/join
safety. All concrete business semantics—including physical table/column mappings, metric formulas,
status meanings, time columns, entity grain, and relationship facts—come solely from the supplied
M6 `CatalogDocument` and `Relationship` values plus the READY requirement.

An architecture regression checks every current assembled-catalog table identifier is absent from
the system prompt. Eval cases may assert governed behavior, but passing examples must not be copied
into the higher-priority prompt.

**Reason:** Duplicating curated semantics in the system prompt creates a second authority that can
drift from the fingerprinted catalog and contaminates attribution of planner-eval results. Prompt
discipline and catalog business authority must remain mechanically separable.

---

## D-025 — Raw SQL is data; GuardedQuery is capability

**Decision:** `QueryPlan.sql` remains an untrusted string. M10 parses and classifies it, resolves
physical tables with SQLGlot scopes, applies namespace/table/construct policy, then—and only
then—proves every function belongs to a conservative approved analytics surface before allowing a
Harness-owned `EXPLAIN FORMAT=JSON`. Unknown/`Anonymous` functions fail closed. An internal
immutable `GuardedQuery` binds the exact SQL payload, its SHA-256 digest, QueryPlan identity,
`SQLGuardResult`, and accepted `ExplainResult` for future M11 consumption.

Neither the EXPLAIN adapter nor future execution code should accept arbitrary SQL when the internal
guarded capability can express the required authority. M10 never constructs `EXPLAIN ANALYZE` and
does not submit the candidate as a normal query. Plain MySQL `EXPLAIN SELECT` is not assumed to be
universally non-executing: MySQL documents an optimizer path where a stored function in a subquery
is evaluated and modifies data when the outer query reads a table. The pre-EXPLAIN function
allowlist is therefore part of admission authority, independent of the current reader's routine
privileges.

**Reason:** Separating evidence from capability prevents both validation bypass and a TOCTOU path
where one SQL string is checked and another is explained or executed. EXPLAIN is optimizer
inspection after deterministic guard admission, not a substitute for statement or function
safety. See the MySQL 8.4 [derived-table EXPLAIN side-effect example](https://dev.mysql.com/doc/refman/8.4/en/derived-tables.html).

---

## D-026 — M11 execution is capability-only, streaming, and connection-discarding

**Decision:** M11 accepts only the current immutable `GuardedQuery`, revalidates its SQL digest,
M10 analytics execution namespace, and M10 policy identities, and executes the admitted SQL
unchanged. The namespace against which M10 admitted unqualified tables is fingerprinted into both
guarded capabilities and must equal the runtime default database before connection. Each execution
receives a new analytics-reader connection, verifies session read-only mode, and sets MySQL
`max_execution_time`; the client read timeout is separately bounded above that server limit.

Results use PyMySQL `SSCursor` with row-bound-plus-one detection and a deterministic type-tagged
normalized-byte budget (`result-byte-budget-v0.1`). Actual column metadata and positional values
are retained. Unsupported types fail closed. If unread rows remain after either cap, M11 closes the
dedicated connection without closing the unbuffered cursor, because PyMySQL cursor close exhausts
the remaining result. Errors are typed and never retried. Metadata-only execution evidence is
separate from `ExecutionResult` rows.

**Reason:** A normal string execution API would reopen the M10 authority boundary. Buffered
fetching and cursor-draining cleanup would make the configured row cap cosmetic rather than a
client resource bound, while row count alone cannot bound wide values. Dedicated connections are
the smallest deterministic MVP design that makes early termination safe without a pool protocol.

---

## D-027 — Verification judges existing evidence and is coverage-bounded

**Decision:** M12 accepts one coherent internal evidence context spanning the accepted M9
`PlanningTrace`, M10 `GuardedQuery`, M11 `ExecutionMetadata`, and exact bounded
`ExecutionResult`. It verifies evidence identity before running deterministic structural,
semantic, and empirical checks. It never queries MySQL, calls a model, generates or repairs SQL,
or mutates upstream state.

M11 metadata evolves internally to `execution-metadata-v0.2` and binds the exact bounded result
through a versioned canonical fingerprint over ordered columns, typed positional rows, returned
row count, and truncation state. Public `ExecutionResult v0.1` and `VerificationResult v0.1`
remain unchanged. Internal verification trace records applied checks separately from
not-applicable and unsupported coverage gaps.

**Reason:** SQL execution success and matching row/byte counts do not prove that separately
transported rows belong to the same execution, and current structured semantics cannot prove every
time/formula interpretation. `PASSED` therefore means every applicable encoded invariant passed;
it is not a proof that all possible semantic errors have been excluded. Not checked is never
represented as passed, and evidence-chain mismatch is a typed integrity error rather than an
ordinary business-check failure.
