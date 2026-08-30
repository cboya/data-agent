# Core Contracts

**Version:** v0.1.0
**Status:** Binding semantic contract; implementation syntax may vary

The examples use Python/Pydantic-like notation for clarity. The exact code is generated during implementation.

## 1. Contract rules

1. Boundary objects are validated.
2. Unknown enum values fail explicitly unless a contract says otherwise.
3. Model-generated control data uses structured output and is parsed into these contracts.
4. IDs are opaque stable strings.
5. Persisted contracts include a version field where schema evolution matters.
6. Timestamps are timezone-aware ISO-8601 values in external representations.
7. Unknown fields are rejected at contract boundaries.
8. Collection defaults are created per model instance; implementations must not use shared
   mutable defaults.
9. Required identifiers and control text reject empty or whitespace-only values.

---

## 2. Session

```python
class SessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class Session(BaseModel):
    id: str
    status: SessionStatus
    requirement: RequirementState
    created_at: datetime
    updated_at: datetime
```

MVP need not model user identity beyond an optional external identifier.

`updated_at` must not precede `created_at`.

Optimistic-concurrency revision is persistence metadata returned alongside `Session`; it is not
part of the frozen domain `Session` shape. A successful update increments the stored revision,
and a stale expected revision fails rather than overwriting newer requirement state.

---

## 3. Message

```python
class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"

class Message(BaseModel):
    id: str
    session_id: str
    role: MessageRole
    content: str
    created_at: datetime
```

Persistence rule: append-only.

Persistence assigns a unique, monotonically increasing per-session sequence for deterministic
ordering. Sequence is persistence metadata and does not change the frozen `Message` shape.

Internal tool/trace events are artifacts/run events, not user-visible `Message` records.

---

## 4. RequirementState

### 4.1 Status

```python
class RequirementStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    CLARIFYING = "CLARIFYING"
    READY = "READY"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
```

### 4.2 Metric requirement

```python
class ResolutionStatus(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    INFERRED = "INFERRED"
    CONFIRMED = "CONFIRMED"

class MetricRequirement(BaseModel):
    term: str
    resolved_name: str | None = None
    definition: str | None = None
    status: ResolutionStatus
```

### 4.3 Dimension/filter/time

```python
class DimensionRequirement(BaseModel):
    term: str
    resolved_name: str | None = None
    status: ResolutionStatus

class FilterRequirement(BaseModel):
    field_term: str
    operator: str
    value: Any

class TimeRange(BaseModel):
    kind: Literal["RELATIVE", "ABSOLUTE"]
    value: str
    start: datetime | date | None = None
    end: datetime | date | None = None
```

Datetime bounds must be timezone-aware. When both bounds are supplied, `end` must not precede
`start`.

### 4.4 Ambiguity

```python
class Ambiguity(BaseModel):
    field: str
    reason: str
    options: list[str] = []
    blocking: bool = True
```

### 4.5 State

```python
class RequirementState(BaseModel):
    version: Literal["v0.1"]
    goal: str | None = None
    metrics: list[MetricRequirement] = []
    dimensions: list[DimensionRequirement] = []
    filters: list[FilterRequirement] = []
    time_range: TimeRange | None = None
    grain: str | None = None
    comparison: str | None = None
    sort: str | None = None
    limit: int | None = None
    confirmed_terms: dict[str, str] = {}
    assumptions: list[str] = []
    unresolved: list[Ambiguity] = []
    status: RequirementStatus
```

Invariant:

```text
status == READY  ⇒  unresolved contains no blocking ambiguity
```

---

## 5. RequirementPatch

Model turns should patch, not regenerate, the full canonical state.

