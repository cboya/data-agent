# Product Specification — Conversational Data Agent MVP

**Version:** v0.1.0
**Status:** Frozen MVP scope

## 1. User problem

A user knows the business question they want answered but does not know:

- which MySQL table contains the data;
- what columns or joins are required;
- how business terms map to database semantics;
- how to write SQL.

The user may also express an incomplete request that needs clarification.

## 2. Product promise

The user can converse naturally with the system and receive:

1. a clarification question when a genuinely blocking ambiguity exists; or
2. a verified data answer backed by executed SQL and evidence.

## 3. Primary user journey

Example:

```text
User: 看一下最近销售情况。

Agent: 你希望看的销售指标是实际支付金额、订单量还是 GMV？

User: 实际支付金额。

Agent: 需要按什么时间范围看？

User: 最近30天，按天。

Agent:
最近30天实际支付金额为……
[table]
Evidence: fact_order, paid_at, paid_amount
```

The system must preserve previously resolved information across turns.

## 4. Functional requirements

### FR-001 Session creation

The system can create a durable conversation session.

### FR-002 Message persistence

Every user/assistant conversational message is append-only persisted.

### FR-003 Structured requirement state

The system maintains canonical `RequirementState` independently of raw chat history.

### FR-004 Requirement patching

Each user turn may update part of the requirement without regenerating the entire state from scratch.

### FR-005 Blocking ambiguity detection

The system distinguishes blocking semantic ambiguity from optional/unimportant missing information.

### FR-006 Clarification

When blocking ambiguity exists, the system asks one concise, actionable clarification question.

Prefer asking the highest-impact unresolved ambiguity first.

### FR-007 Semantic schema retrieval

Once the requirement is executable, the system retrieves only relevant schema/catalog context.

### FR-008 Relationship-aware expansion

Retrieval may add relationship-neighbor tables required to form a valid query path.

### FR-009 Structured query planning

The planner returns a validated structured `QueryPlan`.

### FR-010 SQL deterministic validation

No generated SQL executes before the SQL guard passes.

### FR-011 Read-only execution

Runtime database access is read-only by MySQL privilege.

### FR-012 Bounded repair

A database/planning failure may be repaired a configured, small number of times. Default MVP target: one repair attempt.

### FR-013 Verification

Successful execution is necessary but not sufficient. The result must pass minimum verification before synthesis.

### FR-014 Answer synthesis

The final answer uses only execution evidence for numerical/data facts.

### FR-015 Evidence

A successful response includes machine-readable evidence:

- tables;
- SQL;
- query duration;
- row count;
- assumptions;
- verification status.

### FR-016 Trace

Every run has a stable `run_id` and structured trace.

## 5. Conversation behavior

### Ask when

Ask a clarification when different interpretations would materially change:

- metric;
- cohort/population;
- time definition;
- required filter;
- result grain.

### Do not ask when

Do not ask only because:

- sort order is absent;
- a harmless presentation detail is missing;
- a catalog-approved default exists;
- the model is generically “not 100% confident.”

### Assumptions

For non-blocking ambiguity:

- choose the safest/most conventional catalog-supported interpretation;
- record it in `RequirementState.assumptions`;
- expose it with the result when material.

## 6. Initial synthetic business domain

The local Docker MySQL test world should contain enough complexity to exercise the architecture:

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

It must intentionally contain common analytical traps:

- `total_amount` vs `paid_amount`;
- `created_at` vs `paid_at` vs `completed_at`;
- multiple payment attempts per order;
- refunds affecting net revenue;
- one-to-many join fan-out;
- dimension joins for region/channel/category.

## 7. API behavior

Suggested boundary:

```text
POST /sessions
POST /sessions/{session_id}/messages
GET  /sessions/{session_id}
GET  /runs/{run_id}
```

### Clarification response

```json
{
  "type": "clarification",
  "session_id": "sess_...",
  "message": "你希望查看实际支付金额、订单量还是 GMV？",
  "requirement_status": "CLARIFYING"
}
```

### Result response

```json
{
  "type": "result",
  "session_id": "sess_...",
  "run_id": "run_...",
  "answer": "...",
  "data": {
    "columns": [],
    "rows": []
  },
  "assumptions": [],
  "evidence": {
    "tables": [],
    "sql": "...",
    "query_duration_ms": 0,
    "row_count": 0
  },
  "verification": {
    "status": "PASSED"
  }
}
```

The exact HTTP envelope may evolve, but the domain payload semantics must remain consistent with `CONTRACTS.md`.

## 8. UX principles

- Do not expose internal chain-of-thought.
- Do expose assumptions, evidence, and validation status.
- Do not pretend an ambiguous question has a precise answer.
- Do not ask avoidable questions.
- Keep clarification questions short.
- Prefer returning useful table data alongside the natural-language summary.
- If the result is insufficient, say so rather than inventing a conclusion.

## 9. MVP failure behavior

Return a clear safe error for:

- policy rejection;
- query too expensive;
- unrecoverable SQL/planning failure;
- no relevant schema found;
- verification failure;
- runtime unavailable.

Never fall back to “best effort fabricated data.”

## 10. Product Definition of Done

The MVP is done only when:

- a clean local environment can be rebuilt deterministically;
- multi-turn requirement clarification works;
- relevant tables can be found without full-schema prompting;
- guarded SQL can execute read-only;
- representative database errors can be repaired within the bound;
- results are verified;
- Golden Dataset evals can run automatically;
- all security invariant tests pass;
- `task bootstrap`, `task quality`, and `task eval` pass.
