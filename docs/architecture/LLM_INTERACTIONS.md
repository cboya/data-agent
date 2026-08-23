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

## 2. Interaction A — Dialogue understanding

### Purpose

Merge the latest user message into current requirements and decide whether the request is ready.

### Input context

```text
system behavior rules
current RequirementState
small relevant recent-message window if needed
latest user message
```

### Output

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

- use only supplied tables/columns;
- respect supplied business rules;
- use correct time semantics;
- avoid fan-out duplication;
- return a single read-only query;
- explicitly list assumptions;
- avoid queries whose only purpose is exploratory schema discovery.

The SQL still remains untrusted until deterministic validation passes.

---

## 6. Interaction E — SQL repair

### Trigger

Only after a failed execution/validation path that is explicitly repairable.

### Input

```text
RequirementState
same relevant schema slice
previous QueryPlan
structured database/guard error
```

### Output

A replacement `QueryPlan` or dedicated typed repair contract.

### Bound

Default MVP: maximum one repair attempt per run.

Security/policy rejections must not be “repaired around.”

---

## 7. Interaction F — Answer synthesis

### Purpose

Explain verified execution evidence.

### Input

```text
RequirementState
ExecutionResult (bounded)
VerificationResult
SQL/evidence metadata
assumptions
```

### Output

Natural-language answer only, plus optional typed presentation hints if introduced later.

### Hard rule

All numerical/data facts must be grounded in `ExecutionResult`.

If evidence is insufficient, explicitly state insufficiency.

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

## 10. Prompt tests

Prompts are code-adjacent artifacts and must be tested indirectly through:

- contract parse success;
- Golden Dataset behavior;
- regression cases.

Avoid tests that assert exact natural-language wording unless product behavior requires it.