```python
class PatchOp(str, Enum):
    NO_CHANGE = "NO_CHANGE"
    SET = "SET"
    CLEAR = "CLEAR"

class NoChangeScalarPatch(BaseModel):
    op: Literal[PatchOp.NO_CHANGE]
    value: None = None

class ClearScalarPatch(BaseModel):
    op: Literal[PatchOp.CLEAR]
    value: None = None

class SetScalarPatch[T](BaseModel):
    op: Literal[PatchOp.SET]
    value: T

ScalarPatch[T] = Annotated[
    NoChangeScalarPatch | ClearScalarPatch | SetScalarPatch[T],
    Field(discriminator="op"),
]

class RequirementPatch(BaseModel):
    version: Literal["v0.2"] = "v0.2"
    goal: ScalarPatch[str] = ScalarPatch()
    time_range: ScalarPatch[TimeRange] = ScalarPatch()
    grain: ScalarPatch[str] = ScalarPatch()
    comparison: ScalarPatch[str] = ScalarPatch()
    sort: ScalarPatch[str] = ScalarPatch()
    limit: ScalarPatch[int] = ScalarPatch()
    metrics_upsert: list[MetricRequirement] = []
    metrics_remove: list[str] = []
    dimensions_upsert: list[DimensionRequirement] = []
    dimensions_remove: list[str] = []
    filters_replace: list[FilterRequirement] | None = None
    confirmed_terms_upsert: dict[str, str] = {}
    assumptions_add: list[str] = []
    unresolved_replace: list[Ambiguity] | None = None
```

Scalar invariants:

```text
NO_CHANGE ⇒ value is null and the current value is preserved
SET       ⇒ value is present, contract-valid, and replaces the current value
CLEAR     ⇒ value is null and the current value is removed
```

An omitted scalar operation normalizes to `NO_CHANGE`. Explicit clear is never encoded as an
ambiguous bare `null`. `RequirementPatch` is v0.2 because the mutation wire protocol evolved;
the persisted `RequirementState` representation remains v0.1.

Collection suffixes are operational semantics, not naming decoration:

- `*_upsert` merges keyed domain values;
- `*_remove` explicitly removes keyed domain values;
- `*_replace` replaces the canonical value when supplied;
- `*_add` appends values without regenerating canonical state.

Metric/dimension identity is `resolved_name` when present, otherwise `term`. Remove entries name
that identity exactly. A remove and upsert of the same identity in one patch is invalid. An omitted
optional collection replacement means "no change"; an empty replacement collection explicitly
clears it. The deterministic merge algorithm is M8 application code and never guesses correction
intent from natural-language similarity.

---

## 6. DialogueDecision

```python
class DialogueAction(str, Enum):
    ASK_CLARIFICATION = "ASK_CLARIFICATION"
    READY = "READY"
    CANNOT_RESOLVE = "CANNOT_RESOLVE"

class DialogueDecision(BaseModel):
    version: Literal["v0.1"]
    patch: RequirementPatch
    action: DialogueAction
    question: str | None = None
    reason: str
```

Invariants:

```text
ASK_CLARIFICATION ⇒ question is non-empty
READY ⇒ question is None
```

The LLM proposes the mutation and clarification candidates. The harness owns the final decision.
The model cannot write `RequirementState.status`; deterministic dialogue policy derives it after
merge. `ASK_CLARIFICATION` is accepted only when deterministic blocking policy proves a material,
execution-affecting ambiguity in the merged state, and `READY` only when it proves none.

The Ollama boundary does not deserialize directly into the public decision. It first validates a
provider-facing `DialogueProposal v0.1` containing a mutation patch and an action-discriminated
`resolution`. Provider grain/comparison enum values are deterministically normalized into
`ScalarPatch` operations, then the complete unsuppressed candidate patch is provisionally merged.
Provider blocking ambiguity adds a required `subject_term` copied from the ambiguous surface
phrase. Internal `BlockingAmbiguityPolicy` classifies each candidate with stable reason codes from
the provisional merged state, exact subject attribution, explicit patch operations, structured
resolution status, and concrete competing options. Free-form provider reasons are never
readiness authority. A missing optional `time_range` or `grain` is not a blocker; a resolved
metric/dimension cannot remain blocked; a genuinely unresolved material candidate remains
blocking. Only proven blockers suppress their attributable mutation and cross the public
`Ambiguity` boundary. The final `DialogueDecision` is rebuilt and revalidated after this policy.
Collection removes that cannot be safely attributed and a filter replacement paired with a proven
filter blocker fail closed instead of silently dropping facts.

