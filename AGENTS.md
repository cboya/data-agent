# AGENTS.md

## Mission

Implement and maintain the local conversational Data Agent described by this repository.

The system converts a user's natural-language analytics request into a safe, verified MySQL result through a stateful single-agent harness.

## Start here

Before modifying code, read:

- `ARCHITECTURE.md`
- `docs/product/MVP.md`
- `docs/architecture/DECISIONS.md`
- `docs/architecture/CONTRACTS.md`
- `docs/architecture/SECURITY.md`
- the active file under `docs/exec-plans/`

Read specialized docs only when working in that area:

- LLM behavior → `docs/architecture/LLM_INTERACTIONS.md`
- catalog/retrieval → `docs/architecture/CATALOG_SPEC.md`
- evaluation → `docs/architecture/EVAL_SPEC.md`
- local environment → `docs/architecture/LOCAL_DEV.md`

## Core laws

Do not violate these laws:

1. **Model ≠ Agent.** The model reasons; application code controls state and execution.
2. **Session owns continuity.** Durable state lives outside the model context.
3. **RequirementState is authoritative.** Do not infer current requirements solely from raw chat history.
4. **Context is disposable.** Build task-specific context; do not replay the entire conversation by default.
5. **Clarify only blocking ambiguity.**
6. **Retrieve before planning.** Do not expose the full database schema to the planner.
7. **Generated SQL is untrusted input.**
8. **LLM never receives database credentials.**
9. **Database access is read-only by privilege, not by prompt.**
10. **SQL must pass deterministic guard checks before execution.**
11. **Tables(SQL) ⊆ QueryPlan.tables ⊆ retrieved/authorized tables.**
12. **MySQL execution results are the source of numerical truth.**
13. **Verification precedes final answer synthesis.**
14. **Session knowledge does not automatically become organization-wide semantic knowledge.**
15. **Trace and eval are part of the product, not later observability add-ons.**

## Frozen technology boundaries

- Python application.
- FastAPI HTTP boundary.
- Ollama local runtime for chat and embeddings.
- MySQL 8.4 in Docker for the deterministic test world.
- SQLGlot or an equivalently capable AST parser for deterministic SQL inspection.
- Pydantic models or equivalent typed Python validation at boundaries.
- No external vector database for the MVP.
- No multi-agent framework.
- No MCP/A2A in the core.
- No generic shell/Python tool exposed to the runtime Data Agent.
- No database writes by the runtime Data Agent.

Library choices inside these boundaries may be changed if the active execution plan records why.

## Repository knowledge is the source of truth

Do not depend on context that exists only in chat, issue comments, or your current reasoning.

If an implementation decision changes a stable contract:

1. update the relevant repository document;
2. update or add an executable test;
3. record the decision in the active execution plan;
4. only then change implementation code.

## Generated vs curated data

Anything under a future path named `generated/` is machine-produced and must not be hand-maintained.

Curated semantics belong under:

```text
catalog/semantic/
```

Database introspection output belongs under:

```text
catalog/generated/
```

Do not mix them.

## Implementation workflow

For each execution-plan milestone:

1. inspect current repository state;
2. restate the exact milestone acceptance criteria;
3. implement the smallest coherent change;
4. add/adjust tests;
5. run focused tests;
6. run `task quality`;
7. update the execution-plan progress/decision log;
8. only then proceed to the next milestone.

Do not implement later phases opportunistically unless required to keep a boundary clean.

## Required validation

Before marking a milestone complete, `task quality` must pass.

Before marking the MVP complete:

```bash
task bootstrap
task quality
task eval
```

must all pass from a clean local state.

## Security behavior

Fail closed.

If SQL parsing, authorization, table extraction, EXPLAIN inspection, timeout enforcement, or result validation cannot be performed reliably, do not execute the query.

Never log:

- database passwords;
- model secrets;
- raw credentials;
- unbounded result sets;
- unnecessary sensitive row-level values.

## Testing philosophy

Prefer tests of invariants over tests of implementation details.

Examples of required invariant tests:

- `SELECT` accepted; `DELETE`, `UPDATE`, DDL rejected.
- multi-statement SQL rejected.
- `INTO OUTFILE` rejected.
- query referencing a non-plan table rejected.
- query timeout enforced.
- result cap enforced.
- deterministic seed rebuild produces the same fixture facts.
- a blocking ambiguity triggers clarification.
- a resolved RequirementState does not ask an unnecessary clarification.
- a missing required table in retrieval is visible to the eval harness.

## Scope discipline

Do not add the following in the MVP unless the architecture documents are explicitly revised:

- multi-agent orchestration;
- long-term personal memory;
- automatic semantic-learning from user conversations;
- production database connectivity;
- DML/DDL;
- generic code execution;
- scheduled autonomous jobs;
- external vector database;
- MCP/A2A;
- full enterprise metric-store DSL.

## When uncertain

First consult `docs/architecture/OPEN_QUESTIONS.md`.

If the question is listed there, choose an implementation and record the choice in the active execution plan.

If the question changes a frozen architectural boundary, do not silently decide it. Document the conflict and stop that branch of implementation.
