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
the versioned fingerprint of the exact bounded M9 `PlannerContext`, `SQLGuardResult`, and accepted
`ExplainResult` for future M11 consumption.

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

M9 computes `planner-context-fingerprint-v0.1` over canonical JSON for the complete bounded
`PlannerContext`, including requirement state, ordered allowed tables, full bounded M6 documents
and relationships, and catalog/retrieval identities. M10 binds that fingerprint beside the
QueryPlan fingerprint in its capability; M11 propagates it in execution metadata; M12 recomputes
the current trace context and requires all three stored identities to match before any check.

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

---

## D-028 — Repair is a typed, persisted replacement-plan branch

**Decision:** M13 repair eligibility is a default-deny policy over typed stage/category/code
evidence, never diagnostic text. The initial allowlist covers M10 parse formulation, MySQL error
codes `1052`/`1054` from EXPLAIN or runtime, and selected M12 output-shape/alias, unique governed
source, governed direct-JOIN, and grouping-key formulation checks. Policy/cost/integrity,
capability/namespace, availability/timeout/decoding, truncation, and verification coverage gaps are
terminal or non-triggering and make no repair-model call.

Each internal `RepairFailure v0.2` includes the source Run identity in its canonical fingerprint.
The repair entry point rejects a caller-supplied Run mismatch before repository or model access.
An eligible attempt maps `SQL_GUARD`/`EXPLAIN` to `VALIDATING`, `RUNTIME` to `EXECUTING`, and
`VERIFICATION` to `VERIFYING`; the repository checks that exact state and atomically increments
durable `Run.repair_count` under one row lock before inference. It proposes a new full public
`QueryPlan v0.1` with `query-repair-v0.1` under the exact original
`PlannerContext`; retrieval, catalog, RequirementState, and authorized tables cannot expand. The
replacement passes M9 `PlannerPolicy`, a fresh M10 guard and EXPLAIN, a fresh M11 execution, and a
fresh M12 verification. Previous capabilities, execution evidence, results, and verification are
never mutated or reused. Internal versioned failure and trace evidence binds both branches without
raw result rows. `VALIDATING → REPAIR_EXHAUSTED` is legal so a consumed M10-stage attempt can end
without a new `REPAIRING` status.

**Reason:** Retrying unchanged evidence cannot correct formulation and lets concurrency obscure the
attempt bound. Without source Run and lifecycle-stage binding, the same failed branch could consume
another Run's budget or claim from the wrong lifecycle point. Text classification would allow
provider or prompt content to influence authority.
Reusing downstream evidence would break the M9→M12 identity chain. A durable pre-inference claim
and exact-context replacement branch are the smallest design that makes the default one-attempt
limit auditable and fail closed.

A competing caller that observes an already-consumed positive attempt budget makes no model call
and does not mutate the Run: the in-flight attempt owner alone may advance or terminalize that
branch. A configured zero-attempt budget has no possible owner and terminates directly as
`REPAIR_EXHAUSTED`. This prevents one concurrent observer from invalidating a legitimately running
repair while the database counter still enforces the global bound.

**Provider grammar amendment:** Bound Ollama evidence showed that `QueryPlan v0.1`'s intentionally
default-empty `expected_columns` field was emitted empty in two of three repair cases; the SQL then
executed and M12 correctly rejected the missing output-shape evidence. M13 therefore requests an
internal `RepairPlanProposal` with `expected_columns` constrained to at least one item and
immediately normalizes it to public `QueryPlan v0.1`. The DTO adds no field or semantic authority
and does not bypass M9 policy or any downstream check.

---

## D-029 — Answer language is proposed; the response envelope is deterministic

**Decision:** M14 accepts only an integrity-checked final M9→M12 branch whose public
`VerificationTrace` result is `PASSED`. A successful repair may substitute only its newly planned,
admitted, executed, and verified branch. The provider-facing `AnswerProposal v0.1` contains
natural-language answer text and unique positional `(row_index, column_index)` references. The
model cannot produce result rows, assumptions, tables, SQL, counts, duration, repair status,
verification status/coverage, synthesis mode, or Run state.