Prompt `dialogue-understanding-v0.21` asks the provider for the structured alternatives and
unresolved collection evidence needed by deterministic policy, but does not create a second
semantic authority or a specialized proof protocol. If the submitted evidence proves neither a
blocking nor a nonblocking outcome, resolution raises typed `InvalidProviderEvidenceError` and
emits no `DialogueDecision`; insufficient evidence never certifies READY. An ASK outcome requires
at least one Harness-proven blocker. Clarification wording and exact question-to-blocker targeting
remain behavioral concerns outside this MVP control-plane gate. Public `DialogueDecision v0.1`
and `RequirementState v0.1` remain unchanged.

Public validation of a provider `TimeRange` proves its shape, not semantic resolution. Internal
`time-range-admission-policy-v0.1` must admit every provider `time_range SET` before provisional
merge. It accepts the project's canonical relative values, its existing exact bounded
date/datetime interval representation, or explicit validated `start` plus `end`; vague free-form
relative values fail with typed invalid provider evidence. Rejection emits no public decision and
cannot mutate durable state. The policy does not normalize vague text, inject a default, or change
public `TimeRange v0.1`.

---

## 7. CatalogDocument

```python
class CatalogColumn(BaseModel):
    name: str
    data_type: str
    description: str | None = None
    aliases: list[str] = []
    nullable: bool | None = None
    primary_key: bool = False

class CatalogDocument(BaseModel):
    version: Literal["v0.1"]
    table: str
    aliases: list[str] = []
    description: str
    business_rules: list[str] = []
    columns: list[CatalogColumn]
    typical_use_cases: list[str] = []
    generated_metadata_fingerprint: str
    semantic_revision: str
```

`CatalogDocument` is assembled from generated metadata + curated semantic overlays.
It contains at least one column, and column names are unique within the document.

---

## 8. Relationship

```python
class Cardinality(str, Enum):
    ONE_TO_ONE = "ONE_TO_ONE"
    ONE_TO_MANY = "ONE_TO_MANY"
    MANY_TO_ONE = "MANY_TO_ONE"
    MANY_TO_MANY = "MANY_TO_MANY"

class Relationship(BaseModel):
    version: Literal["v0.1"]
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    cardinality: Cardinality
    description: str
    curated: bool
```

Relationship graph expansion must have an explicit hop bound.

---

## 9. RetrievalResult

```python
class RetrievalHit(BaseModel):
    table: str
    lexical_rank: int | None = None
    semantic_rank: int | None = None
    fused_score: float
    rerank_score: float | None = None
    reason: str | None = None
    source: Literal["SEED", "GRAPH_EXPANSION"]

class RetrievalResult(BaseModel):
    version: Literal["v0.1"]
    query: str
    hits: list[RetrievalHit]
    relationships: list[Relationship]
    index_fingerprint: str
```

The planner may only receive catalog documents represented by the accepted `RetrievalResult`
schema slice. M9 context construction requires an exact table match between final hits and supplied
documents, accepts only the result's relationships, and fails closed on identity or endpoint
inconsistency.

---

## 10. QueryPlan

```python
class ExpectedColumn(BaseModel):
    name: str
    semantic_role: str | None = None

class QueryPlan(BaseModel):
    version: Literal["v0.1"]
    intent: str
    tables: list[str]
    assumptions: list[str] = []
    sql: str
    expected_columns: list[ExpectedColumn] = []
    explanation: str | None = None
```

Hard invariant:

```text
set(Tables(SQL)) ⊆ set(QueryPlan.tables)
```

