# Conversational Data Agent Architecture

**Version:** v0.1.0
**Status:** Frozen MVP Baseline
**Architecture style:** Harness-centric, stateful, single-agent, read-only

## 1. System objective

The system accepts an incomplete or complete natural-language analytics request and returns a verified result from a local MySQL data world.

It must support this closed loop:

```text
User Intent
   ↓
Conversation / Clarification
   ↓
RequirementState
   ↓
Schema & Semantic Retrieval
   ↓
Query Planning
   ↓
Deterministic SQL Policy
   ↓
Read-only Execution
   ↓
Verification
   ↓
Answer + Evidence
```

Failure in planning, execution, or verification may cause a bounded repair/replan step. It must never cause an unbounded autonomous loop.

## 2. Architecture thesis

> The session remembers.
> The model reasons.
> The harness governs.
> The catalog provides semantics.
> The runtime executes.
> MySQL provides facts.
> Verification closes the loop.

The durable architecture is built around contracts, state, capabilities, execution evidence, and tests—not around a particular model.

## 3. Context

### Inputs

- user messages;
- prior `RequirementState`;
- curated catalog semantics;
- database metadata;
- relationship graph;
- execution feedback.

### External runtimes

- Ollama local chat model;
- Ollama local embedding model;
- Docker MySQL 8.4.

### Outputs

- clarification question; or
- answer + structured data + assumptions + evidence + verification status.

## 4. Component model

```text
┌──────────────────────────────────────────────────────────────┐
│                        Experience Layer                      │
│                 FastAPI / Conversation API                  │
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────┐
│                         Agent Harness                        │
│  session | state machine | context | bounded recovery       │
└───────────────┬──────────────────────────────┬───────────────┘
                │                              │
        ┌───────▼────────┐             ┌───────▼────────┐
        │ Session Store  │             │  Ollama Chat   │
        │ messages       │             │ reasoning only │
        │ requirement    │             └───────┬────────┘
        │ runs/artifacts │                     │
        └────────────────┘                     │
                                               ▼
                                      structured decisions
                                               │
┌──────────────────────────────────────────────▼───────────────┐
│                  Semantic Discovery Layer                    │
│ Catalog + lexical retrieval + embeddings + rerank + graph   │
└──────────────────────────────┬───────────────────────────────┘
                               │ relevant schema
                               ▼
                       ┌───────────────┐
                       │ Query Planner │
                       └───────┬───────┘
                               │ QueryPlan
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    Deterministic Boundary                    │
│ SQL AST guard | table scope | limits | EXPLAIN gate         │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
                       ┌───────────────┐
                       │ MySQL 8.4     │
                       │ SELECT only   │
                       └───────┬───────┘
                               │ ExecutionResult
                               ▼
                       ┌───────────────┐
                       │ Verification  │
                       └───────┬───────┘
                               │
                          pass │ fail
                               │
                        answer │ bounded repair
```

## 5. Core planes

### 5.1 Control plane

Owns:

- session lifecycle;
- run lifecycle;
- state machine;
- retry/repair limits;
- context assembly;
- policy routing;
- completion criteria.

The LLM must not own these concerns.

Durable control-plane state is stored separately from analytics data. The MVP may use the same
MySQL server, but it must use a distinct schema and runtime principal for sessions, messages,
runs, and artifacts. Semantic catalog discovery is scoped to the analytics schema and must not
introspect control-plane tables as business data.

### 5.2 Intelligence plane

Owns probabilistic tasks:

- natural-language requirement extraction;
- ambiguity reasoning;
- clarification wording;
- candidate reranking;
- query planning;
- bounded SQL repair;
- answer explanation.

### 5.3 Semantic plane

Owns:

- generated database metadata;
- curated table/column meanings;
- aliases;
- business rules;
- relationship graph;
- retrieval index.

### 5.4 Execution plane

Owns:

- SQL AST validation;
- query timeout;
- result cap;
- EXPLAIN;
- read-only MySQL execution.

### 5.5 Assurance plane

Owns:

- structural verification;
- semantic verification;
- empirical invariants;
- structured tracing;
- Golden Dataset evaluation.

## 6. Core domain objects

The stable objects are:

- `Session`
- `Message`
- `RequirementState`
- `DialogueDecision`
- `CatalogDocument`
- `Relationship`
- `RetrievalResult`
- `QueryPlan`
- `ExecutionResult`
- `VerificationResult`
- `Artifact`
- `Run`

Exact contracts are defined in `docs/architecture/CONTRACTS.md`.

## 7. Session and memory model

The term “memory” is deliberately split into four things:

```text
Conversation History ≠ Requirement State ≠ Artifacts ≠ Domain Knowledge
```

### Conversation History

Append-only record of what user and assistant actually said.

### Requirement State

Canonical structured representation of the current request.

### Artifacts

Work products such as retrieval result, query plan, SQL, EXPLAIN summary, execution metadata, verification result.

### Domain Knowledge

Curated catalog semantics. It is governed repository data and is never automatically promoted from a user's conversation.

## 8. Requirement lifecycle

```text
RECEIVED (new Run for one inbound user message)
   ↓
UNDERSTANDING
   ↓
MERGE_REQUIREMENT
   ↓
CHECK_AMBIGUITY
   ├── blocking → CLARIFYING (terminal for this Run)
   └── ready    → RETRIEVING
                     ↓
                  PLANNING
                     ↓
                 VALIDATING
                     ↓
                  EXPLAIN
                     ↓
                  EXECUTING
                     ↓
                  VERIFYING
                    / \
                  pass fail
                   │    └─ bounded repair/replan → VALIDATING
                   ↓
               SYNTHESIZING
                   ↓
               COMPLETED
```

