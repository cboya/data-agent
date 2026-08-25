# EP-001 — Conversational Data Agent MVP

**Status:** Active
**Owner:** Codex implementation agent(s), human architecture review
**Architecture baseline:** v0.1.0

## 1. Goal

Implement the complete local MVP described by the repository with a deterministic MySQL test world, local Ollama chat/embedding models, multi-turn requirement clarification, hybrid schema retrieval, guarded read-only SQL execution, verification, tracing, and Golden Dataset evaluation.

## 2. Non-goals

Do not implement:

- multi-agent orchestration;
- production database integration;
- database writes;
- arbitrary Python/shell tools for the runtime agent;
- external vector database;
- MCP/A2A;
- long-term user-profile memory;
- enterprise metric-store DSL.

## 3. Global acceptance

From a clean local state:

```bash
task reset
task bootstrap
task quality
task eval
```

must pass.

All `SECURITY.md` invariants are mandatory.

## 4. Milestone sequence

Do these in order unless a dependency requires a small preparatory change.

---

### M0 — Repository foundation

Create:

- `pyproject.toml`;
- package layout;
- `Taskfile.yml`;
- config loader;
- test framework;
- logging baseline;
- developer command stubs.

Acceptance:

```text
task quality
```

runs successfully on the initial scaffold.

Do not implement agent behavior yet.

---

### M1 — Deterministic MySQL test world

Create Docker MySQL 8.4 environment.

Implement a realistic synthetic schema containing at least:

```text
dim_user
dim_region
dim_channel
dim_product
dim_category
fact_order
fact_order_item
fact_payment_transaction
fact_refund
fact_user_event
```

Seed deterministic data including analytical traps specified in `MVP.md`.

Create and verify a runtime read-only user.

Acceptance:

- clean rebuild produces stable fixture facts;
- integration test confirms SELECT works;
- integration test confirms write attempt fails at database privilege level.

---

### M2 — Core contracts

Implement the binding models from `CONTRACTS.md`.

Acceptance:

- contract validation tests;
- invalid enum/shape cases fail clearly;
- model-facing contracts reject unknown fields;
- v0.1 version constraints fail closed;
- JSON serialization round-trips for persisted and model-facing contracts;
- architecture test enforces contract-layer dependency purity.

---

### M3 — Persistence and run state

Implement:

- session repository;
- append-only message repository;
- run repository;
- artifact repository;
- explicit run state machine;
- optimistic session concurrency;
- versioned control-schema migrations and least-privilege runtime access.

Acceptance:

- control storage is logically isolated from analytics data;
- control and analytics runtime principals are separate;
- session survives process restart against local DB;
- stale session revision is rejected without lost updates;
- message and artifact persistence are append-only with deterministic message ordering;
- persisted contract JSON is revalidated on read and corruption fails closed;
- one Run represents one inbound user-message lifecycle;
- `CLARIFYING` and all other terminal Run states cannot be resumed;
- legal transitions succeed and invalid transitions fail closed;
- version-controlled migrations are the control-schema authority.

---

### M4 — Ollama adapters

Implement internal ports and Ollama adapters for:

- structured chat;
- embeddings.

Startup diagnostics must validate endpoint/model availability.

Acceptance:

- integration smoke test can obtain a structured model result;
- embedding batch returns consistent dimensions;
- domain code does not depend on Ollama-specific DTOs.

---

### M5 — Catalog introspection

Read `information_schema` and produce generated schema metadata/fingerprint.

Acceptance:

- generated metadata matches fixture schema;
- rebuild is deterministic;
- generated output is clearly separated from curated semantics.

---

### M6 — Semantic catalog merge

Implement curated semantic overlay loading using `catalog/semantic/`.

Create meaningful semantics for synthetic tables.

Acceptance:

- assembled `CatalogDocument` contains metadata + curated semantics;
- invalid curated references to nonexistent tables/columns fail validation.

