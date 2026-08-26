# Local Development Environment

**Version:** v0.1.0

## 1. Topology

Initial MVP topology:

```text
Host
├── Ollama :11434
├── Data Agent API
└── Docker/OrbStack
    └── MySQL 8.4
```

MySQL contains two logically isolated schemas:

- the configured analytics schema with the deterministic ten-table business world;
- the configured control schema with Session, Message, Run, and Artifact persistence.

They use separate runtime principals. The analytics reader cannot access control state, and the
control principal cannot access analytics tables.

Run the Python API on the host during the first implementation stage. Containerizing the application itself is optional after the functional loop is stable.

## 2. Ollama

Expected configurable endpoint:

```text
http://127.0.0.1:11434
```

Required capabilities:

- chat endpoint;
- embeddings endpoint;
- structured JSON/JSON Schema output from local chat API.

Do not hard-code model names.

Application startup runs fail-closed diagnostics against the configured endpoint and models.
Model requests use `OLLAMA_REQUEST_TIMEOUT_SECONDS`; embedding batches and response bodies are
bounded by `OLLAMA_MAX_EMBEDDING_BATCH` and `OLLAMA_MAX_RESPONSE_BYTES`.
The serial 21-case M9 planner evaluation uses the separate
`PLANNER_EVAL_REQUEST_TIMEOUT_SECONDS` bound (default 180 seconds per case) so complex bounded
multi-table proposals do not weaken the normal 60-second online request limit.

The deterministic quality suite uses transport doubles and does not require Ollama in CI. Run the
explicit host integration smoke with:

```bash
RUN_OLLAMA_INTEGRATION=1 uv run pytest tests/integration/test_ollama_adapter.py
```

M8 adds a real structured-dialogue smoke:

```bash
RUN_OLLAMA_INTEGRATION=1 uv run pytest tests/integration/test_dialogue_ollama.py
```

M9 adds a real bounded-planner smoke and a standalone no-execution evaluation:

```bash
RUN_OLLAMA_INTEGRATION=1 uv run pytest tests/integration/test_planning_ollama.py
uv run data-agent planner-eval
```

M10 adds a deterministic standalone SQL guard and MySQL JSON EXPLAIN evaluation. It uses the
accepted M9 proposal snapshot, does not call Ollama, and never submits the candidate as a normal
query. Before plain EXPLAIN, the Guard rejects unknown/stored/loadable-function shapes and admits
only the versioned EXPLAIN-safe analytics function surface:

```bash
task m10-eval
```

`MAX_SQL_CHARACTERS` bounds the pre-parse candidate size (default 64,000 characters).
`MAX_EXPLAIN_ESTIMATED_ROWS` bounds each MySQL JSON EXPLAIN table-access estimate (default
100,000 rows).

M11 adds a standalone deterministic runtime evaluation that uses only M10-issued capabilities and
the local MySQL world—never Ollama:

```bash
task m11-eval
```

`MAX_RESULT_ROWS` defaults to 1,000 and `MAX_RESULT_BYTES` defaults to 8 MiB. Runtime queries use a
dedicated reader connection with `MYSQL_QUERY_READ_TIMEOUT_SECONDS` (default 10 seconds), which
configuration validation requires to exceed `MAX_QUERY_TIME_MS` (default 5,000 milliseconds).
The evaluation writes metadata-only case evidence to `evals/reports/runtime-latest.json`.

M7 `task bootstrap` builds a bound embedding index and therefore requires the configured runtime.
The remote Delivery workflow supplies a deterministic CI-only Ollama HTTP stub for bootstrap
identity and index plumbing; substantive embedding quality evidence comes from the explicitly
reported host Ollama retrieval eval, not from stub vectors.

## 3. MySQL

Use an official/pinned MySQL 8.4 image.

`compose.yaml` should provide:

- database health check;
- persistent/dev volume or deterministic rebuild path;
- bootstrap admin credentials only for migration/seed setup;
- separate analytics read-only and control-plane runtime principals.

## 4. Environment variables

See root `.env.example`.

The application must validate configuration at startup and fail clearly when required settings are missing.

## 5. Bootstrap contract

`task bootstrap` should be idempotent enough for routine development and should:

1. verify required local commands;
2. verify Ollama is reachable;
3. verify configured models are available, or print an actionable error;
4. start MySQL;
5. wait for health;
6. apply analytics schema and versioned control-schema migrations;
7. seed deterministic business data;
8. create/verify the separate analytics and control runtime principals;
9. introspect database metadata;
10. merge generated metadata with curated semantics;
11. build lexical/embedding index;
12. run a smoke query and a small retrieval smoke test.

Model auto-pulling may be optional; do not surprise the user with large downloads unless explicitly documented.

## 6. Reset contract

`task reset` removes generated local DB/index state required to prove clean reproducibility, then allows `task bootstrap` to rebuild it.

Do not delete curated catalog files.

## 7. Model availability checks

Use Ollama's supported model-list/detail API or client behavior rather than assuming a configured model exists.

Errors should name the missing configured model.

## 8. Networking

Because the initial Python service runs on the host:

```text
Ollama → 127.0.0.1:11434
MySQL  → published localhost port
```

Avoid unnecessary container-to-host networking complexity in the first milestone.

## 9. Generated artifacts

Suggested ignored/generated paths:

```text
catalog/generated/
evals/reports/
.var/
```

Exact path choices are implementation details, but generated state must be reproducible.

## 10. Developer success criterion

A new developer/Codex session should be able to reach a working state from repository instructions with:

```bash
cp .env.example .env
task bootstrap
task quality
task eval
```

`task eval` runs the standalone retrieval, dialogue, planner, SQL-guard, and runtime evaluations. M10 writes
its machine-readable report under `evals/reports/`, binds SQLGlot/policy configuration and the
accepted M9 snapshot fingerprint, runs only Harness-owned JSON EXPLAIN, and does not execute normal
SQL. Plain EXPLAIN is protected by the pre-provider approved-function policy rather than assumed to
be inherently side-effect free.

M11 then executes only its own frozen M10-admitted runtime queries and may claim execution plus
returned database values, but not semantic correctness against the originating requirement.

apart from installing Ollama and the configured local models.
