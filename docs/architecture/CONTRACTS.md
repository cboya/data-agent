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

The LLM proposes the decision. The harness validates and applies it.
The model cannot write `RequirementState.status`; deterministic dialogue policy derives it after
merge. `ASK_CLARIFICATION` is accepted only when the merged state contains a blocking ambiguity,
and `READY` only when it contains none.

The Ollama boundary does not deserialize directly into the public decision. It first validates a
provider-facing `DialogueProposal v0.1` containing a mutation patch and an action-discriminated
`resolution`. ASK grammar requires at least one normalized blocking ambiguity; provider
grain/comparison enum values are then deterministically normalized into `ScalarPatch` operations.
Provider blocking ambiguity adds a required `subject_term` copied from the ambiguous surface
phrase; this attribution metadata is removed before the public `Ambiguity` is constructed. The
normalized `DialogueDecision` is revalidated before merge. A blocked scalar mutation becomes
`NO_CHANGE`. A metric/dimension blocker suppresses only an upsert with the same normalized
user-facing `term`, preserving unrelated explicit members of that collection. Collection removes
that cannot be safely attributed and a filter replacement paired with a filter blocker fail
closed instead of silently dropping facts.

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
validated SQL payload and digest, QueryPlan identity/reference, passed guard evidence, and accepted
EXPLAIN evidence. It is not a public domain contract or a replacement for `SQLGuardResult`.
Future M11 code consumes this capability rather than accepting arbitrary raw SQL.

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
result contract. It carries capability/policy identities, physical tables, database principal
class, bounds, timings, counts, truncation, and typed outcome, but never contains `rows`.

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
configured model name, immutable model digest, declared capabilities, and bounded descriptive
metadata. Ollama request/response DTOs remain inside the adapter.

The composition root must bind each runtime adapter to the corresponding startup fingerprint;
an adapter must not execute from an unbound mutable model tag. If a provider cannot execute a
digest-qualified reference, the provider adapter must revalidate the configured tag-to-digest
mapping immediately before every model request and fail closed with a typed identity-drift error
when the mapping no longer matches.