`QueryPlan.tables` must itself be a subset of authorized/retrieved tables.
The declared table list is non-empty and unique under M9 policy. M9 does not parse `sql`; SQL
referenced-table extraction and subset enforcement are M10 behavior.

---

## 11. SQLGuardResult

```python
class GuardStatus(str, Enum):
    PASSED = "PASSED"
    REJECTED = "REJECTED"

class SQLGuardResult(BaseModel):
    status: GuardStatus
    referenced_tables: list[str]
    violations: list[str]
```

Only `PASSED` may reach EXPLAIN/execution.
`PASSED` has no violations; `REJECTED` has at least one violation.

M10 additionally owns an internal immutable `GuardedQuery` capability that binds the exact
validated SQL payload and digest, QueryPlan identity/reference, the versioned fingerprint of the
exact bounded M9 `PlannerContext`, M10 analytics execution namespace, passed guard evidence, and
accepted EXPLAIN evidence. It is not a public domain contract or a replacement for
`SQLGuardResult`. Future M11 code consumes this capability rather than accepting arbitrary raw
SQL.

---

## 12. ExplainResult

```python
class ExplainTableAccess(BaseModel):
    table: str
    access_type: str | None = None
    key: str | None = None
    estimated_rows: int | None = None

class ExplainResult(BaseModel):
    accepted: bool
    accesses: list[ExplainTableAccess]
    rejection_reason: str | None = None
```

An accepted result has no rejection reason; a rejected result has a non-empty rejection reason.

---

## 13. ExecutionResult

```python
class ExecutionResult(BaseModel):
    version: Literal["v0.1"]
    columns: list[str]
    rows: list[list[Any]]
    returned_row_count: int
    duration_ms: int
    truncated: bool
```

Never put an unbounded result into model context.

`returned_row_count` is exactly the number of bounded rows present in `rows`. It does not claim
to be the database's total pre-truncation result size, which may be unknown. Every row must match
the declared column count.

M11 derives `columns` from database cursor metadata and retains positional rows, including
duplicate column names. It preserves `Decimal`, integer, finite float, date/datetime, string, and
null values without lossy conversion; unsupported values fail closed. Row truncation and the
separate deterministic normalized-byte budget both set `truncated=true` without claiming the
unread result cardinality.

Execution metadata is an internal versioned evidence record, not a replacement for this public
result contract. Internal `execution-metadata-v0.2` carries capability, QueryPlan,
PlannerContext, and policy identities, physical tables, database principal class, bounds, timings,
counts, truncation, typed outcome, and a versioned fingerprint of the exact bounded result, but
never contains `rows`. The result fingerprint covers ordered actual columns, typed positional
rows, returned row count, truncation, and the public result version; it excludes execution IDs,
timestamps, and duration.

---

## 14. VerificationResult

```python
class CheckResult(BaseModel):
    name: str
    category: Literal["STRUCTURAL", "SEMANTIC", "EMPIRICAL"]
    passed: bool
    detail: str | None = None

class VerificationResult(BaseModel):
    version: Literal["v0.1"]
    status: Literal["PASSED", "FAILED"]
    checks: list[CheckResult]
```

`FAILED` cannot transition directly to final answer synthesis.
`PASSED` contains no failed check; `FAILED` contains at least one failed check.

For M12, `PASSED` means every applicable deterministic check encoded by the current verification
policy passed. It is not a complete proof of business correctness. Checks that are not applicable
or cannot be proven from current structured semantics are absent from `checks` and recorded as
explicit internal `VerificationTrace` coverage gaps; they must not be encoded as
`CheckResult(passed=True)`. A typed `VerificationIntegrityError` is raised before these checks when
the M9 planning, M10 capability, M11 metadata, and bounded result identities do not form one
coherent evidence chain.