Deterministic grounding rejects out-of-range references, unreferenced non-empty results,
unreferenced numeric claims, and arithmetic-derived percentages absent as exact evidence. Request,
requirement, scope, filter, and limit numbers never become fungible authority for result-number
claims; every numeric token in model answer text must also occur in a cited result cell. Exact
`Decimal` cells cross the JSON API as strings. Verification scope is always reported as
`COVERAGE_BOUNDED`; coverage is applied checks divided by applied plus `UNSUPPORTED` checks,
excluding `NOT_APPLICABLE` gaps, and every unsupported limitation remains visible. Oversized
answer context makes zero model calls and returns a typed deterministic no-new-facts fallback
while preserving the exact bounded result in the response.

The conversation orchestrator owns only sequencing and Run transitions over M8–M14 services. A
minimal control-plane unit of work atomically commits the M8 Session/user/optional-clarification
turn with its Run outcome, and separately atomically appends the final assistant answer with
`SYNTHESIZING → COMPLETED`.

**Reason:** Letting answer inference regenerate evidence would undo the M9–M12 authority chain at
the user boundary. Positional references remain unambiguous with duplicate column labels, while
atomic completion prevents conversation history and Run state from reporting contradictory
durable outcomes.

---

## D-030 — Trace is append-only evidence; Golden truth is acceptance-only

**Decision:** M15 persists observable pipeline outcomes in a dedicated append-only
`agent_trace_event` table. Each event has a unique ID, Run/Session identity, contiguous per-Run
sequence, bounded attempt (`0` or `1`), typed stage/event, schema version, bounded JSON payload,
canonical payload fingerprint, and timestamp. Event-type/stage pairing, sensitive/raw-row field
rejection, payload size, reload fingerprint, sequence, identity, ordering, attempt branches, and
terminal completeness are deterministic policies. Required `COMPLETED`, `CLARIFYING`, and failure
terminal events share the control-plane transaction that persists their terminal Run outcome; a
trace write failure cannot be converted to a successful public response. Repair services retain
their frozen standalone transition behavior, while production defers repair terminal transitions
to this trace-aware unit of work.

The source-controlled `evals/golden.yaml` contains 59 public Session/Message API cases. Trusted
Oracle SQL is static and isolated in `evals/oracles.yaml`; it is validated as one read-only SELECT
and used only by the top-level `eval_harness` package. Runtime packages and every model prompt are
mechanically prohibited from importing either acceptance source. Golden result assertions compare
typed result values independent of row order and do not require exact generated SQL text.
`EvaluationEnvironment v0.1` binds Git, Golden, generated schema, semantic catalog/revision,
retrieval index, both model fingerprints, Ollama, all prompt/policy versions, trace schema,
dependency lock, and Python under one canonical fingerprint.
Final report construction rejects a dirty Git worktree and records UTC as the evaluation timezone.

**Reason:** A trace must make execution auditable without becoming a second semantic or policy
authority, and it must not persist hidden chain-of-thought, credentials, answer duplicates, or raw
result rows. Allowing Golden expectations or Oracle SQL into runtime/model context would leak the
answer and invalidate acceptance evidence. Model scores without a complete environment identity
cannot distinguish behavioral change from model, data, catalog, prompt, policy, or dependency
drift.

---

## D-031 — Golden semantics are model-neutral; behavioral evidence is model-bound

**Decision:** Freeze 59 meaningful controlled-world cases independently of whether the initially
available local model passes them. The suite contains 55 Oracle-backed result cases over 54
distinct semantic/result Oracles, including 15 simple, 22 aggregation/time, 11 relationship/trap,
two empty-population, four multi-turn clarification/correction, one repair-eligible formulation,
and four safe terminal-failure paths. Every result is judged against static typed values and
governed table evidence; no prompt receives acceptance truth, no SQL text is compared, and no
behavioral gate is lowered.

The initial `gemma4:latest` is an 8B Q4 local model. Its pre-freeze 54-case challenge run achieved
Golden E2E `0.352`, result-Oracle `0.365`, and trace integrity `1.000`. Common failure shapes were
spurious grouping, omitted filters, and wrong governed dimensions. That result remains valid
diagnostic evidence for that exact environment, not a reason to remove hard cases. Final release
behavioral acceptance may use a stronger local Ollama chat model, but its immutable
`ModelFingerprint` and all other environment identities must be recorded and the entire frozen
suite rerun. Small-model failure is permitted only within the probabilistic behavior thresholds;
deterministic safety and trace gates remain exact.

All structured chat calls retain temperature zero, disable thinking where supported, and apply
the configured 2,048-token generation ceiling. Final evaluation identity binds both this ceiling
and the request timeout. This resource bound is model-family neutral: it prevents a capable larger
model from turning a bounded JSON contract into an unbounded generation without changing any
prompt, Oracle, or behavioral truth.

