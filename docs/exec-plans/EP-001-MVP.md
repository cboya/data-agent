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

- MySQL SQL parses as exactly one read-only `SELECT`/set query through SQLGlot;
- scope-aware physical-table resolution covers CTEs, nested/derived queries, unions, and
  shadowing without treating aliases as physical tables;
- `Tables(SQL) ⊆ QueryPlan.tables`; unused declared tables remain visible evidence;
- only unqualified or configured analytics-schema tables are authorized;
- DML, DDL, unsupported statements, recursive CTEs, file access, delays, locks, and hints fail
  closed;
- every function is recognized as part of the versioned EXPLAIN-safe analytics surface; unknown,
  stored-function, and loadable-function shapes fail closed before the provider;
- exact SQL text/digest, plan identity, guard evidence, and EXPLAIN evidence bind an internal
  immutable `GuardedQuery` capability;
- only the Harness may construct `EXPLAIN FORMAT=JSON`, and only after guard pass;
- malformed/unsupported EXPLAIN evidence or a per-access row estimate above the configured bound
  fails closed;
- the standalone M10 eval scores the frozen adversarial corpus and separately reports parse,
  guard, table-scope, and EXPLAIN results for accepted M9 proposals;
- no normal query is executed and no SQL result-correctness claim is made.

---

### M11 — Read-only runtime

Implement bounded query execution.

Acceptance:

- the only public query-execution input is the immutable M10 `GuardedQuery` capability; raw SQL,
  `QueryPlan`, and pre-EXPLAIN `GuardedSQL` have no runtime route;
- capability SQL digest and issuing guard/EXPLAIN policy identities are revalidated immediately
  before execution; M10's analytics execution namespace is fingerprinted and must match the M11
  runtime database before connection; the exact admitted SQL is then sent unchanged to MySQL;
- a dedicated analytics-reader connection enables and verifies session read-only mode and a
  server `max_execution_time`; a bounded client read timeout is greater than the server bound;
- execution uses an unbuffered cursor, never `fetchall`, reads at most the configured row bound
  plus one, and abandons the dedicated connection without draining the remaining result when
  truncation is detected;
- row and deterministic normalized-byte budgets are both authoritative and visible in metadata;
- `ExecutionResult` columns come from cursor metadata, positional rows preserve duplicate names,
  exact `Decimal` values survive, and unsupported result values fail closed;
- typed errors distinguish capability integrity, query timeout, database availability/execution,
  and result decoding, with no hidden retry and bounded sanitized provider detail;
- execution metadata carries capability/policy/database/bound/outcome identity separately from
  the `ExecutionResult`; full raw rows are not automatically written to control-plane storage;
- an independent deterministic runtime eval proves capability-only admission, read-only authority,
  timeout, row/byte bounds, actual shape, and numeric fidelity without claiming semantic
  correctness;
- no direct planner-to-database bypass.

---

### M12 — Verification

Implement deterministic verification over one coherent M9 planning, M10 capability, M11 metadata,
and exact bounded-result context. The verifier judges existing evidence only; it has no database,
model, mutation, synthesis, or repair authority.

Acceptance:

- evidence identity binds the exact M9 bounded PlannerContext, plan, capability, SQL, policies,
  namespace, successful execution, and a versioned fingerprint of the exact bounded result;
  mismatch raises `VerificationIntegrityError`;
- structural checks reject runtime truncation and shape/count/metadata inconsistency while allowing
  a coherent empty result;
- semantic checks require READY state, required metric/dimension outputs, `period` for grain,
  exact RequirementState-owned public output shape, no unrequested public aggregate grain,
  uniquely governed requested-dimension projection lineage, unique governed metric column sources
  where provable, and direct joins authorized by bounded M6 relationships;
- unsupported/ambiguous time, formula, or SQL semantics become explicit coverage gaps rather than
  successful checks or heuristic/model judgments;
- empirical checks enforce generic COUNT, finite-numeric, and grouping-key invariants without a
  second business-semantics registry;
- internal trace separates applied checks from not-applicable/unsupported coverage; public
  `VerificationResult v0.1` remains unchanged;
- standalone deterministic eval reports layer accuracy, false accept/reject, identity/truncation
  rejection, and coverage without claiming complete business correctness.

---

### M13 — Bounded repair

Implement one typed, persisted, maximum-configured repair branch over the same frozen M9
`PlannerContext`.

Acceptance:

- repair eligibility is a default-deny typed allowlist and never depends on free-text matching;
- eligible SQL syntax, approved MySQL unknown/ambiguous-column, and selected M12 formulation
  failures may propose one replacement full `QueryPlan` under exactly the original
  `PlannerContext`;
- policy/cost/integrity/capability/namespace/availability/timeout/decoding/truncation failures and
  verification coverage gaps make zero repair-model calls and do not increment `repair_count`;
- an attempt is atomically claimed in the control database before the model call; model failure
  consumes the attempt and concurrent callers cannot exceed the configured bound;
- failure evidence fingerprints its source Run; a supplied Run mismatch fails before repository or
  model access, and the typed failure stage is checked against the exact expected Run state under
  the same row lock that consumes the attempt;
- replacement evidence is a new branch and must run M9 policy, full M10 guard plus EXPLAIN, M11
  execution, and M12 verification from scratch; failed evidence is never overwritten or reused;
- the repair prompt treats bounded diagnostic detail as untrusted data and cannot widen retrieval,
  catalog, tables, RequirementState, or the PlannerContext;
- internal `RepairFailure` and `RepairTrace` bind the failure, original/replacement plan,
  unchanged PlannerContext, prompt/model/runtime, attempt, outcome, and successful final
  verification identities without retaining raw result rows;
- deterministic standalone evaluation reports eligibility accuracy, policy/integrity zero-call
  accuracy, and bound enforcement; the separate real-model report covers eligible first-attempt
  success and post-repair M12 pass;
- a bounded real-Ollama corpus covers syntax, unknown-column, and one selected semantic
  verification formulation failure through a final M12 PASS.

---

### M14 — Answer synthesis + API

Implement final verified-result synthesis and conversation API.

Acceptance:

- only one coherent final branch ending in M12 `VerificationTrace.result.status == PASSED` may
  enter synthesis; a successful M13 replacement branch supersedes its failed original for answer
  data without erasing historical repair provenance;
- the provider-facing `AnswerProposal` contains answer language plus positional result-cell
  references only; deterministic code owns data, assumptions, SQL/tables, timing/counts, repair
  count, verification status/coverage, synthesis mode, and Run state;
- every result numeric fact must be grounded in a referenced exact `ExecutionResult` value;
  model-side arithmetic-derived percentages/deltas absent from verified SQL output fail closed;
- `VerificationTrace` unsupported coverage is user-visible, not-applicable checks are not presented
  as passed, and a policy/coverage-bounded PASS is never described as exhaustive proof;
- answer context has independent row/byte bounds; oversized verified results use an explicit
  deterministic no-new-facts fallback rather than a partial model summary;
- clarification atomically commits Session/Message state with Run `CLARIFYING`; final assistant
  answer persistence and `SYNTHESIZING → COMPLETED` are one control-plane transaction;
- `POST /sessions`, `POST /sessions/{id}/messages`, `GET /sessions/{id}`, and `GET /runs/{id}`
  return typed clarification/result/safe-failure envelopes with exact Decimal serialization;
- clarification and failed/terminal verification paths make zero downstream/answer-model calls;
- focused deterministic, bound real-Ollama answer, and end-to-end API/MySQL/Ollama evidence pass.

---

### M15 — Trace + Golden Dataset eval

Complete append-only structured trace recording, expand the public-API Golden Dataset to at least
50 cases, and make clean-state MVP acceptance reproducible under a complete environment identity.

Acceptance:

- Trace records observable evidence rather than hidden reasoning and never becomes domain/runtime
  authority;
- a dedicated append-only control store assigns contiguous per-Run sequence and records attempt,
  stage, event type, schema version, bounded payload, fingerprint, and timestamp;
- dialogue, retrieval, planning, admission, execution, verification, repair, synthesis, and terminal
  outcomes are covered without default raw-result-row or duplicated-answer persistence;
- deterministic completeness policy validates clarification, direct success, terminal failure, and
  repaired success shapes plus identity/order/attempt invariants;
- trace persistence failure cannot silently continue to a successful response, and required
  terminal evidence is coordinated with durable terminal Run state;
- versioned Golden Dataset contains at least 50 meaningful cases and exercises the public Session
  and Message HTTP surface with deterministic semantic/result oracles rather than exact SQL text;
- runtime and prompts have no access to Golden expectations or oracle SQL;
- every final report binds Git, suite, schema/catalog/index, model/runtime, prompt/policy,
  dependency, and Python identities under one environment fingerprint;