Beginning with `verification-policy-v0.2`, public analytical shape is an applicable deterministic
invariant whenever the READY requirement supplies resolved output names. The authoritative public
set is its resolved metrics and dimensions plus `period` exactly when `grain` is present. For an
aggregate result, every final `GROUP BY` partition key must map exactly to a requested public
non-aggregate projection, and those mapped outputs must equal the requested dimensions plus
applicable `period`. Hidden grouping keys fail closed unless a future governed contract can prove
the required functional dependency. An unqualified `GROUP BY` name maps to a SELECT alias only
when bounded final-scope metadata proves no input column can claim that name under MySQL's
source-column-first resolution; otherwise it is hidden/ambiguous and fails closed. Ordinary
non-grouping SQL helpers do not participate. Each requested dimension must resolve to exactly one
bounded M6 catalog column and be present in that output projection's SQL lineage. QueryPlan
expected columns remain useful structural evidence but cannot expand this RequirementState-owned
authority.

The internal `planner-context-fingerprint-v0.1` is SHA-256 over canonical JSON containing its
fingerprint version and the complete `PlannerContext`: context version, authoritative
`RequirementState`, ordered allowed tables, bounded M6 `CatalogDocument` semantic contents,
bounded M6 `Relationship` values, and all `PlannerCatalogIdentity` fields. M9 records it when the
plan is accepted; M10 includes it in capability identity; M11 copies it into execution metadata;
M12 recomputes and compares every link before semantic verification.

---

## 15. Artifact

```python
class ArtifactType(str, Enum):
    REQUIREMENT_STATE = "REQUIREMENT_STATE"
    RETRIEVAL_RESULT = "RETRIEVAL_RESULT"
    QUERY_PLAN = "QUERY_PLAN"
    SQL_GUARD = "SQL_GUARD"
    EXPLAIN = "EXPLAIN"
    EXECUTION_METADATA = "EXECUTION_METADATA"
    VERIFICATION = "VERIFICATION"

class Artifact(BaseModel):
    id: str
    session_id: str
    run_id: str
    type: ArtifactType
    contract_version: str
    payload: dict[str, Any]
    created_at: datetime
```

Large raw result payloads should not automatically be persisted here.

---

## 16. Run

```python
class RunStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDERSTANDING = "UNDERSTANDING"
    CLARIFYING = "CLARIFYING"
    RETRIEVING = "RETRIEVING"
    PLANNING = "PLANNING"
    VALIDATING = "VALIDATING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SYNTHESIZING = "SYNTHESIZING"
    COMPLETED = "COMPLETED"
    POLICY_DENIED = "POLICY_DENIED"
    QUERY_TOO_EXPENSIVE = "QUERY_TOO_EXPENSIVE"
    REPAIR_EXHAUSTED = "REPAIR_EXHAUSTED"
    FAILED = "FAILED"

class Run(BaseModel):
    id: str
    session_id: str
    status: RunStatus
    repair_count: int = 0
    started_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = None
```

`Run` is a data contract only. Valid status transitions and terminal-state behavior belong to the
M3 run state machine and must not be embedded in this model.
If `completed_at` is present, it must not precede `started_at`.

One Run represents processing one inbound user message. `CLARIFYING`, `COMPLETED`,
`POLICY_DENIED`, `QUERY_TOO_EXPENSIVE`, `REPAIR_EXHAUSTED`, and `FAILED` are terminal outcomes;
a later user reply creates a new Run in the same Session.

M13 does not add a public repair contract or Run status. Internal `RepairFailure v0.2` carries its
source Run ID, a typed stage/category/code, optional bounded provider errno/SQLSTATE and sanitized
diagnostic detail, the original QueryPlan and PlannerContext fingerprints, and applicable
downstream fingerprints. Its canonical `repair-failure-fingerprint-v0.2` binds the source Run and
determines evidence identity, not eligibility. Internal `RepairTrace v0.2` records that source Run
and binds policy/prompt versions, attempt/max, failure, original/replacement plan fingerprints,
unchanged PlannerContext fingerprint, model/runtime, outcome, and final verification identity on
success. `SQL_GUARD`/`EXPLAIN`, `RUNTIME`, and `VERIFICATION` failure stages may claim only from
`VALIDATING`, `EXECUTING`, and `VERIFYING`, respectively; this check is atomic with the attempt
increment. Neither type contains raw result rows.
The provider-facing `RepairPlanProposal` mirrors public `QueryPlan v0.1` but requires at least one
`expected_columns` item; it is normalized immediately to `QueryPlan` and is never persisted or
treated as semantic authority.

