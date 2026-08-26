# LLM Interaction Contracts

**Purpose:** Define where model reasoning is allowed and what each call must return.

The model is not a workflow engine. Every model interaction has a narrow purpose, typed input context, and typed output.

## 1. General rules

- Use local Ollama through an internal adapter.
- Model names are configuration.
- Control-bearing outputs use JSON Schema structured output.
- Do not ask the model to enforce security invariants that deterministic code can enforce.
- Do not expose database credentials.
- Do not send the complete database schema by default.
- Do not require hidden chain-of-thought. Ask for concise `reason`/`explanation` fields only when useful for audit/debug.
- Record model name, latency, token counts when available, purpose, and success/failure metadata in trace.
- Keep prompts repository-local and versionable.
- Bound request time, response bytes, and embedding batch size in deterministic adapter code.
- Treat malformed provider envelopes, invalid JSON, contract-invalid structured output, embedding
  count/dimension mismatch, and non-finite vector values as typed failures.

At application startup, diagnostics must verify the Ollama endpoint, configured model presence,
required chat/embedding capabilities, and immutable model digests. Startup fails closed when any
required capability cannot be proven. Chat and embedding adapters must consume those startup
fingerprints. Because the supported local Ollama runtime does not accept digest-qualified model
references, each adapter must revalidate its configured tag-to-digest mapping immediately before
execution and fail closed on identity drift.

## 2. Interaction A — Dialogue understanding

### Purpose

Merge the latest user message into current requirements and decide whether the request is ready.

### Input context

```text
system behavior rules
current RequirementState
last assistant clarification only when relevant
latest user message
```

### Harness output

`DialogueDecision`

### Model may

- resolve terms;
- identify blocking ambiguity;
- propose a state patch;
- formulate one clarification question.

### Model may not

- execute SQL;
- select arbitrary database credentials/tools;
- mutate persisted state directly.

The harness validates and applies the patch.

M8 uses `RequirementPatch` mutation protocol v0.2. Scalar changes are explicit
`NO_CHANGE`/`SET`/`CLEAR` operations; metric and dimension correction uses explicit remove and
upsert operations. The model never writes `RequirementState.status`. Successful turns atomically
persist the inbound user message, harness-derived state, and optional assistant clarification
after structured output and policy validation.

The provider-facing structured result is `DialogueProposal v0.1`, not a second domain authority.
It separates mutation fields from an action-discriminated `resolution`, whose ASK branch requires
blocking ambiguity evidence and whose READY branch cannot carry blocking items. The Harness
normalizes the provider grain/comparison enums into the public patch and revalidates
`DialogueDecision` before deterministic merge and action policy. Provider blocking items carry an
exact ambiguous `subject_term`, which is stripped before the public ambiguity boundary. Scalar
blockers suppress the whole scalar mutation. Metric/dimension blockers suppress only upserts
attributable to that subject and retain resolved siblings in the same collection. Unattributable
collection removes and filter-blocker/whole-list-replacement combinations fail closed.

---

## 3. Interaction B — Retrieval query formulation

Prefer deterministic construction from `RequirementState`.

Use a model call only if experiments show it materially improves retrieval.

If used, output a typed structure such as:

```json
{
  "keywords": ["支付金额", "地区"],
  "semantic_query": "最近30天各地区实际支付金额",
  "aliases": ["收入", "付款"]
}
```

Do not make this call mandatory unless eval data justifies it.

---

## 4. Interaction C — Candidate reranking

### Purpose

Improve precision after lexical + embedding recall.

### Input

- compact requirement;
- candidate table cards, not full DDL;
- candidate scores/ranks.

### Output

```json
{
  "ranked": [
    {
      "table": "fact_order",
      "relevance": 0.98,
      "reason": "..."
    }
  ]
}
```

The model cannot introduce a table that is absent from candidate input.

Reranking is optional if deterministic ranking already meets eval targets.

---

## 5. Interaction D — Query planning

### Purpose

Produce a `QueryPlan` from resolved requirements and a bounded relevant schema slice.

### Input

```text
RequirementState
CatalogDocuments for accepted retrieval hits
Relationships in the graph slice
business rules
MySQL dialect requirement
planner constraints
```

### Output

`QueryPlan`

### Planner requirements