- canonical `task eval` preserves every stage gate, adds Golden E2E and trace integrity metrics,
  writes human-readable output plus ignored `evals/reports/latest.json`, and attributes failures;
- clean `task reset`, `task bootstrap`, `task quality`, and `task eval` all pass without generated
  source drift.

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
[x] M9 Query planner — complete and frozen via PR #9
[x] M10 SQL guard + EXPLAIN gate — complete and frozen via PR #10
[x] M11 Read-only runtime — complete and frozen via PR #11
[x] M12 Verification — complete and frozen via PR #12
[x] M13 Bounded repair — complete and frozen via PR #13
[x] M14 Answer synthesis + API — complete and frozen via PR #14
[x] M12 targeted false-acceptance remediation — complete and frozen via PR #16
[x] M8 targeted deterministic-readiness remediation — complete and frozen via PR #17
[x] M8 targeted time-range admission remediation — complete and frozen via PR #18
[ ] M15 Trace + Golden Dataset eval — resumed final acceptance / Draft PR #15
```

M12 targeted-remediation activation (2026-08-27): M14 is squash-merged at
`8cf14aa2766603ffb581abf8fb08874dbdd3e478`. Draft PR #15 diagnosis at
`395991b3ec66531362973da8c44d853cb59d9c53` found six frozen cases where M12 returned `PASSED`
while the deterministic Golden Oracle failed: four unrequested aggregate-grain expansions and two
public dimension shapes whose generic `channel` identity could not be proven from the bounded M6
catalog. M15 remains paused and untouched. This isolated remediation reopens only M12 to make the
READY RequirementState the independent public-shape authority, add exact six-case deterministic
regressions, and enforce `verified_oracle_mismatch_count == 0`; M8/M9/M10/M11/M13/M14 behavior,
Golden/Oracle truth, model/resource configuration, and acceptance thresholds remain frozen.

M12 targeted-remediation local evidence (2026-08-27): `verification-policy-v0.2` and
`verification-trace-v0.2` add separately typed requested-output resolution, public-shape,
dimension-source authority, dimension-projection lineage, and analytical-grain checks. All six
frozen IDs (`simple-gmv`, `simple-paid-amount`,
`simple-payment-attempts`, `join-net-revenue`, `agg-gmv-channel`, `agg-orders-channel`) now end in
deterministic `SEMANTIC_FAILURE`; the 24-case standalone report passes with structural, semantic,
empirical, identity, PlannerContext-substitution, and truncation metrics at `1.000`, false accept
and false reject at `0.000`, `verified_oracle_mismatch_count=0`, and coverage `0.914`. Clean
`task bootstrap` passed against an isolated local control schema and reproduced the ten-table
world plus retrieval index `e0730e5adcc689a62de6042c7cc818626aa8fe5a86d0cf04f2a4a221236c0336`.
The complete M12 suite passes 38 tests; the focused M12/M13 review set passes 62 tests; `task
quality` passes 447 tests with 7 explicit host-only
skips. Downstream deterministic M13 and M14 evals remain green (19 and 7 cases respectively, every
reported authority metric `1.000`). No large-model or full 59-case M15 suite was run. The
remediation is ready for a focused PR and substantive review; it is not authorized for merge, and
M15 remains paused/Draft.

M12 targeted-remediation closure (2026-08-27): PR #16 final accepted head
`a058090398ffe9c9e84abac87d224fbf82a13191` was substantively approved and squash-merged to
`main` as `f0d248f872bd0d2a81918cf56e9d4d8bb7d73969`. M12 is complete/frozen again. M15 stays
paused/Draft and its behavioral acceptance remains failed.

M8 targeted-readiness activation (2026-08-28): diagnosis evidence at Draft PR #15 proved all 35
unexpected-clarification cases reproduce in standalone M8, with zero M14 integration,
provider/runtime, or Golden/Oracle ownership. This isolated remediation reopens only M8 from
`main@f0d248f872bd0d2a81918cf56e9d4d8bb7d73969`. The model's action and ambiguity values become
candidates; internal `blocking-ambiguity-policy-v0.1` must derive the final action from a
provisional merged RequirementState and stable reason codes. Missing optional time/grain is not a
blocker, resolved metric/dimension facts outrank model uncertainty, and only unresolved material
alternatives may remain blocking. M9–M15 behavior, Draft PR #15, Golden/Oracle truth, model and
resource identity, and acceptance thresholds remain frozen.

M8 targeted-readiness implementation note (2026-08-28): normalization now preserves an
unsuppressed candidate patch for provisional merge, after which deterministic policy classifies
each blocker before suppressing only proven conflicting mutations and rebuilding the public
decision. The exact 35-case / 36-turn diagnosis proposals are frozen in provider-free fixtures,
alongside metric, dimension, explicit-time, and explicit-grain positive controls. The resulting
39-case / 40-turn suite fingerprint is
`38ac3cb618b544a443458e29a7b98692f18cf53d4a3a6f3efd0cbedd9a07b840`; initial focused evidence
reports unnecessary clarification `0`, necessary clarification recall `1.000`, false READY `0`,
and action/state/reason/scope preservation each `1.000`. Existing `v0.20` bound evidence showed
true blockers omitted competing options and unresolved metric items, so the smallest documented
wire amendment is `dialogue-understanding-v0.21`: optional time/grain stays absent, each real
blocker supplies at least two structured alternatives, and metric/dimension blockers carry a
matching `UNRESOLVED` item. Public M8 contracts, bounded context, persistence, CAS, and rollback
remain unchanged. Focused M8 contracts/dialogue/persistence/conversation coverage passes 53
tests. Isolated `task bootstrap` passes with ten tables, ten orders, paid amount `1545.00`,
successful refunds `110.00`, and unchanged retrieval index
`e0730e5adcc689a62de6042c7cc818626aa8fe5a86d0cf04f2a4a221236c0336`; complete `task quality`
passes 455 tests with 7 explicit host-only skips. `task m8-readiness-eval` passes every exact gate.
The optional targeted live replay was not run because the frozen local chat model is the 30B
effect-acceptance model and the approved resource boundary forbids a large local run here. Focused
PR #17 is open for substantive M8 review at implementation head
`b77640b6d5ee04e2562931ee40cf0efd58461acc`; remote `Delivery / Quality` passes in workflow run
`33093127780`. The remediation is not authorized for merge, M8 remains open pending substantive
review, and Draft PR #15 remains paused and untouched.

M8 targeted-readiness substantive remediation (2026-08-29): exact PR #17 review accepted the
provisional-state authority inversion and ultimately retained one narrow control-plane blocker: a
provider candidate whose structured evidence proves neither blocking nor safely nonblocking must
never authorize READY. Deterministic policy classifies such candidates as
`INVALID_CANDIDATE / INSUFFICIENT_EVIDENCE`; final resolution emits no public decision and does not
persist state. This is intentionally a simple UNKNOWN-to-failure rule, not a general semantic-proof
protocol. Three exact legacy proposals (`simple-paid-users`, `join-units-order`, and
`join-units-attempts-order`) that cannot establish an exact resolved or unresolved subject identity
remain typed invalid-evidence regressions. The last case explicitly proves that the Harness neither
declares an empty state READY nor invents `order_id`, `unit_sales`, or `payment_attempt_count`. A
separate structurally complete proposal proves those requested facts are preserved when READY is
legitimate.

The final provider-free suite remains 40 cases / 41 turns with fingerprint
`f90759d7b0ce41e99425a2d1fb7c053803f4482910f6208dbd5d40f72187c194`: unnecessary clarification
`0`, necessary clarification recall `1.000`, true-ambiguity false READY `0`, three expected
insufficient-evidence cases, insufficient-evidence false READY `0`, and action/state/reason/scope/
fact accuracy each `1.000`. The narrow policy/eval set passes 8 tests and the complete M8
contracts/dialogue/persistence/conversation set passes 60. Clean isolated `task bootstrap`
reproduces ten tables, ten orders, paid amount `1545.00`, successful refunds `110.00`, and retrieval
index `f9da78a01e6d030185c4510ba394b860e0d79bd39c06ea625b95599aed76b9e4`; `task quality` passes
457 tests with 7 explicit host-only skips. Implementation head
`b2f0d87e3c260d0d1e092d333f67c21304a48a1b` passes remote `Delivery / Quality` in workflow run
`33245092669`.

The earlier question-to-surviving-blocker protocol and dedicated `DialogueProposalV021` validator
were removed after review reclassified them as dialogue-quality optimization beyond the MVP
control-plane boundary. ASK still requires at least one Harness-proven blocker; exact question
targeting and wording remain deferred unless later end-to-end convergence evidence justifies
reopening them. Public M8 contracts and M9–M15 remain unchanged. No 30B replay or full M15 suite is
authorized for this remediation. PR #17 accepted final head
`8b016ab8d5fa7a7c50dde3e2a36ba324bf3de59d` received substantive approval; final remote
`Delivery / Quality` passed in workflow run `33245167017`; and it was squash-merged to protected
`main` as `a937546cb2d0c032ffa8dd76a8a4fbeec0227c95`. M8 targeted remediation is
complete/frozen. Draft PR #15 may resume final M15 acceptance without reopening an upstream
milestone.

M8 time-range-admission activation (2026-08-29): the minimal M15 live wire smoke then exposed one
new control-plane trust defect: a provider SET of `TimeRange(kind=RELATIVE, value=recent)` was
treated as resolved solely because a valid public object existed, allowing false READY. Reopen M8
only to add internal `time-range-admission-policy-v0.1` before provisional merge. Existing
canonical relative values and exact bounded date intervals remain admitted; vague free-form
relative values fail typed with no public decision or durable mutation. This is not a natural-
language temporal parser and introduces no default semantics. Draft PR #15, the provider prompt,
public M8 contracts, clarification targeting, M9–M15 behavior, Golden/Oracle truth, model/runtime,
timeout/token bounds, and acceptance thresholds remain unchanged. No 30B or 59-case M15 run is
authorized in this remediation.

M8 time-range-admission local evidence (2026-08-29): provider proposal resolution now rejects an
inadmissible time SET before provisional merge with stable code
`TIME_RANGE_NOT_OPERATIONALLY_CONCRETE`. The permanent regressions prove `RELATIVE/recent` emits no
decision and leaves a loaded Session/revision uncommitted, while `RELATIVE/last_30_days` and the
existing `ABSOLUTE/2026-08-01 to 2026-08-31` form still reach READY. Focused policy/service coverage
passes 11 tests; the unchanged provider-free readiness suite passes 40 cases / 41 turns with zero
unnecessary clarification, true-ambiguity recall `1.000`, false READY `0`, and insufficient-
evidence false READY `0`; complete M8 contracts/dialogue/persistence/conversation coverage passes
64 tests. Isolated `task bootstrap` reproduces ten tables, ten orders, paid amount `1545.00`,
successful refunds `110.00`, and retrieval index
`f9da78a01e6d030185c4510ba394b860e0d79bd39c06ea625b95599aed76b9e4`; `task quality` passes
461 tests with 7 explicit host-only skips. No 30B inference or 59-case M15 eval ran, and Draft PR
#15 remained unchanged at `0438bc35f599984d34d5c801289e9fe551d9f092`.

M8 time-range-admission closure evidence (2026-08-29): focused PR #18 implementation commit
`2be082a81e29aa8809bf5026ebe02dce03ac7c46` and accepted final head
`08159f1f6bbaf270d81827fac96f78fab81887f2` received substantive approval. Final remote
`Delivery / Quality` passed in workflow run `33247019114`; PR #18 was squash-merged to protected
`main` as `9837520c2b68e5b4f5c26de4eb2eed9b66ff76e5`. The M8 TimeRange-admission remediation is
complete/frozen and M15 final acceptance is authorized without another upstream change.

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
skipped. Remediation head `e2eb860` passes remote `Delivery / Quality` in run `32894798892`.
M9 remains active pending substantive re-review; M10 remains unauthorized.

M9 closure evidence (2026-08-26): implementation and acceptance PR #9; semantic-authority
remediation commit `e2eb860`; accepted final head `e14e728`; substantive re-review approved; final
remote `Delivery / Quality` passed in run `32894953002`; squash-merged to `main` as
`bf29dcffe3ff33c211bb4fd2a8cb4307e8d76fc8`. The domain-neutral 21-case real-model eval passed
all frozen gates, focused M9/CLI tests passed 17 tests, the bound-Ollama smoke passed, and complete
`task quality` passed 219 tests with 6 host-only tests skipped. M9 is complete/frozen and M10 is
authorized/active; M11 remains unauthorized.

M10 implementation note (2026-08-26): SQLGlot `30.17.0` now enforces the frozen size → MySQL
parse → single statement → read-only root → prohibited AST → scope resolution → namespace → plan
table subset → dangerous function/lock/hint order. Scope traversal admits physical tables only,
keeps CTE/derived scopes non-physical, uses exact analytics namespace/table identifiers, and
records unused `QueryPlan.tables` without changing subset into equality. MySQL executable comments,
session variables, table-valued JSON sources, recursive CTEs, exports, intentional delays, locks,
and optimizer/index hints fail closed. Only an issued `GuardedSQL` may enter the read-only
Harness-owned `EXPLAIN FORMAT=JSON`; the `explain-policy-v0.1` bounds of 1,000,000 JSON characters,
10,000 traversed nodes, and the configurable per-access row estimate must pass before the exact
SQL/digest can become `GuardedQuery`. Eval identity binds both `sql-guard-v0.2` and
`explain-policy-v0.1` plus every active bound.

The standalone M10 eval binds accepted M9 head `e14e728`, merge
`bf29dcffe3ff33c211bb4fd2a8cb4307e8d76fc8`, and frozen proposal snapshot fingerprint
`cc80748eef14bf8fcd70681fa2d88d74ef7a844865b37b1d13736832db193db9`. Its 40-case
adversarial guard and valid-EXPLAIN decisions both score `1.000`. Across the 21 real M9 proposals,
SQL parse, guard admission, and physical-table compliance each score `1.000`; EXPLAIN admission is
`0.905`, with `net-revenue` and `item-units-and-payment-attempts` correctly rejected by MySQL
EXPLAIN and retained as future M13 repair evidence rather than prompting an M9 change. No normal
query ran and no result-correctness claim is made. Focused M10/config tests pass 83 tests,
`task bootstrap` passes, and complete `task quality` passes 294 tests with 6 host-only tests
skipped. M10 remains active pending substantive review; M11 remains unauthorized.

M10 EXPLAIN-function-safety remediation note (2026-08-26): substantive review identified that
plain MySQL `EXPLAIN SELECT` may evaluate a stored function in a subquery when the outer query reads
a table, so a dangerous-function denylist alone did not prove EXPLAIN safety. Policy
`sql-guard-v0.2` now requires every SQLGlot `Func` node to match the narrow analytics surface used
by the frozen M9 corpus; every `Anonymous` or otherwise unapproved function fails closed. The
focused regression uses `unsafe_business_function(1)` under an authorized `fact_order` query and
proves `RecordingProvider.candidates` remains empty. Positive regressions cover `DATE`, `DATE_SUB`,
`CURRENT_DATE`, `SUM`, `COUNT`, `COALESCE`, `CAST`, and CASE; all 21 accepted M9 proposals retain
guard admission `1.000`. No QueryPlan, M9 prompt, EXPLAIN policy, or M11 behavior changed.

M10 closure evidence (2026-08-26): implementation and acceptance PR #10; accepted head
`e44e283494da00e9245995df10c7c461a29dd9a7`; substantive re-review approved; final remote
`Delivery / Quality` passed; squash-merged to `main` as
`92e2ae91e71067feec900ad18d0a0ff7055fcce5`. The pre-EXPLAIN function-authority remediation
retains adversarial and accepted-M9 guard admission `1.000`, with focused and complete local
quality evidence recorded above. M10 is complete/frozen and M11 is authorized/active; M12 remains
unauthorized.

M11 implementation note (2026-08-26): runtime policy `query-runtime-v0.1` accepts only the current
M10 `GuardedQuery`, revalidates its SQL digest plus complete capability/plan/guard/EXPLAIN identity,
and sends the admitted SQL unchanged. One dedicated `ANALYTICS_READONLY` connection per execution
enables and verifies session transaction read-only mode and MySQL `max_execution_time`; the
configured client read timeout must be strictly larger. PyMySQL `SSCursor` reads at most the row
bound plus one and applies the deterministic type-tagged `result-byte-budget-v0.1`. A truncated or
failed stream abandons the connection without closing the cursor, preventing PyMySQL cleanup from
draining the unread result. Cursor columns and positional rows preserve duplicate names and exact
`Decimal` values; unsupported values and provider failures surface as typed errors with no retry.
Metadata-only execution evidence carries capability, database, bound, timing, count, truncation,
and outcome facts without raw rows.

The frozen six-case no-LLM runtime suite fingerprint is
`fdd59397c027a33203f9f703eb3f9e409a3861255010132e166a1315697fa33c` under MySQL
`8.4.11` and PyMySQL `1.2.0`. Execution success, server timeout, row bound, byte bound, actual
shape, numeric fidelity, capability-only admission, read-only enforcement, and no-hidden-retry
each score `1.000`. Focused M11/M10/config/CLI coverage passes 43 tests; `task bootstrap` passes
with unchanged retrieval index fingerprint
`e0730e5adcc689a62de6042c7cc818626aa8fe5a86d0cf04f2a4a221236c0336`; complete
`task quality` passes 314 tests with 6 explicit host-only Ollama tests skipped. PR #11 implementation
head `e6cb1ba` passes remote `Delivery / Quality` in run `32924666433`. M11 remains active pending
substantive review; M12 remains unauthorized.

M11 execution-namespace remediation note (2026-08-26): substantive review identified that exact
SQL identity alone did not bind the default database used to resolve unqualified tables. M10 now
copies `SQLGuard.analytics_schema` into `GuardedSQL.execution_namespace`, propagates it unchanged
to `GuardedQuery`, and covers it with both stage capability fingerprints. M11 verifies the complete
capability and then requires `query.execution_namespace == connection_factory.database_schema`
before generating execution state or calling `connect()`. Focused regressions prove a capability
issued for `analytics_a` cannot reach a runtime configured for `analytics_b`, namespace tampering
invalidates the fingerprint, both failures keep `connect_count == 0`, and the matching namespace
path retains normal execution. M11 remains active pending substantive re-review; M12 remains
unauthorized. The remediation bumps the runtime policy to
`query-runtime-v0.2`; focused M11/M10/config/CLI coverage passes 45 tests, `task bootstrap` passes
with the unchanged retrieval index fingerprint, complete `task quality` passes 316 tests with 6
explicit host-only Ollama tests skipped, and the six-case runtime eval retains every metric at
`1.000`. PR #11 remediation head `875eac9` passes remote `Delivery / Quality` in run
`32925478092`. M11 remains active pending substantive re-review; M12 remains unauthorized.

M11 closure evidence (2026-08-26): implementation and acceptance PR #11; execution-namespace
remediation commit `875eac9`; accepted final head `c6dea2c`; substantive re-review approved; final
remote `Delivery / Quality` passed in run `32925593899`; squash-merged to `main` as
`c83763b223edc5958677545d8d9499e0664ae31b`. Focused M11/M10/config/CLI coverage passed 45
tests, complete `task quality` passed 316 tests with 6 explicit host-only Ollama tests skipped,
and every frozen six-case runtime-eval metric remained `1.000`. M11 is complete/frozen and M12 is
authorized/active; M13 remains unauthorized.

M12 activation note (2026-08-26): deterministic verification consumes one coherent evidence
context spanning M9 `PlanningTrace`, M10 `GuardedQuery`, M11 `ExecutionMetadata`, and the exact
bounded `ExecutionResult`. Verification never queries MySQL, calls a model, mutates upstream
state, generates evidence, or repairs SQL. Evidence-chain mismatch raises a typed integrity error
before checks. Public `VerificationResult v0.1` remains unchanged; an internal trace records
applied checks and explicit not-applicable/unsupported coverage gaps, so not checked is never
represented as passed. M11 metadata will evolve narrowly to v0.2 by binding a versioned canonical
fingerprint of ordered columns, typed positional rows, bounded row count, and truncation state.
Structural, semantic, then empirical checks are deterministic and coverage-bounded. A PASS means
only that every applicable encoded invariant passed; M13 remains unauthorized.

M12 implementation note (2026-08-26): internal `VerificationContext` is the only verifier input
and revalidates the M9 plan/bounded-table/retrieval identities, M10 capability/SQL/policy/physical
table identities, M11 namespace/metadata/success identities, and exact bounded-result fingerprint
before checks. `execution-metadata-v0.2` binds ordered columns, typed positional rows, returned row
count, truncation, and public result version through `execution-result-fingerprint-v0.1`, excluding
duration, IDs, and timestamps. Policy `verification-policy-v0.1` runs exact structural shape and
completeness checks, required-output/grain checks, output-alias-specific unique governed-column
lineage, conservative direct relationship JOIN validation, nonnegative integral COUNT checks,
finite-number checks, and grouping-key uniqueness. CTE/subquery lineage and unstructured
time/formula semantics remain explicit unsupported gaps; not-applicable checks also remain outside
public `CheckResult`.

The frozen 13-case no-LLM/no-database verification suite fingerprint is
`54e11f0f67cb1811442ca6dcbb8743d9bcfc6b32c3c0dacf67e350f042b732ab` against catalog
fingerprint `b492ee596e681484d9fabdb8981e773bba78079e15effd7ea1f67e23d10c5b1f`. Structural,
semantic, empirical, identity-mismatch, and truncation decisions each score `1.000`; false accept
and false reject are `0.000`; applied-versus-unsupported coverage is honestly reported as `0.904`.
Focused M12/M11 integration coverage passes 51 tests, `task bootstrap` preserves the deterministic
ten-table world and retrieval index fingerprint
`e0730e5adcc689a62de6042c7cc818626aa8fe5a86d0cf04f2a4a221236c0336`, and complete
`task quality` passes 346 tests with 6 explicit host-only Ollama tests skipped. PR #12
implementation head `592cd70` passes remote `Delivery / Quality` in run `32928350734`. M12
remains active pending substantive review; M13 remains unauthorized.

M12 PlannerContext-identity remediation note (2026-08-26): substantive review identified that M12
used bounded M6 CatalogDocument/Relationship values from `PlanningTrace.context` as semantic
authority even though only the associated QueryPlan was bound into the downstream capability.
`planner-context-fingerprint-v0.1` now hashes canonical JSON for the complete bounded
`PlannerContext`: version, RequirementState, ordered allowed tables, full document and relationship
semantics, and catalog/generated-schema/semantic-revision/retrieval identities. M9 records that
identity at plan acceptance; M10 requires and covers it in both guarded capability fingerprints;
M11 propagates it into execution metadata; M12 recomputes it and requires exact agreement across
the trace, capability, and metadata before checks. Focused regressions preserve QueryPlan,
GuardedQuery, ExecutionMetadata, and ExecutionResult while swapping only a governed relationship
or catalog semantic alias; both fail as `VerificationIntegrityError` before semantic verification.
No public contract, M13 behavior, model call, database call, or repair path changed. M14 is now
explicitly required to consume `VerificationTrace` or equivalent coverage evidence so a
coverage-bounded PASS cannot be presented as exhaustive verification.

The remediation supersedes the initial 13-case suite with a frozen 15-case suite fingerprint
`3be8b6e22367efb6eca7c827a8ad38443e3f1e0a0e26150f720eeaf8c7291f74`. Structural,
semantic, empirical, general identity, PlannerContext-substitution, and truncation decisions each
score `1.000`; false accept and false reject remain `0.000`; coverage remains `0.904`. Focused
M9→M12 identity-chain coverage passes 63 tests. `task bootstrap` preserves the deterministic
ten-table world and retrieval index fingerprint
`e0730e5adcc689a62de6042c7cc818626aa8fe5a86d0cf04f2a4a221236c0336`; complete
`task quality` passes 350 tests with 6 explicit host-only Ollama tests skipped. M12 remains active
pending substantive re-review; M13 remains unauthorized. Remediation implementation commit
`c8e31631fd9a0bf210bae6665e8415c2c388e5ae` passes remote `Delivery / Quality` in run
`32932751098`.

M12 closure note (2026-08-26): PR #12 was approved and squash-merged to `main` at
`962dcf1798057bd5f026765c722234b8e729a426`. The accepted remediation head was `f2a51b8`; the
accepted M9→M12 identity-chain suite passed 63 focused tests, the frozen 15-case verification eval
fingerprint remained `3be8b6e22367efb6eca7c827a8ad38443e3f1e0a0e26150f720eeaf8c7291f74`,
`task quality` passed 350 tests with 6 explicit host-only Ollama tests skipped, and remote
`Delivery / Quality` passed. M12 is complete/frozen; M13 is active. M14 remains unauthorized.

M13 activation note (2026-08-26): use `repair-policy-v0.1`, `query-repair-v0.1`,
`repair-failure-fingerprint-v0.2`, and `repair-trace-v0.2`. Repair returns a replacement public
`QueryPlan v0.1`. Eligibility is an exact typed allowlist. The only initial provider codes are
MySQL `1052` (ambiguous column) and `1054` (unknown column), whether
raised by Harness-owned EXPLAIN or runtime execution. Selected M12 repairable check names are
limited to output shape/alias, unique governed output source, direct governed relationship JOIN,
and grouping-key formulation. Coverage gaps never trigger repair. The original PlannerContext is
reused by value and fingerprint, retrieval is not rerun, and replacement plans pass the existing
M9 PlannerPolicy and the complete M10→M12 evidence chain. The existing
`max_sql_repair_attempts` setting remains the configured bound and defaults to one. An atomic
control-plane claim increments durable `Run.repair_count` before inference; a claimed model
failure consumes the attempt. `VALIDATING → REPAIR_EXHAUSTED` is added as the smallest lifecycle
amendment needed for a failed/exhausted M10-stage repair without inventing a `REPAIRING` status.

M13 provider-grammar evidence note (2026-08-26): the first bound real-Ollama smoke repaired the
unknown-column case through M12 but produced an empty `expected_columns` list for both syntax and
verification-alias cases. Their replacement SQL executed, then M12 correctly failed
`expected_columns_present`, output-shape, required-metric, and grain-period checks. Because public
`QueryPlan v0.1` intentionally defaults that list to empty, prompt text alone could not make the
provider schema require the M12-essential output shape. Introduce a narrow internal
`RepairPlanProposal` whose only material restriction is `expected_columns min_length=1`, then
normalize it immediately into public `QueryPlan v0.1` and apply the unchanged M9 policy/M10–M12
chain. This measured adapter workaround does not revise the frozen public contract or make the DTO
semantic authority.

M13 implementation evidence (2026-08-26): `repair-policy-v0.1` classifies a frozen 19-case suite
with eligibility accuracy `1.000`, policy/integrity zero-model-call accuracy `1.000`, durable-bound
enforcement `1.000`, and concurrent-claim bound enforcement `1.000`; suite fingerprint
`c087d5e8d3c9dc9c33244b61ebe4fd0334460a062eea05b62db03ae5fbf1474f`. The real
control database proves one of two concurrent claims succeeds and durable `repair_count` remains
one; a separate cross-service regression proves an exhausted competing caller cannot terminalize
the in-flight owner's Run. The focused M13/M9–M12/persistence suite passes 157 tests. `task
bootstrap` preserves the ten-table controlled world and retrieval index fingerprint
`e0730e5adcc689a62de6042c7cc818626aa8fe5a86d0cf04f2a4a221236c0336`; complete
`task quality` passes 392 tests with 6 explicit host-only Ollama tests skipped.

The final three-case real-Ollama report binds chat model fingerprint
`3abd0ade8368742786e7464c1ff3b7ffbdb048bbfb303820725ac724f01bdfe6`, Ollama
`0.32.15`, the unchanged retrieval index/catalog/generated-schema/semantic identities, prompt
`query-repair-v0.1`, per-case failure and replacement-plan fingerprints, one model call, and
durable `repair_count=1`. Syntax, MySQL unknown-column `1054`, and M12 verification-alias cases all
produce new evidence branches ending in M12 PASS: eligible first-attempt success `1.000`,
post-repair M12 pass `1.000`, and bound enforcement `1.000`. This is controlled-world evidence
only, not a general self-healing claim. M13 remains active pending PR and substantive review; M14
remains unauthorized.

M13 substantive-review remediation evidence (2026-08-26): review of head `f66b483` identified one
P1 in the durable repair authority chain: failure evidence did not bind the Run whose budget it
consumed, and the atomic claim accepted any repairable lifecycle state regardless of typed failure
stage. Internal `RepairFailure v0.2` now requires `source_run_id`; its
`repair-failure-fingerprint-v0.2` and `RepairTrace v0.2` bind that identity. The retained explicit
service `run_id` must equal the evidence source before any repository/model access. The opaque Run
ID is deliberately excluded from model context. `SQL_GUARD`/`EXPLAIN`, `RUNTIME`, and
`VERIFICATION` map deterministically to `VALIDATING`, `EXECUTING`, and `VERIFYING`; MySQL validates
that exact status under the same `SELECT ... FOR UPDATE` lock that increments `repair_count`.

The remediation regressions prove cross-Run replay leaves the target Run at `repair_count=0` with
zero claims/model calls; all four typed stages reject a mismatched lifecycle state with the same
zero-call behavior; the real control database rolls back a stage mismatch without changing
`VERIFYING` or `repair_count=0`; and the existing same-Run cross-service concurrency bound remains
covered. The final focused repair/control-DB/M10/M11 suite passes 53 tests. `task bootstrap`
preserves ten tables, ten orders, paid amount `1545.00`, successful refunds `110.00`, and retrieval
index fingerprint `e0730e5adcc689a62de6042c7cc818626aa8fe5a86d0cf04f2a4a221236c0336`.
`task quality` passes 399 tests with 6 explicit host-only Ollama tests skipped. The unchanged
19-case deterministic suite fingerprint
`c087d5e8d3c9dc9c33244b61ebe4fd0334460a062eea05b62db03ae5fbf1474f` remains PASS at `1.000`
for eligibility, policy/integrity zero-model-call, configured bound, and concurrent bound. The
three-case real-Ollama syntax/`1054`/verification-alias smoke remains PASS at first-attempt
`1.000`, post-M12 `1.000`, and bound `1.000`, with the unchanged model/runtime/catalog/index
identities already recorded above. M13 remains active pending substantive re-review; M14 remains
unauthorized.

PR #13 implementation commit `2ee9234b7f1e63fbce8c82a339578b0c59e56302` passes remote
`Delivery / Quality` in run `32936610821`. The PR remains open with required reviewer `cboya` and
is ready for substantive M13 review; it must not be merged and M14 must not start without explicit
authorization.

PR #13 P1 remediation commit `ac2648ed90df46fe221cf8b11419f63cb649b1af` passes remote
`Delivery / Quality` in run `32938518767` (57 seconds). The PR remains open for substantive
re-review; M13 is not complete, the PR must not be merged, and M14 must not start without explicit
authorization.

M13 closure evidence (2026-08-26): acceptance PR #13; accepted final head
`0653c9f86a837804fa1530e5349a2b0fe52b3f80`; squash-merged to `main` as
`e4a3c4249c21334c2986d597f2321f31476eba7d`; substantive re-review approved; final remote
`Delivery / Quality` passed in run `32938661354` (52 seconds). Focused remediation coverage passed
53 tests, complete `task quality` passed 399 tests with 6 explicit host-only Ollama tests skipped,
the frozen 19-case deterministic repair eval and three-case real repair smoke remained fully green.
M13 is complete/frozen; M14 is authorized/active. M15 remains unauthorized.

M14 activation note (2026-08-26): the model may explain evidence but cannot define the result
envelope, data, assumptions, evidence, verification/policy status, coverage, or Run state. Build an
internal integrity-checked `AnswerSynthesisContext` from exactly the final M9–M12 branch and
optional successful M13 trace. Use a narrow structured `AnswerProposal` with positional cell
references, an independent deterministic grounding policy, and separate synthesis row/byte bounds.
Surface unsupported verification coverage and assumption provenance mechanically. Use the smallest
control-plane unit of work for dialogue/Run outcome and final assistant-message/Run completion
consistency. Full M15 trace persistence and 50+ Golden Dataset expansion remain out of scope.

M14 implementation note (2026-08-26): `answer-synthesis-v0.2` uses an internal strict
`AnswerProposal v0.1` with positional cell references and `answer-grounding-v0.2`. Coverage is
reported as applied divided by applied plus unsupported checks; not-applicable gaps do not become
passes or denominator entries, and public scope remains `COVERAGE_BOUNDED`. Exact Decimal values
serialize as strings. Context larger than `MAX_ANSWER_CONTEXT_ROWS` or
`MAX_ANSWER_CONTEXT_BYTES` returns a deterministic `RESULT_TOO_LARGE` fallback with zero model
calls and no new result facts. The minimal conversation UoW extends the existing M8 store so
dialogue/Run outcomes and final-message/Run completion cannot partially commit. The orchestrator
only sequences existing M8–M14 authorities. Deterministic M14 eval currently passes all seven
frozen cases and every grounding/Decimal/coverage metric at `1.000`; host and initial remote
acceptance evidence are recorded below.

M14 local acceptance evidence (2026-08-26): `task bootstrap` rebuilt the ten-table controlled
world and retrieval index `e0730e5adcc689a62de6042c7cc818626aa8fe5a86d0cf04f2a4a221236c0336`;
the focused answer/conversation/API/MySQL-UoW suite passes 40 tests; final `task quality` passes
433 tests with 7 explicit host-only skips. `task m14-eval` originally passed six frozen cases and
the final v0.2 suite passes seven, adding request/result numeric-authority separation while every
grounding, arithmetic, reference, Decimal, and coverage metric remains `1.000`. Initial real-model
evidence showed Ollama omitted a
default-valued reference list, so `AnswerProposal v0.1` now makes `evidence_refs` provider-required
(empty only for an empty result); the final three-case real-Ollama smoke reports structured
grounding, non-empty usefulness, reference validity, injection resistance, and one-call bound each
`1.000`. The real FastAPI→Ollama→MySQL M8–M14 result path passes in 35.98 seconds. Full `task eval`
also remains green: M7 seed/final recall `0.990/1.000`, M8 action/state `1.000`, M9 parse/allowed
`1.000`, M10 guard/table-scope `1.000`, and every M11–M14 deterministic gate passes. M14 is ready
for focused PR and substantive review; it is not complete or authorized for merge, and M15 remains
unauthorized.

M14 PR evidence (2026-08-26): focused PR #14 was opened from implementation head
`7a7f886930d7083b7f598d523545712711d10156`; remote `Delivery / Quality` passed in run
`32946182680` (55 seconds). Required reviewer `cboya` remains requested. M14 is ready for
substantive review; it remains active rather than complete, PR #14 must not be merged without
approval, and M15 remains unauthorized.

M14 P1 remediation note (2026-08-26): substantive review found that
`answer-synthesis-v0.1` instructed scope-only use but `answer-grounding-v0.1` still merged numbers
extracted from RequirementState with numbers from cited result cells, so the `30` in
`last_30_days` could incorrectly authorize “paid amount is 30” while the cited result was
`100.00`. `answer-grounding-v0.2` removes all request/context numeric
authority: every numeric token in model answer text must occur in a cited `ExecutionResult` cell,
including empty-result answers. Scope remains deterministic RequirementState/API data rather than
free-text evidence. The focused 18-test answer suite passes, and the expanded seven-case eval
rejects this crossover while retaining exact cited Decimal acceptance; grounding decision,
ungrounded-number rejection, request/result numeric authority separation, arithmetic rejection,
reference rejection, Decimal fidelity, and coverage visibility are each `1.000`. Complete
`task quality` passes 435 tests with 7 explicit host-only skips. The three-case real-Ollama answer
smoke remains fully green, and the real FastAPI→Ollama→MySQL path passes in 37.59 seconds. Remote
`Delivery / Quality` passes on remediation head
`56685dc2bdefb67b0a40aef478610d5a1d00fe80` in run `32947600298` (50 seconds). M14 is ready for
substantive re-review; it stays active, PR #14 must not merge, and M15 remains unauthorized.

M14 closure evidence (2026-08-26): acceptance PR #14; numeric-authority remediation commit
`56685dc2bdefb67b0a40aef478610d5a1d00fe80`; accepted final head
`7d950538c7898379f2bf8bc97b5f6f5e35de1988`; substantive re-review approved; final remote
`Delivery / Quality` passed in run `32947750444` (52 seconds); squash-merged to protected `main`
as `8cf14aa2766603ffb581abf8fb08874dbdd3e478`. The final seven-case deterministic answer eval,
three-case real-Ollama smoke, and FastAPI→Ollama→MySQL path remained green. M14 is
complete/frozen; M15 is authorized/active. MVP release remains unauthorized.

M15 activation note (2026-08-26): Trace records only observable structured evidence, never hidden
reasoning, credentials, or default raw result rows, and cannot become authority for any M8–M14
decision. Use a dedicated append-only `agent_trace_event` store with deterministic per-Run
sequence and explicit attempt branches. Golden expectations and oracle SQL belong exclusively to
the evaluation harness outside runtime packages. Final behavioral evidence is meaningful only
under a canonical environment identity binding repository, Golden, schema/catalog/index,
model/runtime, prompt/policy, dependency, and Python fingerprints. M15 adds no Agent intelligence.

M15 implementation note (2026-08-26): migration `005_agent_trace_event.sql` introduces a
dedicated append-only trace ledger with contiguous per-Run sequencing, attempt/stage/event
identity, canonical bounded payload fingerprints, and runtime SELECT/INSERT-only privileges.
The conversation orchestrator projects observable M8–M14 outcomes without raw rows, duplicated
answers, credentials, or hidden reasoning. Terminal Run state and required terminal trace evidence
commit through one control-plane unit of work. `eval_harness` drives the public Session/Message API,
reloads persisted Run/trace state, executes isolated static SELECT Oracles through the analytics
reader, preserves all standalone stage gates, and emits one environment-bound final report.

M15 model-bound calibration note (2026-08-26): the first 54-case challenge run under the bound
8B Q4 `gemma4:latest` environment achieved E2E `0.352`, result-Oracle `0.365`, and trace integrity
`1.000`. Observed failures included spurious grouping, omitted filters, and wrong governed
dimensions; this remains diagnostic evidence rather than a case-selection input. The frozen
model-neutral suite now contains 59 cases: 55 result cases over 54 distinct Oracles, with 15
simple, 22 aggregation/time, 11 relationship/trap, four multi-turn clarification/correction,
three repair/empty, and four policy-failure cases. Two Oracles prove empty populations and one
formulation permits the single M13 repair when the model needs it; the standalone repair eval
retains deterministic attempt-1 coverage. Final behavioral acceptance may use a stronger local Ollama model,
but it must rerun the unchanged suite under a new complete environment fingerprint. Golden
fingerprint `53d969d1196877829cc89ee3070d75a1fea6ba88bfd5986fbe66beb21fcf93f7`
binds the exact suite.

M15 large-model execution note (2026-08-27): final acceptance uses a configured local
Qwen3-30B-A3B-Instruct-2507 Q4 model rather than treating the 8B diagnostic as a release gate.
Initial observation exposed repeated 17–18 minute unbounded-generation tails even with structured
JSON and thinking disabled. The provider-neutral adapter now sends the frozen configurable
2,048-token `num_predict` ceiling for every structured call; EvaluationEnvironment binds this
ceiling and the request timeout. This is a resource-safety amendment only: prompts, Golden cases,
Oracles, stage policies, and M8–M14 semantics remain unchanged.

M15 effect-acceptance note (2026-08-27): head `3be2534` passed the focused resource-boundary,
typed-failure, configuration, and frozen-Golden checks (`33 passed`), followed from a clean reset
by `task bootstrap` and `task quality` (`454 passed, 7 skipped`). The complete public-API run under
Qwen3-30B-A3B-Instruct-2507 recorded environment fingerprint
`f2fb51fb05df516c59489fffaccb0d3a3adf0daeb528ecfb568481f6e665b933`, Git
`3be25340a471a101ce414b6bec98909c18045ea0`, Ollama `0.32.15`, request timeout `60s`, output ceiling
`2048`, Golden fingerprint `53d969d1196877829cc89ee3070d75a1fea6ba88bfd5986fbe66beb21fcf93f7`,
and the bound schema, catalog, retrieval, chat, and embedding identities. Retrieval, planning,
SQL guard, runtime, verification, repair, and answer stage gates passed. Trace integrity was
`1.000`, with zero unauthorized execution, failed-verification synthesis, repair-bound, and
numeric-grounding violations. Model-bound dialogue and Golden behavior did not pass: Golden E2E
was `0.169`, Oracle pass rate `0.127`, and unnecessary clarification rate `0.610`. Per the
resource-sensitive acceptance direction, an additional dense 27B local calibration was stopped
to avoid host contention; no further local large-model run is required for this PR iteration.
These model-capability results remain diagnostic: no Prompt, Golden case, Oracle, or frozen
behavioral threshold changed, `task eval` remains failed, and PR #15 remains Draft pending final
behavioral acceptance in a suitable capable-model environment. The post-eval and post-quality
tracked worktree was clean.

M15 behavioral-failure attribution note (2026-08-27): `task m15-attribution` now derives a strict,
model-free report from the failed source report without changing runtime behavior. Attribution
fingerprint `62bbd0b0c3ca33f63de1599048699eeb3f8d1f9128be7a0c0ed9b10156167a79`
binds source environment `f2fb51fb05df516c59489fffaccb0d3a3adf0daeb528ecfb568481f6e665b933`
and produces an exact 59-case terminal partition: 10 pass, 35 unexpected clarification, one
planning failure, one SQL-admission failure, three repair-exhausted, two answer-synthesis failure,
six verified-result Oracle mismatch, and one public-evidence assertion. The stage funnel is 59
received, 20 dialogue-ready/retrieval-pass, 19 planning-pass, 16 admission/execution-pass, 15
verification-pass, 13 synthesis/Oracle-reached, seven Oracle-pass, and ten final Golden-pass;
five cases entered repair. Across 63 turns the dialogue matrix is READY→READY 20,
READY→CLARIFY 36, READY→DIALOGUE_FAILURE one, CLARIFY→CLARIFY two, and four expected safe
terminal failures. Six explicit `M12 PASSED + Oracle FAILED` cases split into four extra-grain and
two output-shape mismatches. Source report v0.1 did not retain clarification blocker fields,
same-input standalone replay, or typed causes beneath generic pipeline failures; the report marks
36 blocker occurrences `EVIDENCE_UNAVAILABLE`, all 35 comparisons `NOT_REPLAYED`, and four
structured-call failures `UNCLASSIFIED` rather than guessing. The ranked remediation ownership is
M8 first (35 cases), M9+M12 second (eight cases including the planning and verified semantic set),
M13+M10/M12 third (four cases), and M14 fourth (two cases). Machine-readable and human evidence
are frozen at `docs/evidence/M15-BEHAVIORAL-ATTRIBUTION-3be2534.json` and
`docs/evidence/M15-BEHAVIORAL-ATTRIBUTION-3be2534.md`. This diagnosis does not authorize reopening
any prior milestone, changing a frozen truth source, or moving PR #15 out of Draft.

M15 targeted behavioral-diagnosis note (2026-08-27): under the exact retained effect environment
(`be7d8c949d1d85dc17e248c17db10be4634effd614fd20860d749082fbe7fe3e` chat
fingerprint, `0112ea4d6590628288600ebd612ee8b094001c1e181c4eda9a64493d205c138f`
embedding fingerprint, Ollama `0.32.15`, dialogue prompt `v0.20`, timeout `60s`, and
`num_predict=2048`), `task m15-behavioral-diagnosis` replayed exactly the 35 attributed M8 cases
without running the full 59-case suite. All 35 also clarified standalone; all 36 structured turns
completed successfully, so the partition is M8/model behavior 35, integration/context owner zero,
structured/model failure zero, and spec/Oracle review zero. The 37 blocking-ambiguity occurrences
are time range 22, grain eight, metric six, and dimension one.

The retained report lacked the six original full evidence chains, so exactly those six
`M12 PASSED + Oracle FAILED` cases were replayed. All six reproduced their source public shape and
Oracle failure. `simple-gmv`, `simple-paid-amount`, `simple-payment-attempts`, and
`join-net-revenue` first diverge at `QueryPlan` by adding output grain while canonical
`RequirementState` has no grain/dimension; M12 then passes the plan-consistent extra shape, so
ownership is M9+M12. `agg-gmv-channel` and `agg-orders-channel` first diverge when explicit
`order_channel` output shape becomes canonical dimension `channel`; per the frozen owner taxonomy
they require human M8/output-shape contract review rather than an automatic Golden/Oracle change.
The forensic path makes no M14 model call. Report fingerprint
`1070e9346cdb441eb083299363d818e39cdde598815906e38437d1300b4ebc78` and full machine/human
evidence are frozen at `docs/evidence/M15-BEHAVIORAL-DIAGNOSIS-3be2534.json` and
`docs/evidence/M15-BEHAVIORAL-DIAGNOSIS-3be2534.md`. This diagnostic recommends regression scope
but does not authorize reopening M8/M9/M12, changing truth, or moving PR #15 out of Draft. The
focused diagnosis/attribution suite passes 13 tests; complete host `task quality` passes 467 tests
with seven explicit host-only skips after the sandbox-only MySQL denial was rerun with the required
host socket access. The 30B model was unloaded after the bounded replay.

M15 final-acceptance resume note (2026-08-29): protected `main` baseline
`9837520c2b68e5b4f5c26de4eb2eed9b66ff76e5` contains the completed/frozen M12, deterministic M8
readiness, and M8 TimeRange-admission remediations from PR #16, PR #17, and PR #18. The earlier
main baseline through PR #17 entered the existing Draft PR #15 lineage at merge commit
`d74b323f67844a480b0ad7cff0b6c8556ebaa16a`; final protected main entered the same unre-written
lineage at merge commit `b61921694cab39394411c76aa9919fa22ba93dfa`. Prior attribution and diagnosis
commits and all checked-in evidence artifacts remain intact. Integration conflicts were append-
only documentation collisions: M15 decisions retain D-030/D-031 and the later M12/M8 decisions
are mechanically numbered D-032/D-033/D-034. Golden truth, Oracle truth, thresholds, bound model,
timeout, output-token ceiling, prompts, and M8–M14 behavioral contracts remain frozen. Final
acceptance now proceeds through deterministic integration sanity, the exact six-case bound-model
control-plane smoke, and then the canonical clean `reset → bootstrap → quality → eval` sequence
without reopening an upstream milestone.

M15 canonical environmental-rerun result (2026-08-29): one authorized clean rerun at exact Draft
PR #15 head `431fb1fdbb5e8b6e94e0d1b59a7a4bc8bdd478ec` completed all 59 cases; the previous
MySQL/trace interruption did not recur. `task reset`, `task bootstrap`, and `task quality` passed
(`493 passed / 7 skipped`), while the complete `task eval` failed the unchanged behavioral gates:
E2E `10/59` (`0.1695`) and result Oracle `6/55` (`0.1091`). Trace integrity remained `1.000`,
unnecessary clarification `0.000`, and unauthorized execution, failed-verification synthesis,
numeric-grounding violations, repair-bound violations, and verified/Oracle mismatches all remained
zero. Dialogue was the only failing standalone stage; all other standalone stages passed. The
canonical report binds EvaluationEnvironment
`c711d8bc5d7d25d0dddde7536e4ee8f17a6f4f8678a6e616893d85f7942fc607` and is frozen in
`docs/evidence/M15-FINAL-CANONICAL-ACCEPTANCE-431fb1f.json` plus its human-readable companion.
This valid behavioral FAIL leaves M15 incomplete, PR #15 Draft, and the MVP unaccepted. It does not
authorize remediation, another canonical run, Ready-for-Review, merge, release, or tag.

M15 terminal closure rule: this milestone becomes COMPLETE only when final substantive review is
APPROVED, remote `Delivery / Quality` is PASS, clean-state final acceptance is PASS, and the
focused protected-main PR is squash-merged. The immutable merge SHA plus the project release/tag
are terminal closure evidence; no post-merge closure-only PR is required.

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

2026-08-26 — OQ-009 / M10 raw-SQL capability and MVP EXPLAIN admission
Decision: Treat raw SQL as data and expose only an internal immutable `GuardedQuery` as future
execution capability. SQLGlot 30.x performs MySQL parsing and scope-aware physical-table
resolution. The Harness alone constructs `EXPLAIN FORMAT=JSON` after all guard checks; model SQL
cannot request EXPLAIN and `EXPLAIN ANALYZE` is never constructed. Initial bounds are 64,000 SQL
characters and 100,000 estimated rows per table access. Plain MySQL EXPLAIN is not assumed to be
universally side-effect free: policy `sql-guard-v0.2` admits only a narrow recognized analytics
function surface and rejects unknown/stored/loadable-function shapes before provider access.
Evidence: SQLGlot scope sources distinguish physical `Table` values from CTE/derived `Scope`
values. MySQL EXPLAIN JSON exposes per-access `rows_examined_per_scan`; the deterministic ten-table
world is far below the initial obviously-unreasonable threshold.
Consequences: M11 can consume the exact validated SQL payload and digest rather than accept a new
string. The row threshold is a configurable synthetic-world admission rule, not a general cost
model; changes require recorded calibration evidence.

2026-08-26 — M11 capability-only streaming runtime
Decision: Execute only the current fully fingerprinted M10 `GuardedQuery` through a synchronous
PyMySQL service. Bind M10's analytics execution namespace into the capability and reject a runtime
database mismatch before connection. Use one non-pooled analytics-reader connection, verified
session read-only mode, MySQL `max_execution_time`, and a larger bounded client read timeout.
Stream with `SSCursor`, use row-bound-plus-one detection plus an 8 MiB default type-tagged
normalized-byte budget, and close the connection without closing the cursor whenever unread rows
remain. Emit metadata through a separate sink and never retry.
Evidence: MySQL documents session transaction access mode and millisecond read-only SELECT
timeouts; PyMySQL documents that `SSCursor` reads on demand and cursor close exhausts remaining
data. The real controlled-world suite proves server timeout code 3024, row/byte truncation,
duplicate cursor columns, exact `Decimal`, read-only/control-schema denial, and one attempt.
Consequences: The sync MVP path relies on server and socket bounds rather than an asyncio-only
cancellation illusion. Truncated results are successful but incomplete evidence; M12 must decide
whether they satisfy a requirement. Supporting connection pooling would require an explicit
discard protocol and is deferred.

2026-08-26 — M12 deterministic, coverage-bounded verification
Decision: Verify one integrity-checked M9→M10→M11 evidence context in structural, semantic, then
empirical order. Verification only judges existing evidence: it performs no database/model call,
does not mutate upstream objects, and does not repair. Bind the exact bounded M9 semantic world
through `planner-context-fingerprint-v0.1` carried by PlanningTrace, M10 capability, and M11
metadata. Bind the exact bounded `ExecutionResult` into `ExecutionMetadata v0.2` through a
versioned canonical typed fingerprint. Keep public `VerificationResult v0.1`; record applied
checks and not-applicable/unsupported gaps separately in an internal trace. PASS means every
applicable encoded invariant passed, not that every possible semantic error was disproven.
Evidence: M11 previously bound SQL, plan, policy, namespace, and result-size facts but could not
prove that separately transported rows belonged to that execution. Current catalog contracts can
prove unique governed column sources and direct single-column relationship joins, while time and
formula semantics remain partly natural-language and therefore must stay explicit coverage gaps.
Consequences: Evidence-chain mismatch is a typed integrity error rather than an ordinary failed
check. Runtime truncation fails structural verification. Ambiguous/unencoded semantics cannot be
silently marked passed or replaced by an LLM judge or a second business-semantics registry. M13
alone may consume verification failure for bounded repair. M14 must consume the internal trace or
equivalent coverage evidence and preserve this bounded claim in answer synthesis.

2026-08-27 — M12 targeted public-shape authority remediation
Decision: Advance the internal policy to `verification-policy-v0.2`. Derive the complete allowed
public output set and requested aggregate grain from READY RequirementState, independently of the
Plan's expected columns. Require exact public-shape equality and exact public aggregate grain, and
require every requested dimension output to have one uniquely governed M6 column source in the SQL
projection lineage. Inspect every final aggregate `GROUP BY` partition key; without governed
functional-dependency metadata, any key that cannot map to one requested public grouping
projection fails closed. Ignore only non-grouping SQL helpers that cannot partition result rows.
Evidence: Draft M15 diagnosis froze six `M12 PASSED + Oracle FAILED` cases: four Plans added
unrequested channel/day grain and two exposed generic `channel` dimensions without a uniquely
provable M6 column identity. In every case the wrong Plan and matching result had been allowed to
validate one another.
Consequences: These six cases become permanent provider-free M12 regressions and the standalone
report adds the exact `verified_oracle_mismatch_count == 0` release gate. This does not change the
Golden/Oracle assets, model behavior, M8/M9 prompts or contracts, M13 bound/prompt/repair categories,
or public VerificationResult schema. Repairable public-shape, projection-lineage, and grain check
names join M13's already-supported verification-formulation allowlist. Missing/ambiguous requested
dimension authority has a separate nonrepairable check and consumes zero repair attempts.

2026-08-27 — M12 substantive-review grain and repair-classification remediation
Decision: Replace projection-only grain inference with an exact mapping from every final aggregate
`GROUP BY` expression to one public non-aggregate projection. Accept structural expression
identity, an output alias only when bounded final-scope metadata proves that MySQL cannot resolve
the unqualified name as an input column, or a valid SELECT ordinal; reject any unmatched/ambiguous
hidden grouping key because current governed metadata cannot prove it functionally dependent on
the requested grain. Split output-set conformance, requested-output resolution, requested-dimension
source uniqueness, and requested-dimension projection lineage into stable check IDs. Only the
output-set, projection-lineage, and grain formulation checks are M13-repairable.
Evidence: Substantive review supplied a metric-only counterexample whose public shape was correct
but `GROUP BY user_id` produced multiple hidden-grain rows, plus a province result refined by a
hidden user key. It also showed that zero/multiple M6 candidates cannot be repaired under the same
frozen PlannerContext.
Consequences: Hidden grouping refinements become deterministic semantic failures. M6 authority
ambiguity makes zero repair-model calls and consumes zero durable attempts; no text-detail parsing,
new repair category, prompt change, or attempt expansion is introduced.

2026-08-27 — M12 MySQL GROUP BY alias-resolution hardening
Decision: Treat an unqualified final `GROUP BY` identifier as a SELECT alias only after proving
from the complete bounded simple final scope that no input column has the same normalized name.
If the scope is complex, incomplete, or contains a colliding source column, the alias route fails
closed; structural-expression and positional-ordinal mappings remain unchanged.
Evidence: MySQL resolves unqualified grouping names against `FROM` columns before SELECT aliases.
The permanent collision regression uses `DATE(o.paid_at) AS paid_at ... GROUP BY paid_at`, while
the noncolliding `period` alias and ordinal variants remain accepted.
Consequences: A source `paid_at` column cannot be mistaken for the transformed output alias and
silently refine aggregate grain. No planner, prompt, M6 authority, or M13 repair-policy change is
introduced.

2026-08-26 — M14 deterministic response authority and atomic conversation completion
Decision: Allow the answer model to propose only natural-language text and unique positional
ExecutionResult cell references under `answer-synthesis-v0.2`. Revalidate one final PASSED
M9→M12 branch, apply `answer-grounding-v0.2`, expose assumptions/query evidence/coverage/Run state
from deterministic sources, serialize Decimal as an exact string, and use independent 100-row /
128-KiB synthesis defaults. Report verification scope as `COVERAGE_BOUNDED`; compute coverage as
applied checks divided by applied plus unsupported checks and exclude not-applicable gaps. Extend
the existing dialogue store with a minimal UoW for atomic dialogue/Run and final-message/completion
transactions. Keep the orchestrator a sequencing layer over unchanged M8–M13 services.
Evidence: Positional references remain unambiguous when cursor column labels duplicate. The frozen
seven-case provider-free answer corpus rejects hallucinated numbers, request-to-result numeric
authority crossover, arithmetic-derived percentage, invalid references, and missing references
while retaining exact Decimal and unsupported coverage at the API. In-process HTTP smoke covers
one-turn, multi-turn, repaired, and policy-terminal paths.
Consequences: The model cannot rewrite database truth or epistemic status at the final boundary.
Oversized answer context receives a typed zero-call no-new-facts fallback, not a sampled summary.
Control-plane records cannot persist a final assistant answer without Run completion or a dialogue
outcome without its matching Run state. M15 trace persistence remains intentionally deferred.

2026-08-28 — M8 deterministic material-ambiguity readiness
Decision: Add internal `blocking-ambiguity-policy-v0.1`. Provisionally merge the unsuppressed model
patch, classify every candidate from structured state/operations/attribution/alternatives, suppress
only proven blockers, and derive the final action. Missing optional time/grain is nonblocking;
resolved metric/dimension facts cannot remain blocked. Keep public M8 contracts unchanged. Amend
only the provider wire prompt to `dialogue-understanding-v0.21` because accepted bound evidence
proved v0.20 did not emit the structured alternatives/unresolved item needed for positive recall.
Evidence: All 35 diagnosis-proven false clarifications reproduce with successful standalone M8
calls and empty competing options. The provider-free 39-case / 40-turn suite eliminates all 35
while retaining four true-blocker classes at recall `1.000`, false READY `0`, and exact canonical
state/scope preservation `1.000`.
Consequences: Model explanation prose and M15 expected answers are not readiness inputs. No default
time/grain is injected, no resolved sibling is erased, and M9–M15 behavior/thresholds remain frozen.

2026-08-29 — M8 insufficient-evidence fail-closed amendment
Decision: Keep the live boundary on `DialogueProposal v0.1` and let
`blocking-ambiguity-policy-v0.1` evaluate provider evidence after provisional merge. Evidence that
proves neither blocking nor nonblocking is typed invalid provider evidence and produces no public
decision. UNKNOWN must never authorize READY. Do not add a dedicated v0.21 proof validator or a
question-target protocol; ASK only requires at least one Harness-proven blocker.
Evidence: Exact patch review found `join-units-attempts-order` reached READY with empty metric and
dimension state because two optionless provider blockers were classified nonmaterial. Applying the
same fail-closed rule mechanically also identifies `simple-paid-users` and `join-units-order` as
legacy proposals without an exact resolved/unresolved subject match. The provider-free suite
freezes all three invalid outcomes and a complete READY counterpart that preserves every requested
fact.
Consequences: Insufficient structured evidence produces no public decision, no state persistence,
and no model retry. Question-to-surviving-blocker binding, perfect ambiguity semantics, and further
prompt optimization are deferred behavioral refinements. Public M8 contracts, M6 semantic
authority, and M9–M15 behavior remain unchanged.

2026-08-29 — M8 operational TimeRange SET admission
Decision: Add internal `time-range-admission-policy-v0.1` at the provider-proposal trust boundary.
Admit only existing canonical relative forms (`last_N_days`, `last_N_months`, `yesterday`, and
`all_time`), deterministic exact bounded date/datetime interval representations, or explicit
validated start/end bounds. Reject vague values such as `recent` before provisional merge with
typed `TIME_RANGE_NOT_OPERATIONALLY_CONCRETE`; do not normalize or default them.
Evidence: M15's minimal live smoke produced structurally valid `RELATIVE/recent` and the old policy
authorized READY because the TimeRange object existed. Permanent provider-free regressions cover
that exact false-READY path, canonical relative admission, exact bounded interval admission, and
zero dialogue-store mutation on rejection.
Consequences: Scalar SET remains a proposal rather than proof of resolution. No public M8
contract, prompt, clarification-targeting rule, M9–M15 behavior, Golden/Oracle asset, model/runtime
bound, or acceptance threshold changes.

## 7. Deviation rule

If implementation reveals that a binding architecture decision is invalid:

1. do not silently work around it;
2. describe the failing assumption;
3. add evidence/test demonstrating the issue;
4. propose the smallest architecture amendment;
5. update the relevant document only after explicit review.