---

## 17. Internal model ports

The domain/harness must not import Ollama-specific response objects.

```python
T = TypeVar("T", bound=BaseModel)

class ChatModel(Protocol):
    async def structured(
        self,
        *,
        messages: list[dict[str, str]],
        response_type: type[T],
        purpose: str,
    ) -> T: ...

class EmbeddingModel(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Adapters may expose observability metadata separately without leaking transport details into domain contracts.

Startup diagnostics are exposed through a provider-neutral `ModelRuntimeProbe`. Its result
contains runtime version plus chat/embedding `ModelFingerprint` values built from provider,
configured model/deployment name, declared capabilities, and bounded descriptive metadata.
Identity additionally records the base-endpoint identity, an actual immutable digest or provider
revision when one is exposed, and assurance (`IMMUTABLE_PROVIDER_REVISION`,
`PINNED_DEPLOYMENT`, or `ALIAS_ONLY`). A provider that exposes only a mutable alias has no digest;
it must not be represented as immutable. Provider request/response DTOs remain inside adapters.

The composition root must bind each runtime adapter to the corresponding startup fingerprint;
an adapter must not execute from an unbound mutable model tag. If a provider cannot execute a
digest-qualified reference, the provider adapter must revalidate the configured tag-to-digest
mapping immediately before every model request and fail closed with a typed identity-drift error
when the mapping no longer matches.

The M16 OpenAI-compatible profile revalidates its configured identity source before every request.
The default source is `GET /models/{id}`. The explicit `cloudflare_workers_ai` source instead
requires one exact authenticated account-catalog match with the expected Chat or Embedding task
and stable bounded metadata; it is not selected automatically after a provider error. When the
descriptor exposes a revision/snapshot, drift fails closed. When it exposes only an alias, that
limitation remains explicit as `ALIAS_ONLY`; the adapter cannot claim to detect underlying weights
movement that the provider does not reveal.

For canonical evaluation, runtime composition exposes one provider-neutral resource-evidence
record for the exact bound runtime. `EvaluationEnvironment v0.2` consumes that record rather than
reselecting provider-specific settings. It binds provider, runtime version, both fingerprints and
assurances, request timeout, and max-output-token bound. Product identity eligibility is derived
from those assurances: any `ALIAS_ONLY` member forbids canonical Product acceptance while
remaining usable for portability and diagnostic evidence. Historical `EvaluationEnvironment
v0.1` remains unchanged and parseable.

---

## 18. M14 answer and conversation response boundaries

`AnswerSynthesisContext` is an internal construction token, not a public domain contract. Its
builder accepts one READY requirement plus the matching final `PlanningTrace`, `GuardedQuery`,
`ExecutionMetadata`, exact `ExecutionResult`, and PASSED `VerificationTrace`; an optional
successful `RepairTrace` must bind the same Run, replacement plan, PlannerContext, and final
verification identity.

The provider-facing `AnswerProposal v0.1` contains only a non-empty answer and unique positional
cell references. Its free-text numeric tokens are admitted only when the same value occurs in a
cited result cell; numbers from RequirementState or other context never provide answer authority.
Public HTTP responses are a discriminated union:

```text
clarification = session_id + run_id + question + RequirementState
result        = answer + exact data + assumption provenance + query evidence
                + coverage-bounded verification + synthesis mode