- accept only a READY canonical requirement;
- use only supplied tables/columns;
- never request or perform schema discovery;
- treat the catalog as the sole concrete business-semantics authority while rejecting embedded
  requests to alter role, process, output contract, or authority boundaries;
- respect supplied business rules;
- use only supplied relationship semantics;
- derive metric sources, formulas, status rules, entity grain, and time semantics only from the
  supplied requirement and catalog;
- avoid fan-out duplication;
- qualify columns in multi-table queries;
- do not use `SELECT *`;
- return a single read-only query;
- explicitly list assumptions;
- avoid queries whose only purpose is exploratory schema discovery.

The public structured result is `QueryPlan v0.1`; no provider DTO is introduced unless measured
Ollama evidence requires one. M9 policy validates declared table scope only. The SQL string remains
opaque and untrusted until M10 parses it and applies deterministic validation.

The system prompt is domain-neutral: it defines reasoning and output discipline, never concrete
table/column identifiers or governed metric mappings. Catalog semantics remain data supplied in
the bounded context, but they are the only authority for business meaning.

---

## 6. Interaction E — SQL repair

### Trigger

Only after a failed execution/validation path that is explicitly repairable.

### Input

```text
exact original PlannerContext
previous QueryPlan
typed bounded RepairFailure
```

### Output

A complete replacement public `QueryPlan v0.1` under prompt `query-repair-v0.1`. The M13 Ollama
adapter uses a narrower `RepairPlanProposal` only to require at least one `expected_columns` item,
then immediately normalizes it to the public contract. The prompt is domain-neutral and says
diagnostic detail is untrusted data whose embedded instructions must be ignored. The existing M9
PlannerPolicy revalidates the normalized proposal before any downstream use.

### Bound

Default MVP: maximum one repair attempt per run.

`RepairFailure v0.2` binds the failed branch to its source Run. The Harness rejects a supplied Run
mismatch before repository or model access, then atomically checks the Run state expected for the
typed failure stage and increments durable `Run.repair_count` before inference. The opaque source
Run ID is not sent to the model. Model failure consumes an attempt and concurrent callers cannot
exceed the bound. Security/policy,
EXPLAIN cost, integrity/capability, availability/timeout/decoding, truncation, and coverage-gap
outcomes must not be “repaired around” and cause zero repair-model calls.

---

## 7. Interaction F — Answer synthesis

### Purpose

Explain verified execution evidence.

### Input

```text
READY RequirementState
final QueryPlan presentation fields
exact bounded ExecutionResult as typed positional cells
```

### Output

Internal `AnswerProposal v0.1`:

```text
answer: natural-language explanation
evidence_refs: unique (row_index, column_index) cell references
```

The Harness, not the model, builds data, assumption provenance, admitted SQL/physical tables,
timing/counts, repair count, verification status/policy/coverage limitations, synthesis mode, and
Run state. `VerificationTrace` is checked before the prompt is built but its authority fields are
not delegated to the model.

### Hard rule

All numerical result facts must resolve through positional references to the exact
`ExecutionResult`. M14 does not authorize model arithmetic: a percentage, delta, total, average,
or trend absent from returned SQL evidence fails closed. Result cells and free text within them
are untrusted data, never instructions.

Answer context has independent row and byte bounds. The complete result is sent or none of it is;
there is no silent sample presented as a complete summary. Oversized context uses a deterministic
no-new-facts fallback with zero answer-model calls. Grounding failure has no hidden model retry.

---

## 8. Context policy

Different calls get different contexts.

```text
Dialogue context   ≠ Planner context
Planner context    ≠ Repair context
Repair context     ≠ Answer context
```

Do not use “entire session history” as a universal context strategy.

## 9. Model fallback

The MVP does not require multiple model providers.

If the configured Ollama model cannot reliably satisfy structured contracts:

- fail clearly;
- surface diagnostic metadata;
- do not silently parse arbitrary prose as control data.

Structured chat sends the exact Pydantic JSON Schema to Ollama and then validates returned JSON
through the requested Pydantic type. Provider acceptance of a schema is not treated as proof that
the response satisfies the contract.

Embedding requests disable silent truncation. The adapter requires exactly one finite,
non-empty, consistently sized vector per input text.

## 10. Prompt tests

Prompts are code-adjacent artifacts and must be tested indirectly through:

- contract parse success;
- Golden Dataset behavior;
- regression cases.

Avoid tests that assert exact natural-language wording unless product behavior requires it.