---

### M7 — Hybrid retrieval

Implement:

- lexical search;
- embedding index/search;
- rank fusion;
- optional reranking only if needed;
- relationship graph expansion.

Acceptance:

- standalone retrieval eval runs;
- meet initial retrieval targets or record exact failures before moving on;
- index fingerprint includes embedding/catalog information.

---

### M8 — RequirementState and clarification loop

Implement dialogue interaction, typed patch merge, blocking ambiguity policy, session update.

Acceptance cases:

- before implementation, freeze scalar replacement semantics so omitted means `NO_CHANGE` and
  explicit clear is represented unambiguously (explicit null or a typed operation);
- “最近销售怎么样？” asks for material clarification;
- resolved metric/time/grain survives multiple turns;
- a fully specified question reaches READY without unnecessary clarification;
- model output cannot directly mutate persistence without validation.

---

### M9 — Query planner

Implement the typed query-planning interaction using only:

- `RequirementState`;
- retrieved catalog documents;
- relevant relationships/business rules.

Acceptance:

- plan parses as `QueryPlan`;
- planner cannot reference schema outside provided context without later guard rejection;
- representative single/multi-table cases generated.

---

### M10 — SQL guard + EXPLAIN gate

Implement deterministic MySQL SQL parsing and policy.

Acceptance:

All `SECURITY.md` guard tests pass, including:

- SELECT/CTE accepted;
- DML/DDL rejected;
- multi-statement rejected;
- forbidden constructs rejected;
- out-of-scope table rejected.

EXPLAIN is executed only after guard pass.

---

### M11 — Read-only runtime

Implement bounded query execution.

Acceptance:

- timeout enforced;
- result cap enforced;
- `ExecutionResult` returned;
- no direct planner-to-database bypass.

---

### M12 — Verification

Implement:

- structural checks;
- initial semantic checks;
- initial empirical checks.

Acceptance:

- result shape mismatch detected;
- representative metric/time/grain mismatch caught where deterministically possible;
- empirical bounds cases tested.

---

### M13 — Bounded repair

Implement maximum configured repair loop.

Acceptance:

- representative unknown-column/syntax error can be repaired;
- repair count is visible;
- policy rejection cannot be repaired around;
- bound cannot be exceeded.

---

### M14 — Answer synthesis + API

Implement final verified-result synthesis and conversation API.

Acceptance:

- clarification and result response contracts work;
- numerical facts are tied to `ExecutionResult`;
- evidence and assumptions returned;
- no synthesis on failed verification.

---

### M15 — Trace + Golden Dataset eval

Complete trace recording and expand Golden Dataset to at least 50 cases.

Acceptance:

- `task eval` produces machine-readable and human-readable report;
- environment/model/index fingerprints captured;
- hard gates and behavioral targets in `EVAL_SPEC.md` pass.

---

## 5. Progress log

Codex must update this section as milestones complete.

```text
[x] M0 Repository foundation
[x] M1 Deterministic MySQL test world
[x] M2 Core contracts — complete and frozen via acceptance PR #2
[ ] M3 Persistence and run state — active
[ ] M4 Ollama adapters
[ ] M5 Catalog introspection
[ ] M6 Semantic catalog merge
[ ] M7 Hybrid retrieval
[ ] M8 RequirementState and clarification loop
[ ] M9 Query planner
[ ] M10 SQL guard + EXPLAIN gate
[ ] M11 Read-only runtime
[ ] M12 Verification
[ ] M13 Bounded repair
[ ] M14 Answer synthesis + API
[ ] M15 Trace + Golden Dataset eval
```

M2 closure evidence (2026-08-25): implementation baseline `66c3d5a`; acceptance PR #2; accepted
head `1f9882b`; squash-merged to `main` as `3400e14db32b2ddd919ca9ab8cba318ad9ceff82`;
focused M2 suite 50 passed; complete `task quality` 57 passed; remote `Delivery / Quality` passed;
substantive review approved. M2 is complete/frozen and M3 is authorized.

