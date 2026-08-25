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

- internal `ChatModel` and `EmbeddingModel` ports remain provider-neutral;
- integration smoke test can obtain and revalidate a JSON Schema structured model result;
- malformed envelopes and contract-invalid model output fail closed;
- request timeout and transport failures surface as typed adapter errors;
- startup diagnostics validate endpoint, configured model presence, declared capabilities, and
  stable model fingerprints;
- runtime requests remain bound to the startup model fingerprints and fail closed if a configured
  mutable tag resolves to a different digest;
- bilingual embedding batch returns one finite vector per input with consistent dimensions;
- empty/oversized batches and inconsistent embedding responses fail closed;
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
- generated FKs provide connectivity evidence only; relationship cardinality comes exclusively
  from validated curated relationship semantics.
- `Relationship v0.1` connectivity evidence comes only from true single-column generated FKs;
  composite FKs remain generated metadata and are never decomposed into independent edges.
- semantic revision and assembled output are deterministic; generated output does not become
  curated authority.

---

### M7 — Hybrid retrieval

Implement:

- lexical search;
- embedding index/search;
- rank fusion;
- optional reranking only if needed;
- relationship graph expansion.

Acceptance:

- deterministic `RetrievalDocument` projection preserves governed table/column semantics without
  mutating M6 authority;
- provider-neutral M4 embeddings are searched in-process with the same bound immutable model
  identity used for indexing and querying;
- lexical and semantic ranks remain visible through deterministic RRF provenance; graph-added
  tables are explicitly marked `GRAPH_EXPANSION` rather than receiving fabricated ranks;
- relationship expansion traverses only validated M6 `Relationship` values with deterministic
  ordering and explicit hop/total-table bounds;
- standalone retrieval eval reports seed and post-expansion Required Table Recall@5/Recall@10 plus
  relationship-path recovery and meets the frozen 0.90/0.95 recall gates;
- before embedding, validate that the assembled catalog's generated metadata fingerprint and
  semantic revision match the current generated schema and curated semantics, or build the index
  directly from a freshly assembled object; an internally valid but stale catalog must fail closed;
- index identity/fingerprint includes catalog fingerprint, generated schema fingerprint, semantic
  revision, complete embedding `ModelFingerprint`, model runtime version, index format version,
  and retrieval-document builder version; mismatched identities fail closed;
- LLM reranking remains absent unless deterministic retrieval misses the frozen target and measured
  evidence demonstrates that reranking is necessary.

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

- only READY `RequirementState` is admitted;
- deterministic bounded context contains exactly final M7 hit documents and result relationships;
- context identity/endpoint mismatch fails closed;
- plan parses directly as public `QueryPlan v0.1` through provider-neutral M4 `ChatModel`;
- declared plan tables are non-empty, unique, and a subset of retrieved tables;
- SQL remains opaque/untrusted; AST parsing and `Tables(SQL) ⊆ QueryPlan.tables` stay in M10;
- standalone no-execution eval measures parse, table recall/precision/exactness, and expected
  columns across representative business traps.

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
- before persisting execution artifacts, define a metadata-only contract/reference so result rows
  are not automatically written to control-plane storage;
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
- trace persistence stores execution metadata/references, not raw result rows by default;
- hard gates and behavioral targets in `EVAL_SPEC.md` pass.

---

## 5. Progress log

Codex must update this section as milestones complete.