`Session` owns conversation continuity. A `Run` owns one processing lifecycle for one inbound
user message. When a Run ends in `CLARIFYING`, the Session remains active; a later user reply
creates a new Run rather than resuming the terminal Run.

The deterministic M3 Run transition graph is:

```text
RECEIVED       → UNDERSTANDING
UNDERSTANDING  → CLARIFYING | RETRIEVING | FAILED
RETRIEVING     → PLANNING | FAILED
PLANNING       → VALIDATING | FAILED
VALIDATING     → EXECUTING | POLICY_DENIED | QUERY_TOO_EXPENSIVE | FAILED
EXECUTING      → VERIFYING | VALIDATING | REPAIR_EXHAUSTED | FAILED
VERIFYING      → SYNTHESIZING | VALIDATING | REPAIR_EXHAUSTED | FAILED
SYNTHESIZING   → COMPLETED | FAILED
```

`CLARIFYING`, `COMPLETED`, `POLICY_DENIED`, `QUERY_TOO_EXPENSIVE`, `REPAIR_EXHAUSTED`,
and `FAILED` are terminal and have no outgoing edges. The repair edges are representational in
M3; bounded repair behavior remains deferred to M13.

Terminal/non-success states include:

- `FAILED`
- `POLICY_DENIED`
- `QUERY_TOO_EXPENSIVE`
- `REPAIR_EXHAUSTED`

## 9. Clarification rule

The agent asks a question only if an unresolved ambiguity can materially change the query or result.

Examples:

- “最近销售情况” → blocking metric ambiguity; clarify.
- “昨天订单量” with a catalog-defined order-count semantic → do not clarify.
- optional sort order absent → do not clarify; choose a transparent default.

All non-blocking assumptions that affect interpretation must be returned to the user.

## 10. Retrieval architecture

The planner never receives the complete database schema by default.

```text
RequirementState
   ↓
Retrieval Query
   ├── lexical search
   └── embedding search
          ↓
        merge
          ↓
      candidate top-N
          ↓
       reranking
          ↓
       seed tables
          ↓
 relationship expansion
          ↓
   relevant schema slice
```

MVP uses no external vector database. Catalog embeddings are small enough to store locally and search in-process.

The vector index and lexical index are replaceable adapters.

## 11. Query planning

`QueryPlan` is the minimal intermediate representation for the MVP.

The planner sees a bounded semantic data world, never the database. Its complete schema authority
is the final accepted M7 `RetrievalResult`: exactly the corresponding `CatalogDocument` values and
only the relationships already present in that result. It receives no full catalog,
`information_schema`, raw generated foreign keys, database credentials, or execution capability.
Only a READY `RequirementState` may enter planning.

The system prompt defines provider-neutral planning discipline only. Concrete business meanings,
physical table/column mappings, metric formulas, status rules, time semantics, and relationship
facts come exclusively from the supplied M6 semantic catalog slice. The prompt must not duplicate
those governed facts as a second, higher-priority semantic authority.

It describes:

- intent;
- selected tables;
- assumptions;
- generated SQL;
- expected result shape.

It is **not** intended to become a SQL AST clone. Future versions may introduce a richer semantic `DataRequest IR` before query lowering.

M9 treats generated SQL as an opaque, untrusted proposal. It deterministically enforces declared
plan-table scope; M10 owns SQL parsing, referenced-table extraction, and read-only policy.

## 12. Execution invariants

Before SQL reaches MySQL:

1. parse as MySQL SQL;
2. require a single query statement;
3. allow only read-only query forms;
4. reject prohibited constructs/functions;
5. extract referenced tables;
6. enforce table subset invariant;
7. enforce configured query limits;
8. run EXPLAIN and apply conservative cost policy;
9. execute via a MySQL account with only required read privileges.

Raw SQL is data; `GuardedQuery` is capability. M10 binds the exact guarded payload and SHA-256
identity, proves a conservative EXPLAIN-safe analytics function surface, then permits only
Harness-owned `EXPLAIN FORMAT=JSON`. Unknown/stored/loadable-function shapes fail closed before the
provider because plain MySQL EXPLAIN may evaluate a stored function in optimizer subquery paths.
M11 must consume that immutable capability instead of accepting a new arbitrary SQL string.
`EXPLAIN ANALYZE` is outside M10 because it executes the statement.

Generated SQL is never trusted merely because an LLM produced it.

## 13. Verification

Verification is ordered:

1. **Structural** — execution and shape correctness.
2. **Semantic** — requirement/metric/time/grain/table consistency.
3. **Empirical** — deterministic numeric/business invariants where available.

An LLM-based qualitative check may assist later, but it is not the primary correctness authority.

## 14. Trace model

Every run must make observable:

- message;
- requirement before/patch/after;
- retrieval query and candidates;
- final retrieved schema;
- query plan;
- SQL guard decision;
- EXPLAIN summary;
- execution metadata;
- repair count;
- verification;
- final answer.

Raw large result sets and secrets must not be indiscriminately logged.

## 15. MVP non-goals

The MVP explicitly excludes:

- multi-agent coordination;
- database writes;
- production database access;
- arbitrary code/shell execution;
- full enterprise metric-store DSL;
- automatic long-term user memory;
- automatic promotion of chat statements into catalog truth;
- external vector database;
- MCP/A2A as domain architecture;
- scheduled autonomous jobs.

## 16. Evolution boundaries

Expected evolution:

```text
MVP
  requirement state
  hybrid catalog retrieval
  guarded SQL
  verification
      ↓
v1
  richer semantic DataRequest IR
  metric/dimension registry
  charts
      ↓
v2
  controlled Python/DataFrame runtime
  analysis skills
  long-running tasks
      ↓
v3
  multiple data sources
  governed actions
  specialist agents where independently justified
```

Each evolution must preserve the core rule:

> Stable interfaces, replaceable intelligence.