**Reason:** Golden truth describes intended product semantics, while an environment-bound score
describes one model's capability. Optimizing case selection around an 8B model would reverse that
authority relationship and overstate generalization. A stronger model may improve behavior, but
cannot change Oracle truth, catalog authority, safety policy, or the scored suite.

---

## D-032 — M12 independently proves the governed public analytical shape

**Decision:** `verification-policy-v0.2` treats the READY `RequirementState`, not a mutually
consistent `QueryPlan` and `ExecutionResult`, as the independent authority for the public
analytical shape. In an aggregate query, the public grouping outputs must equal the requested
resolved dimensions plus `period` exactly when a time grain was requested. The complete public
result-column set must equal the requested resolved metrics, resolved dimensions, and applicable
`period`; additional public columns fail even when the Plan predicted them. Every requested
dimension must also bind to exactly one M6 governed column and the matching public projection
lineage. An absent, ambiguous, or mismatched governed dimension binding is a failed semantic check,
not a successful check or an unsupported coverage pass.

Output identity uses only final SELECT projections. Aggregate grain additionally inspects every
final SELECT `GROUP BY` partition key: each key must map exactly to one requested public
non-aggregate projection, by expression, unambiguous alias, or ordinal. Current M6 metadata does
not encode enough uniqueness/functional-dependency authority to excuse a hidden grouping key, so
an unmatched key fails closed. MySQL resolves an unqualified `GROUP BY` name against input columns
before SELECT aliases, so the alias path is unambiguous only when bounded final-scope metadata
proves that no input column has that name; complex or incomplete source scope fails closed. SQL
helpers outside the final `GROUP BY` (for example JOIN or WHERE columns) remain outside this check.
Formula and time-filter equivalence still remain explicit coverage gaps where current contracts
cannot prove them.

**Reason:** M15 diagnosis found plans that introduced an unrequested grouping dimension and then
validated themselves because their expected columns matched the executed result. It also found a
generic `channel` output whose requested semantic source could not be uniquely established from
the bounded M6 catalog. Required-output containment alone allowed both shapes to receive M12
`PASSED` despite deterministic Oracle disagreement.

**Consequences:** A wrong Plan and matching wrong result can no longer authorize one another, and a
hidden `GROUP BY` key cannot silently refine the requested grain. Repairable output-set,
projection-lineage, and grouping formulation checks retain the existing typed M13 path. Missing or
ambiguous M6 dimension authority is a distinct nonrepairable check and therefore consumes no model
call or durable repair attempt. M13's bound, prompt, stage/category gate, and all other eligibility
classes remain unchanged. Public `VerificationResult v0.1` and the M8/M9/M10/M11/M13/M14
contracts remain unchanged.

---

## D-033 — M8 readiness is derived from material structured ambiguity

**Decision:** Reopen M8 narrowly with internal `blocking-ambiguity-policy-v0.1`. The model's action
and ambiguity list are candidates. The Harness normalizes an unsuppressed `RequirementPatch`,
provisionally merges it, classifies every candidate with stable machine reason codes, suppresses
only mutations attributable to candidates proven blocking, and constructs the final public
`DialogueDecision`. Missing `time_range` and `grain` remain valid unspecified scope. A confirmed
metric/dimension in merged state outranks provider uncertainty. Provider explanation text and M15
expected answers are never policy inputs.

A candidate is material only when structured evidence proves unresolved competing executable
interpretations. Prompt `dialogue-understanding-v0.21` therefore minimally requires at least two
concrete options for a blocker and a matching `UNRESOLVED` metric/dimension item when applicable;
it also states explicitly that absent time/grain is optional. This wire amendment supplies
evidence but does not become final authority. Public `RequirementState v0.1`,
`DialogueDecision v0.1`, and `RequirementPatch v0.2` remain unchanged.

The Harness evaluates those evidence candidates with deterministic policy. Evidence that proves
neither blocking nor nonblocking is invalid and produces no decision; it cannot fall through to
READY. This is a narrow trust-boundary rule rather than a general ambiguity-proof protocol. ASK
requires at least one Harness-proven blocker. Exact question-to-blocker binding and clarification
wording are deferred behavioral refinements, not MVP readiness authority.