```text
[x] M0 Repository foundation
[x] M1 Deterministic MySQL test world
[x] M2 Core contracts — complete and frozen via acceptance PR #2
[x] M3 Persistence and run state — complete and frozen via PR #3
[x] M4 Ollama adapters — complete and frozen via PR #4
[x] M5 Catalog introspection — complete and frozen via PR #5
[x] M6 Semantic catalog merge — complete and frozen via PR #6
[x] M7 Hybrid retrieval — complete and frozen via PR #7
[x] M8 RequirementState and clarification loop — complete and frozen via PR #8
[ ] M9 Query planner — active
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

M3 closure evidence (2026-08-25): implementation and acceptance PR #3; accepted head `f44f6c3`;
squash-merged to `main` as `aca7868388a580f4a34758942dff441017cbd9b5`; focused M3/config
suite 54 passed; complete `task quality` 109 passed; remote `Delivery / Quality` passed;
substantive review approved. M3 is complete/frozen and M4 is authorized.

M4 closure evidence (2026-08-25): implementation and acceptance PR #4; accepted implementation
head `eac0f18`; final evidence head `a7327f0`; squash-merged to `main` as
`8f26c56c2ad5d2b67561a6e97bed9bf47b627f4b`; focused deterministic M4/API/config suite 31
passed; explicit bound host Ollama smoke 3 passed; complete `task quality` 135 passed with 3
host-only tests skipped; final remote `Delivery / Quality` passed in run `32852333026`;
substantive re-review approved. M4 is complete/frozen and M5 is authorized.

M5 closure evidence (2026-08-25): implementation and acceptance PR #5; accepted final head
`9d8613d`; squash-merged to `main` as `21115b1bc8d7f710f51ed65b12fe6a594012c6b1`;
focused M5 suite 6 passed; integrated `task bootstrap` passed with ten business tables, ten
internal FK groups, and stable generated fingerprint
`7390d087d0c50d152dc7d3e0f0d76e2657a992921bba41606076e63e3f8dbd64`; complete
`task quality` 141 passed with 3 host-only Ollama tests skipped; final remote
`Delivery / Quality` passed in run `32854415366`; substantive review approved. M5 is
complete/frozen and M6 is authorized.

M6 implementation note (2026-08-25): strict safe YAML loading now rejects duplicate/unknown
fields, requires curated coverage for all ten generated tables, validates every curated column and
relationship endpoint, and requires generated FK connectivity evidence without deriving
cardinality from it. Bootstrap assembles ten `CatalogDocument` values and ten curated
relationships into deterministic `catalog/generated/catalog.json`. The generated fingerprint is
`7390d087d0c50d152dc7d3e0f0d76e2657a992921bba41606076e63e3f8dbd64`, semantic
revision is `7f01061e15eabef2122a0fc99c647cf4a110d536eb52ad29a3859b89a0193d50`, and
assembled catalog fingerprint is
`b492ee596e681484d9fabdb8981e773bba78079e15effd7ea1f67e23d10c5b1f`. Focused M6
tests pass 13 tests; integrated `task bootstrap` passes; complete `task quality` passes 154 tests
with 3 explicit host-only Ollama tests skipped. Commit `304729c` closed field-sensitive column
overlay behavior, but substantive re-review clarified that composite generated FKs were still
being decomposed into false single-column connectivity evidence. The current remediation accepts
only true single-column generated FKs for `Relationship v0.1` and its partial-composite regression
passes locally. Remote `Delivery / Quality` passes at remediation head `2f9d202` in run
`32859369209`. Accepted final head `73ece4d`; final remote `Delivery / Quality` passed in run
`32859573749`; substantive re-review approved; squash-merged to `main` as
`6ad9325d1c21cd82f789a0826d248b2e5eba1e4d`. M6 is complete/frozen and M7 is authorized.

M7 implementation note (2026-08-25): deterministic versioned retrieval documents feed
repository-local BM25 and a bound M4 embedding index searched by cosine similarity; RRF (`k=60`)
retains both ranks, and only validated M6 relationships participate in deterministic graph
expansion. Calibrated defaults are four seeds, one hop, and eight total tables. Index identity binds
catalog fingerprint `b492ee596e681484d9fabdb8981e773bba78079e15effd7ea1f67e23d10c5b1f`,
generated fingerprint `7390d087d0c50d152dc7d3e0f0d76e2657a992921bba41606076e63e3f8dbd64`,
semantic revision `7f01061e15eabef2122a0fc99c647cf4a110d536eb52ad29a3859b89a0193d50`,
embedding fingerprint `0112ea4d6590628288600ebd612ee8b094001c1e181c4eda9a64493d205c138f`,
Ollama `0.32.15`, index format `retrieval-index-v0.1`, and builder
`retrieval-document-v0.1`; the resulting 10-document/1024-dimension index fingerprint is
`e0730e5adcc689a62de6042c7cc818626aa8fe5a86d0cf04f2a4a221236c0336`. The frozen
24-case standalone eval passes actual pre-expansion seed Recall@5 `0.990`, seed Recall@10
`0.990`, final Recall@5 `0.990`, final Recall@10 `1.000`, Precision@5 `0.383`, 16-case
relationship-path recovery `1.000`, and mean final table count `6.79`; no LLM reranker is
justified. Substantive review found that the first eval implementation had incorrectly measured
seed recall over the complete fused candidate list rather than the four tables actually passed to
graph expansion. The remediation makes those actual seed hits explicit in `RetrievalTrace`; its
focused one-seed regression reports seed Recall@5/Recall@10 `0.333` and final
Recall@5/Recall@10 `1.000`. The corrected focused M7 suite passes 21 tests including real MySQL
and bound Ollama smoke; `task bootstrap` passes; complete `task quality` passes 175 tests with 4
explicit host-only Ollama tests skipped; corrected `task eval` passes all frozen final recall gates.
Remote `Delivery / Quality` passes on PR #7 at remediation head `42287c0` in run `32865874232`
and final head `89cd20c` in run `32866051635`. Substantive re-review approved the corrected seed
evaluation; PR #7 squash-merged to `main` as
`2dce0428c22faf07f4646856096c37a4cba0ba00`. M7 is complete/frozen and M8 is authorized.

M8 activation note (2026-08-25): `RequirementState` remains v0.1 while its mutation protocol
evolves explicitly to `RequirementPatch` v0.2. Scalar mutations use typed
`NO_CHANGE`/`SET`/`CLEAR`; metric and dimension correction uses explicit remove plus upsert rather
than merge heuristics. Successful dialogue turns will persist the inbound user message, optimistic
Session update, and optional assistant clarification through one short atomic control-schema
transaction after model/policy validation. M9 remains unauthorized.

M8 implementation note (2026-08-26): one bounded structured call consumes canonical
`RequirementState`, the latest user message, and only the last relevant assistant clarification.
Ollama returns provider-facing `DialogueProposal v0.1`; the Harness normalizes it into public
`DialogueDecision v0.1` / `RequirementPatch v0.2`, performs deterministic merge, and owns final
`CLARIFYING`/`READY`/`FAILED` status. ASK grammar requires blocking evidence. Scalar blocker
conflicts become `NO_CHANGE`; collection blockers use provider-only subject identity so only
attributable upserts are suppressed while resolved siblings survive. Unattributable collection
removes and filter-blocker/whole-list replacement combinations fail closed. Successful turns
atomically commit the inbound user message, revision-checked Session state, and optional assistant
clarification after inference/policy.

The initial pre-review standalone dialogue suite contained 24 cases / 28 turns across nine
categories. Bound host evaluation with `gemma4:latest` digest
`c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb`, model
fingerprint `3abd0ade8368742786e7464c1ff3b7ffbdb048bbfb303820725ac724f01bdfe6`, Ollama
`0.32.15`, and prompt `dialogue-understanding-v0.19` passes: action accuracy `1.000`, canonical
state accuracy `1.000`, required clarification recall `1.000`, unnecessary clarification `0.000`,
explicit clear `1.000`, correction `1.000`, multi-turn convergence `1.000`, and mean turns-to-ready
`1.22`. The focused M8 suite passes 71 tests including bound Ollama structured output and real
MySQL atomic success/stale-revision/rollback coverage. Integrated `task bootstrap` passes while
preserving the ten-table deterministic world and M7 index fingerprint
`e0730e5adcc689a62de6042c7cc818626aa8fe5a86d0cf04f2a4a221236c0336`; complete
`task quality` passes 198 tests with 5 explicit host-only tests skipped. M8 remains active until PR
acceptance and merge; M9 remains unauthorized. Remote `Delivery / Quality` passes on PR #8 at
implementation head `03f2e44` in run `32882403836`.

M8 substantive-remediation note (2026-08-26): initial review found that field-wide suppression for
metric/dimension/filter collections could erase an explicit sibling fact, which bounded next-turn
context could not recover from raw history. `DialogueProposal` blocking items now carry a
provider-only exact `subject_term`; normalization strips this metadata from public `Ambiguity`,
suppresses only matching metric/dimension upserts, and fails closed for collection operations that
cannot be safely attributed. The frozen suite adds the two-turn “实际支付金额 + 销售情况” case and
requires `paid_amount` to remain canonical while “销售指 GMV” produces `[paid_amount, gmv]`
without replaying the first user message. Prompt `dialogue-understanding-v0.20` passes the expanded
25-case / 30-turn bound-host eval with action accuracy `1.000`, canonical state accuracy `1.000`,
required clarification recall `1.000`, unnecessary clarification `0.000`, explicit clear `1.000`,
correction `1.000`, multi-turn convergence `1.000`, and mean turns-to-ready `1.26`. The focused M8
suite passes 76 tests including real Ollama and MySQL atomic-turn coverage; `task bootstrap`
passes with the unchanged M7 index fingerprint; complete `task quality` passes 203 tests with 5
explicit host-only tests skipped. Remediation head `906f365` passes remote `Delivery / Quality` in
run `32885561101`. M8 remains active pending substantive re-review and merge; M9 remains
unauthorized.

M8 closure evidence (2026-08-26): implementation and acceptance PR #8; collection-continuity
remediation commit `906f365`; accepted final head `7dc73fe`; substantive re-review approved; final
remote `Delivery / Quality` passed in run `32885719303`; squash-merged to `main` as
`a71c1037d46e5aaa73586d3ba6a40c8871dffccc`. Focused M8 suite passed 76 tests, complete
`task quality` passed 203 tests with 5 explicit host-only tests skipped, and the frozen 25-case /
30-turn dialogue eval passed all gates. M8 is complete/frozen and M9 is authorized/active; M10
remains unauthorized.

M9 implementation note (2026-08-26): `PlannerContextBuilder` admits only READY requirements and
projects the exact ordered M7 final-hit documents plus only result-carried relationships, while
revalidating M6 document/relationship authority, catalog identity, retrieval-index identity, a
maximum eight-table bound, and a 64,000-character context bound. `gemma4:latest` consumes this
context through the provider-neutral M4 `ChatModel` and returns public `QueryPlan v0.1` directly;
real evidence did not justify a provider DTO. `PlannerPolicy` validates non-empty unique declared
tables within the retrieved set and bounded assumptions/expected columns, while deliberately
leaving SQL opaque for M10. Internal `PlanningTrace` and eval identity retain prompt, chat model,
runtime, retrieval index, catalog/generated schema, and semantic-revision provenance without
polluting `QueryPlan`.

The frozen standalone M9 suite contains 21 no-execution cases across single-table aggregation,
time grain, metric semantics, dimension/relationship paths, payment attempts, refund/net revenue,
fan-out, irrelevant context, bounded-world injection, and expected shape. Bound-host evaluation
with `gemma4:latest` digest
`c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb`, model
fingerprint `3abd0ade8368742786e7464c1ff3b7ffbdb048bbfb303820725ac724f01bdfe6`, Ollama
`0.32.15`, prompt `query-planning-v0.2`, and retrieval index
`e0730e5adcc689a62de6042c7cc818626aa8fe5a86d0cf04f2a4a221236c0336` passes:
structured parse `1.000`, allowed-table compliance `1.000`, out-of-context probe rejection
`1.000`, required-table recall `0.984`, plan-table precision `1.000`, exact required table set
`0.952`, and expected-column accuracy `1.000`. Non-gating representative SQL string evidence is
`0.619` and makes no syntax, safety, execution, or result claim. Broad 6–8-table schema slices do
not reduce plan-table precision, so M9 evidence does not justify changing M7 or adding reranking.
The real bound-Ollama smoke passes direct QueryPlan parsing, seven-table-to-one-table narrowing,
stable output aliases, and MySQL `DATE_SUB` syntax. The serial eval uses a separately configured
180-second per-case timeout while normal model calls retain the existing 60-second default.
`task bootstrap` passes with the unchanged
retrieval fingerprint; focused deterministic M9/CLI tests pass 16 tests; complete `task quality`
passes 218 tests with 6 explicit host-only tests skipped. PR #9 implementation head `54c6d4b`
passes remote `Delivery / Quality` in run `32892383013`. M9 remains active pending substantive
review; M10 remains unauthorized.

M9 semantic-authority remediation note (2026-08-26): substantive review found that prompt v0.2
duplicated concrete synthetic-world metric, table, column, status, and time mappings already owned
by M6, creating a higher-priority semantic authority that could drift from the fingerprinted
catalog. Prompt `query-planning-v0.3` is domain-neutral: it defines bounded planning discipline,
structured output, MySQL dialect, and generic fan-out safety, while every concrete business fact
comes only from the READY requirement and supplied M6/M7 semantic context. D-024 freezes this
boundary, and an architecture regression enumerates the current assembled catalog and rejects any
concrete table identifier in the system prompt.

The unchanged 21-case bound-host suite passes after removing all answer hints: structured parse,
allowed-table compliance, out-of-context probe rejection, required-table recall, and
expected-column accuracy are each `1.000`; plan-table precision is `0.934`; exact required table set
is `0.905`. Non-gating representative SQL string evidence is `0.667` and remains explicitly
non-authoritative. These metrics meet the original frozen gates without changing M6, M7, the
Golden cases, or the acceptance targets, so the de-leaked results demonstrate that governed
catalog context itself is sufficient. The focused M9/CLI suite passes 17 tests, the real
bound-Ollama smoke passes, and complete `task quality` passes 219 tests with 6 host-only tests
skipped. M9 remains active pending remediation push, remote `Delivery / Quality`, and substantive
re-review; M10 remains unauthorized.

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
domain contracts or ports. Before any pending SQL executes, the migration plan requires the
applied ledger to be an exact checksum-matching prefix of repository history; only a new suffix
may be applied.

2026-08-25 — M3 control and Run lifecycle
Decision: Isolate harness state in a dedicated control schema/principal. Define one Run as one
inbound user-message processing lifecycle; `CLARIFYING` is terminal, later replies create a new
Run in the same Session, and all status transitions pass through a deterministic state machine.
Evidence: This prevents future business catalog introspection from discovering control tables and
keeps finite Run traces separate from long-lived conversation continuity.
Consequences: Terminal Runs cannot be resumed. Message and Artifact have insert/read-only runtime
capabilities; Session and Run add controlled updates; runtime DELETE is unavailable.

2026-08-25 — OQ-003 / M4 Ollama adapter
Decision: Use a small asynchronous adapter over the Python standard-library HTTP client, keeping
Ollama request/response objects private. Expose only provider-neutral `ChatModel`,
`EmbeddingModel`, and `ModelRuntimeProbe` ports. Bound time, response bytes, and embedding batch
size in configuration; send Pydantic JSON Schema for structured chat and revalidate the returned
JSON through the requested contract.
Evidence: Host probes against Ollama 0.32.15 produced a strict `gemma4:latest` structured result
and a two-item Chinese/English `qwen3-embedding:0.6b` batch with consistent 1024 dimensions.
Consequences: Application startup fails when endpoint, model, digest, or required capability
cannot be proven. Model fingerprints include provider/name/digest/capabilities/metadata so later
index and trace fingerprints can bind to an immutable model identity without importing Ollama
DTOs into domain code.

2026-08-25 — M4 immutable model identity binding
Decision: Require each Ollama chat/embedding adapter to consume the corresponding startup
`ModelFingerprint`. Revalidate the configured tag-to-digest mapping immediately before every
execution and raise a typed identity-drift error before `/api/chat` or `/api/embed` when it no
longer matches. Keep this enforcement provider-local; the provider-neutral model ports do not
change.
Evidence: Ollama 0.32.15 on the supported host rejects both `tag@digest` and
`tag@sha256:digest` through `/api/show` with HTTP 400, while digest-only references do not resolve.
The adapter therefore cannot bind execution by sending a digest-qualified model reference.
Consequences: A mutable tag cannot silently move after startup while traces or future indexes
continue to claim the earlier fingerprint. The fallback adds one bounded `/api/tags` identity
check immediately before each inference request; inability to prove the mapping fails closed.

2026-08-25 — M5 deterministic catalog introspection
Decision: Read MySQL metadata through the analytics read-only principal with every
`information_schema` query explicitly scoped to the configured analytics schema. Normalize base
tables, ordered columns, PK flags, internal FK groups, and database comments into a versioned JSON
artifact. Compute its SHA-256 over canonical content without timestamps and write only beneath
`catalog/generated/`; reject semantic-output paths and cross-schema foreign keys.
Evidence: The deterministic M1 world exposes ten analytics base tables and ten internal FK groups
through the analytics reader. Integrated `task bootstrap` produced a stable canonical artifact
with fingerprint `7390d087d0c50d152dc7d3e0f0d76e2657a992921bba41606076e63e3f8dbd64`;
the M3 control schema is absent from the output.
Consequences: Repeated introspection of unchanged schema produces identical bytes and fingerprint.
M6 may merge this artifact with repository-curated semantics but must not hand-maintain generated
content. M7 must compose its index fingerprint from the generated schema fingerprint, semantic
revision, complete embedding fingerprint, Ollama runtime version, and index format/version.

2026-08-25 — M6 curated semantic authority
Decision: Load repository YAML with safe parsing into strict Pydantic overlays, require exact
generated-table coverage, and reject nonexistent table/column/relationship endpoints. Assemble
sorted `CatalogDocument` values by overlaying curated text on M5 metadata, and compute one
canonical semantic revision over the normalized curated tables and relationships. Emit
`Relationship.cardinality` exclusively from curated relationship YAML; generated FKs never infer
cardinality. Apply column overlays field by field: a non-null curated description overrides the
generated database comment, an omitted description inherits it, and aliases enrich independently.
Because `Relationship v0.1` expresses one column pair, accept connectivity evidence only from a
true single-column generated FK; preserve composite FKs as generated metadata without decomposing
their component columns into independent relationships.
Evidence: M5 proves join connectivity but intentionally omits unique-index metadata, so an FK
alone cannot distinguish one-to-one from many-to-one. The completed curated sources cover ten
tables and ten FK-backed relationships; integrated bootstrap produces stable semantic revision
`7f01061e15eabef2122a0fc99c647cf4a110d536eb52ad29a3859b89a0193d50`.
Consequences: Curated semantic mistakes fail bootstrap rather than leaking into retrieval.
`catalog/generated/catalog.json` is rebuildable assembled output; only `catalog/semantic/*.yaml`
is semantic authority. M7 consumes the generated fingerprint and semantic revision without
recomputing business meaning.

2026-08-25 — OQ-002/OQ-004/OQ-005/OQ-006 / M7 deterministic hybrid retrieval
Decision: Project each M6 `CatalogDocument` into versioned deterministic retrieval text. Implement
repository-local BM25 with Unicode NFKC/casefold tokenization, ASCII identifier splitting, and CJK
character/bigram terms; use cosine similarity over M4 `EmbeddingModel` vectors; fuse lexical and
semantic ranks with RRF (`k=60`); and use the top four fused candidates as graph-expansion seeds,
with calibrated defaults of one hop and eight total tables. Do not add an LLM reranker while
deterministic retrieval meets the frozen eval gate. Traverse only M6 `Relationship` objects with
deterministic bounded breadth-first expansion.
Evidence: The controlled catalog contains ten bilingual documents, so an external lexical/search
dependency or vector database adds no acceptance value. RRF is score-scale independent, and the
existing M4 port already binds `qwen3-embedding:0.6b` requests to an immutable startup fingerprint.
The corrected 24-case controlled-world run measures only the actual four pre-expansion seeds,
reports seed Recall@5/Recall@10 `0.990`, and retains final Recall@5 `0.990`, Recall@10 `1.000`,
and path recovery `1.000` while reducing mean final tables from `8.75` to `6.79`.
Consequences: Lexical/semantic provenance remains visible, graph-added tables have no fabricated
ranks, and retrieval behavior is independently evaluable without dialogue, planning, or SQL.

2026-08-25 — M7 retrieval index identity and stale protection
Decision: Persist a generated in-process index whose canonical identity binds the assembled catalog
fingerprint, generated schema fingerprint, semantic revision, complete embedding model fingerprint,
Ollama runtime version, index format version, and retrieval-document builder version. The complete
artifact fingerprint also covers projected documents and vectors. Build/load compares identity to
the current generated schema, curated semantics, assembled catalog, and runtime model identity.
Evidence: An internally self-consistent M6 catalog or M7 index can still be stale relative to current
generated/curated sources; identity comparison is therefore required in addition to self-hashing.
Consequences: Model, runtime, schema, semantics, projection, or index-format drift fails closed and
requires rebuild. Generated index files remain beneath `catalog/generated/` and are never semantic
authority.

2026-08-25 — M8 explicit requirement mutation and dialogue-turn persistence
Decision: Version `RequirementPatch` independently as v0.2 while preserving `RequirementState`
v0.1. Scalars use explicit `NO_CHANGE`/`SET`/`CLEAR`; collection correction uses explicit keyed
remove/upsert. Compose successful dialogue persistence behind one transaction that writes the user
message, revision-checked Session state, and optional assistant clarification. Run local-model
inference before opening that transaction and surface revision conflict without hidden retry.
Evidence: The v0.1 scalar replacement fields cannot distinguish explicit clear from no change
without depending on JSON field-presence metadata, and independent M3 Session/Message repository
writes cannot prevent a partially durable successful turn.
Consequences: JSON/trace/persistence round-trips retain scalar intent. The model proposes mutation
and action, while deterministic merge/policy owns canonical state and status. Failed model/policy
turns persist nothing; concurrency conflict rolls back the complete durable turn and requires the
caller to rerun it.

2026-08-26 — M8 provider dialogue grammar and blocker/mutation conflict handling
Decision: Use a provider-facing `DialogueProposal v0.1` with an action-discriminated resolution
and explicit core mutation choices, then normalize and revalidate public `DialogueDecision v0.1`
and `RequirementPatch v0.2`. ASK requires at least one normalized blocking item carrying a
provider-only exact `subject_term`, which is removed at the public contract boundary. Scalar
blockers suppress their scalar mutation. Metric/dimension blockers suppress only an upsert whose
user-facing `term` matches that subject; unrelated same-collection members survive. Unattributable
collection removes and filter blocker plus whole-list replacement fail closed.
Evidence: Ollama `0.32.15` with frozen `gemma4:latest` did not reliably enforce a root union and
could emit a guessed time mutation together with a time blocker. Provider enum normalization plus
scalar blocker suppression closes those contradictions. Substantive review identified that the
original field-wide collection rule erased explicit siblings; a pure normalization regression and
the 25-case bounded two-turn eval now require those facts to remain canonical.
Consequences: Provider grammar may be narrower than the domain contract, but it is not semantic
authority. The public patch remains provider-neutral, mutation intent is traceable, contradictory
blocking-subject values fail conservatively, unrelated explicit collection facts survive, and no
natural-language parsing moves into the Harness.

2026-08-26 — M9 bounded planner authority and SQL trust boundary
Decision: Admit only READY canonical requirements. Build planner context deterministically from
exactly M7 final-hit `CatalogDocument` values and `RetrievalResult.relationships`, validated
against current M6 catalog and retrieval-index identity. Use direct structured `QueryPlan v0.1`
output, and enforce only declared plan-table scope in M9.
Evidence: M7 already exposes an accepted final schema slice and M10 is the dedicated SQL AST/security
milestone. The existing QueryPlan shape is provider-simple and separates declared semantic scope
from still-untrusted SQL text. The 21-case bound-host eval parses public QueryPlan directly in all
cases and achieves required-table recall `0.984`, table precision `1.000`, exact set `0.952`, and
expected-column accuracy `1.000`; broad M7 context does not justify a reranker or provider DTO.
Consequences: The planner has no catalog/database discovery capability. Out-of-context declared
tables fail closed, while a SQL string that lies about its table set is intentionally deferred to
M10 rather than receiving a false M9 safety claim. Planner provenance stays in internal trace/eval
identity, not QueryPlan.

2026-08-26 — M9 system-prompt semantic authority purity
Decision: Keep the planner system prompt domain-neutral. It may define reasoning, output, dialect,
and generic join/aggregation discipline, but all concrete business meanings and physical mappings
come exclusively from the bounded M6 catalog slice and READY requirement. Mechanically reject
current catalog table identifiers in the prompt.
Evidence: Substantive review found v0.2 duplicated governed synthetic-world answers. After removing
them, prompt v0.3 passes the same 21-case suite with parse/allowed/escape/recall/columns `1.000`,
table precision `0.934`, and exact set `0.905`, without changing M6, M7, Golden cases, or gates.
Consequences: Eval attribution is clean, catalog revisions cannot conflict with a stale
higher-priority business mapping in the prompt, and case-specific performance improvements must be
made in the true authority layer rather than accumulating an implicit semantic layer in prompts.

## 7. Deviation rule

If implementation reveals that a binding architecture decision is invalid:

1. do not silently work around it;
2. describe the failing assumption;
3. add evidence/test demonstrating the issue;
4. propose the smallest architecture amendment;
5. update the relevant document only after explicit review.