failure       = safe code + safe message + session_id + run_id + terminal Run status
```

Result rows preserve positional order. `Decimal` serializes as its exact base-10 string, dates and
datetimes as ISO strings, and finite JSON-native scalar values without implicit arithmetic or
renaming. Physical tables and SQL come from the final `GuardedQuery`; duration and row count come
from the exact final `ExecutionResult`; repair count and terminal state come from the durable Run.

Coverage is deterministic: `UNSUPPORTED` gaps are user-visible, `NOT_APPLICABLE` gaps are excluded
from both passed checks and the coverage denominator, and scope is explicitly
`COVERAGE_BOUNDED`. A result response cannot be built from failed verification or a non-completed
Run.

---

## 19. Internal M15 trace evidence

Trace is an internal observable-evidence record, not a public domain contract and not authority for
dialogue, retrieval, planning, admission, execution, verification, repair, or synthesis.

```python
class TraceEventDraft(BaseModel):
    id: str
    session_id: str
    run_id: str
    attempt: Literal[0, 1]
    stage: TraceStage
    event_type: TraceEventType
    schema_version: Literal["trace-event-v0.1"]
    payload: dict[str, JsonValue]
    payload_fingerprint: Sha256
    occurred_at: AwareDateTime

class TraceEvent(TraceEventDraft):
    sequence: PositiveInt
```

Persistence alone assigns the contiguous per-Run `sequence`. Event type mechanically determines
stage. Payloads are canonical JSON bounded to 64 KiB and revalidated against their SHA-256 after
reload. Each event type has a frozen top-level payload-key allowlist; recursive forbidden-field
policy additionally rejects raw/result rows, generic data envelopes, answer duplicates,
credentials, secrets, hidden reasoning, chain-of-thought, and scratchpad content before insertion.

Execution payloads retain bounded column names, row/byte counts, truncation, result/capability
fingerprints, and principal class but no cell values. Synthesis payloads bind the assistant Message,
prompt/mode, bounded cell references, and the hashed `AnswerProposal` without duplicating answer
text.

The completeness policy freezes four observable paths: clarification, direct success, terminal
failure, and one bounded repaired branch. Every trace begins with `RUN_RECEIVED` and a terminal Run
ends with exactly one `RUN_TERMINATED` whose status matches durable `Run.status`. A direct completed
Run contains dialogue, retrieval, planning, admission, execution, verification, and synthesis in
order at attempt 0. A repaired completion retains the failed attempt-0 prefix, one
`REPAIR_COMPLETED`, and a fresh planning-through-synthesis attempt-1 suffix. The trace repository
has append/list operations only; the runtime principal has no UPDATE or DELETE grant.

---

## 20. Internal M17 analytics-source and preflight evidence

M17 has one configuration-owned active source. The profile is identity and scope, never a
credential container:

```python
class AnalyticsSourceProfile(BaseModel):
    version: Literal["analytics-source-profile-v0.1"]
    source_id: str
    mode: Literal["SYNTHETIC", "EXTERNAL"]
    backend: Literal["mysql"]
    database: str
    allowed_tables: tuple[str, ...]
    catalog_workspace: str
    fingerprint: Sha256
```

Allowed tables are non-empty, unique, and canonically sorted. The fingerprint covers every field
except itself. It contains no host, port, username, password, connection string, or other secret.
The profile selects one local catalog workspace; it does not create a multi-source runtime.

The external preflight report is bounded operational evidence:

```python
class ExternalMySQLPreflightReport(BaseModel):
    version: Literal["external-mysql-preflight-v0.1"]
    source_profile_fingerprint: Sha256
    source_id: str
    backend: Literal["mysql"]
    database: str
    server_version: str
    allowed_table_count: int
    column_count: int
    foreign_key_count: int
    table_comment_coverage: float
    column_comment_coverage: float
```

It is produced only after `DATABASE()` exactly matches the profile and all allowed base tables are
visible through the configured analytics reader. Counts and coverage refer only to the allowed
surface. The report carries no table/column names, SQL, credentials, row values, or connection
endpoint. The same read-only metadata pass yields `GeneratedSchemaMetadata v0.1` for downstream
M6 assembly; the report does not become semantic authority.