M3 progress note (2026-08-25): the implementation candidate uses a dedicated control schema,
checksummed SQL migrations, explicit PyMySQL repository adapters, optimistic Session revision,
append-only Message/Artifact capabilities, and a deterministic atomic Run state machine. The
focused M3/config suite passes 49 tests and complete `task quality` passes 104 tests. Remote
`Delivery / Quality` and substantive review remain pending, so M3 is not complete.

## 6. Decision log

Record implementation choices that resolve `OPEN_QUESTIONS.md`.

Template:

```text
YYYY-MM-DD — OQ-xxx
Decision:
Evidence:
Consequences:
```

2026-08-23 — OQ-008
Decision: Use Taskfile as the stable command facade and uv for Python environment, lockfile,
and command execution. Use Ruff, Mypy, and pytest for the initial quality gate.
Evidence: The M0 scaffold passes `task quality` on the host Python 3.14 environment.
Consequences: Python dependencies are locked in `uv.lock`; uv's cache and virtual environment
are repository-local generated state and excluded from source control.

2026-08-23 — OQ-001
Decision: Configure `gemma4:latest` as the initial local chat model through
`OLLAMA_CHAT_MODEL`; application architecture must remain model-family agnostic.
Evidence: A host smoke test against Ollama `/api/chat` returned a valid object matching a
strict JSON Schema with required fields, an enum constraint, and no additional properties.
Consequences: Local development can proceed without another chat-model download. Startup
diagnostics and M4 integration tests must still fail closed if the configured endpoint or
model becomes unavailable or stops satisfying structured-output requirements.

2026-08-23 — M2 contract hardening
Decision: Reject unknown contract fields, require timezone-aware timestamps, use explicit
`upsert`/`replace`/`add` RequirementPatch field semantics, and define ExecutionResult count as
`returned_row_count == len(rows)` rather than implying knowledge of a pre-truncation total.
Evidence: These rules make the binding architecture invariants executable at the Pydantic
boundary and remove ambiguity before persistence, merge, and bounded execution are implemented.
Consequences: M8 merge logic must consume patch operations rather than regenerated full state;
M11 reports only the bounded returned-row count. Run transition behavior remains deferred to M3.

2026-08-25 — OQ-007 / M3 persistence
Decision: Keep the existing PyMySQL dependency and implement explicit repository ports backed by
a dedicated MySQL control schema. Use ordered, checksummed SQL migration files rather than an ORM
or application-startup `create_all`. Keep optimistic-concurrency revision and message sequence as
persistence metadata so the frozen M2 domain contract shapes do not become database rows.
Evidence: The current test world already uses PyMySQL and MySQL 8.4; raw migrations provide the
smallest coherent addition while preserving explicit mapping and Pydantic revalidation on reads.
Consequences: Repository adapters own UTC/database conversion, JSON validation, transaction
boundaries, and conflict classification. A future ORM may replace the adapter without changing
domain contracts or ports.

2026-08-25 — M3 control and Run lifecycle
Decision: Isolate harness state in a dedicated control schema/principal. Define one Run as one
inbound user-message processing lifecycle; `CLARIFYING` is terminal, later replies create a new
Run in the same Session, and all status transitions pass through a deterministic state machine.
Evidence: This prevents future business catalog introspection from discovering control tables and
keeps finite Run traces separate from long-lived conversation continuity.
Consequences: Terminal Runs cannot be resumed. Message and Artifact have insert/read-only runtime
capabilities; Session and Run add controlled updates; runtime DELETE is unavailable.

## 7. Deviation rule

If implementation reveals that a binding architecture decision is invalid:

1. do not silently work around it;
2. describe the failing assumption;
3. add evidence/test demonstrating the issue;
4. propose the smallest architecture amendment;
5. update the relevant document only after explicit review.