**Reason:** Draft M15 diagnosis replayed 35 unexpected clarifications in standalone M8. The old
normalizer treated model ASK as effective readiness authority and suppressed patch facts before
the Harness could observe that the cited ambiguity was optional, stale, or already resolved. The
same diagnosis and the accepted M8 report also showed that old `v0.20` outputs left competing
options empty and omitted structured unresolved metric facts, so deterministic positive recall
could not be maintained by policy alone without hard-coding business terminology.

**Consequences:** The exact 35-case provider-free corpus must produce zero unnecessary
clarifications, while metric, dimension, explicit-time, and explicit-grain controls retain
clarification recall `1.000` and false READY `0`. Suppression cannot inject default time/grain or
erase confirmed siblings. Existing bounded context and atomic persistence/CAS behavior remain
unchanged. M9–M15 behavior, Golden/Oracle truth, model/resource identity, and final thresholds are
outside this remediation.

Every legacy proposal lacking an exact resolved or unresolved subject match must fail with invalid
provider evidence. The empty-state case that omitted every requested analytical fact has a separate
complete-READY control. The gate fixes insufficient-evidence false READY at zero. Clarification
question targeting remains deferred unless later end-to-end evidence proves it prevents
convergence.

---

## D-034 — Provider time-range mutation requires deterministic operational admission

**Decision:** A provider `time_range SET` remains an untrusted proposal even after public
`TimeRange v0.1` validation. Before provisional merge or blocker classification, internal
`time-range-admission-policy-v0.1` admits only the already-supported operational forms: canonical
relative values `last_<positive integer>_days`, `last_<positive integer>_months`, `yesterday`, or
`all_time`; an existing exact bounded date/datetime interval encoded with `to` or `/`; or explicit
validated `start` and `end` bounds. The policy does not rewrite the value or infer a default.

Any other SET value, including vague free-form relative language such as `recent`, raises typed
`InvalidProviderEvidenceError(TIME_RANGE_NOT_OPERATIONALLY_CONCRETE)`. It emits no public
`DialogueDecision` and therefore cannot reach dialogue-turn persistence. Public
`RequirementState v0.1`, `TimeRange v0.1`, `RequirementPatch v0.2`, the provider prompt, and
clarification-question targeting remain unchanged.

**Reason:** M15 live smoke observed the provider encode a genuinely ambiguous relative phrase as
`TimeRange(kind=RELATIVE, value=recent)`. The old policy treated object existence as semantic
resolution and authorized READY. Contract shape proves only structural validity; it cannot grant
control-plane authority to an unconstrained free-form value.

**Consequences:** The Harness closes this specific false-READY path without becoming a general
natural-language temporal parser. Canonical and exactly bounded existing representations continue
to compose with M9, while vague values fail before state mutation. M9–M15 behavior, Golden/Oracle
truth, model/resource settings, and acceptance thresholds remain frozen.

---

## D-035 — Final acceptance completion is distinct from product acceptance

**Decision:** Treat final acceptance as an adjudication process with exactly three terminal
outcomes:

```text
ACCEPTED
    a complete canonical run exists and every frozen acceptance gate passes

REJECTED
    a complete canonical run exists and one or more frozen acceptance gates fail

INVALID / ABORTED
    no complete canonical adjudication can be produced
```

Completion and substantive correctness of the M15 trace/evaluation infrastructure are reviewed
independently of whether the bound model earns `ACCEPTED`. A `REJECTED` adjudication is a valid
completed evaluation result, never a behavioral pass. The Product NL2SQL MVP and its release/tag
remain unauthorized unless the canonical adjudication is `ACCEPTED`.

**Reason:** The final frozen-environment run completed all 59 cases with a fully bound report and
correctly rejected the current product behavior: E2E `10/59`, result Oracle `6/55`, while trace
integrity was `1.000` and every deterministic safety/epistemic-integrity violation count remained
zero. Requiring a passing product score before the evaluation infrastructure can close would make
an acceptance system incomplete precisely when it successfully proves the candidate unfit for
release.

**Consequences:** The earlier MySQL/trace timeout attempt is `INVALID / ABORTED`; the complete
59-case run is `REJECTED`. No Golden case, Oracle, threshold, model, prompt, policy, timeout, or
token bound changes. M15 evaluation infrastructure may be substantively approved and merged after
its own correctness gate while the behavioral verdict remains `REJECTED`, the Product NL2SQL MVP
remains `NOT ACCEPTED`, and no MVP release/tag is created.
