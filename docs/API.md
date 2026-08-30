# Data Agent HTTP API

**API version:** `0.1.0`  
**Protocol:** HTTP + UTF-8 JSON  
**Default base URL:** `http://127.0.0.1:8000`  
**Product status:** Architecture/Harness validated; Product NL2SQL behavioral verdict rejected

This document describes the public HTTP surface implemented by `src/data_agent/api.py`. The
generated OpenAPI document remains the machine-readable schema authority for a running instance:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

## 1. Start the API

Prepare the configured model runtime, MySQL, catalog, and retrieval index before starting the
server:

```bash
cp .env.example .env
task bootstrap
task dev
```

`task dev` starts the FastAPI service on `APP_HOST` and `APP_PORT`, which default to
`127.0.0.1:8000`. Startup fails closed when the configured model identity, catalog, retrieval
index, or required persistence/runtime dependency cannot be bound safely. The API does not start
Ollama; Ollama must already be running when it is the selected provider.

See [`architecture/LOCAL_DEV.md`](architecture/LOCAL_DEV.md) for complete local, remote-model, and
external-MySQL configuration. Windows users should also follow [`WINDOWS.md`](WINDOWS.md).

## 2. API conventions

### 2.1 Media type

Requests with a body use:

```http
Content-Type: application/json
```

Responses are JSON. Unknown request fields are rejected.

### 2.2 Authentication and network exposure

The MVP HTTP boundary does not implement authentication, authorization, tenant identity, CORS
policy, or rate limiting. It binds to localhost by default and must not be exposed directly to an
untrusted network. A deployment that changes `APP_HOST` must place an authenticated, rate-limited
gateway in front of it.

Model and database credentials are server-side configuration. They never belong in an API
request.

### 2.3 IDs and timestamps

- IDs are opaque strings. Current IDs use forms such as `session_<hex>` and `run_<hex>`, but
  clients must not parse their contents.
- Timestamps are timezone-aware ISO-8601 strings.
- Session `revision` is persistence metadata and increases after successful requirement updates.
  It is informational in v0.1; the API has no client-supplied revision or `If-Match` header.

### 2.4 Exact values

Result rows are positional arrays matching `data.columns`. A result cell is one of:

```text
string | boolean | integer | finite number | null
```

MySQL `DECIMAL` values are serialized as base-10 strings to avoid binary floating-point loss.
Dates and datetimes are serialized as ISO strings. Consumers should preserve these strings until
they deliberately parse them with the required precision and timezone rules.

### 2.5 Synchronous processing

`POST /sessions/{session_id}/messages` is synchronous. One request can perform dialogue,
retrieval, model planning, SQL admission, MySQL `EXPLAIN`, read-only execution, verification,
bounded repair, and answer synthesis before returning.

The configured model timeout applies to an individual model call, not necessarily to the whole
HTTP request. Clients should use an appropriate end-to-end timeout. The API currently provides no
streaming, Server-Sent Events, webhook, or asynchronous job endpoint.

### 2.6 Idempotency and ordering

Message submission has no idempotency key. Retrying a completed or uncertain
`POST /sessions/{session_id}/messages` can create another durable user message and Run. Clients
should not retry it automatically unless they have independently determined that the original
request was never accepted.

Send messages to a given Session serially. Concurrent updates can conflict with the Session's
internal optimistic-concurrency boundary.

### 2.7 HTTP status versus domain outcome

A successfully processed message returns HTTP `200` for all three typed domain envelopes:

- `type = clarification`
- `type = result`
- `type = failure`

Therefore, HTTP `200` does not by itself mean the analytical request succeeded. Clients must first
switch on the top-level `type` discriminator.

## 3. Endpoint summary

| Method | Path | Success | Purpose |
| --- | --- | ---: | --- |
| `GET` | `/health` | `200` | Process liveness after successful application startup |
| `POST` | `/sessions` | `201` | Create a durable conversation Session |
| `GET` | `/sessions/{session_id}` | `200` | Read current Session and authoritative requirement state |
| `POST` | `/sessions/{session_id}/messages` | `200` | Submit one user turn and synchronously process one Run |
| `GET` | `/runs/{run_id}` | `200` | Read durable Run lifecycle status |

There are no public list, delete, message-history, trace, artifact, raw-SQL execution, or database
write endpoints in v0.1.

## 4. Health

### `GET /health`

Returns process liveness after the FastAPI lifespan has started successfully.

```bash
curl http://127.0.0.1:8000/health
```

Response — `200 OK`:

```json
{
  "status": "ok"
}
```

This endpoint does not run a fresh model, catalog, or MySQL probe on every request. Model-runtime
identity diagnostics and application composition occur at startup.

## 5. Sessions

### `POST /sessions`

Creates an empty durable Session. The request has no body and does not invoke a model.

```bash
curl -X POST http://127.0.0.1:8000/sessions
```

Response — `201 Created`:

```json
{
  "id": "session_0123456789abcdef0123456789abcdef",
  "status": "ACTIVE",
  "requirement": {
    "version": "v0.1",
    "goal": null,
    "metrics": [],
    "dimensions": [],
    "filters": [],
    "time_range": null,
    "grain": null,
    "comparison": null,
    "sort": null,
    "limit": null,
    "confirmed_terms": {},
    "assumptions": [],
    "unresolved": [],
    "status": "INCOMPLETE"
  },
  "revision": 0,
  "created_at": "2026-08-30T10:00:00Z",
  "updated_at": "2026-08-30T10:00:00Z"
}
```

#### Session fields

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Opaque Session ID |
| `status` | enum | `ACTIVE`, `COMPLETED`, or `FAILED` |
| `requirement` | object | Current authoritative `RequirementState v0.1` |
| `revision` | integer ≥ 0 | Persistence revision |
| `created_at` | datetime | Creation time |
| `updated_at` | datetime | Last durable Session update |

### `GET /sessions/{session_id}`

Returns the current durable Session projection. It does not invoke a model.

```bash
curl http://127.0.0.1:8000/sessions/session_0123456789abcdef0123456789abcdef
```

Response — `200 OK`: the same `SessionView` shape returned by `POST /sessions`.

Unknown Session — `404 Not Found`:

```json
{
  "detail": {
    "code": "NOT_FOUND",
    "message": "Session does not exist"
  }
}
```

### RequirementState projection

The `requirement` object is server-owned canonical conversational state:

| Field | Type | Meaning |
| --- | --- | --- |
| `version` | `"v0.1"` | Contract version |
| `goal` | string or null | Current analytical goal |
| `metrics` | array | Requested metrics and their resolution status |
| `dimensions` | array | Requested dimensions and their resolution status |
| `filters` | array | Structured filters |
| `time_range` | object or null | Relative/absolute time scope |
| `grain` | string or null | Requested output grain |
| `comparison` | string or null | Requested comparison |
| `sort` | string or null | Sort requirement |
| `limit` | positive integer or null | Requested result limit |
| `confirmed_terms` | object | Terms explicitly resolved in the Session |
| `assumptions` | string array | Non-blocking assumptions |
| `unresolved` | array | Remaining ambiguity evidence |
| `status` | enum | `INCOMPLETE`, `CLARIFYING`, `READY`, `EXECUTING`, `COMPLETED`, or `FAILED` |

Clients cannot write this object directly. It changes only through submitted user messages and
Harness-controlled requirement merging.

## 6. Conversation messages

### `POST /sessions/{session_id}/messages`

Submits exactly one user message and creates one bounded Run.

Request body:

```json
{
  "content": "请按天统计最近30天实际支付金额"
}
```

Validation rules:

- `content` is required;
- length is 1–20,000 characters;
- whitespace-only content is rejected;
- unknown properties are rejected.

Example:

```bash
curl -X POST \
  http://127.0.0.1:8000/sessions/session_0123456789abcdef0123456789abcdef/messages \
  -H 'Content-Type: application/json' \
  -d '{"content":"请按天统计最近30天实际支付金额"}'
```

The response is the following discriminated union.

### 6.1 Clarification response

Returned when a blocking ambiguity remains. The Run ends in `CLARIFYING`; the Session remains
available, and the next user reply creates a new Run in the same Session.

Response — `200 OK`:

```json
{
  "type": "clarification",
  "session_id": "session_0123456789abcdef0123456789abcdef",
  "run_id": "run_0123456789abcdef0123456789abcdef",
  "question": "你希望按支付日期还是订单创建日期统计？",
  "requirement": {
    "version": "v0.1",
    "goal": "统计最近30天实际支付金额",
    "metrics": [
      {
        "term": "实际支付金额",
        "resolved_name": "paid_amount",
        "definition": null,
        "status": "CONFIRMED"
      }
    ],
    "dimensions": [],
    "filters": [],
    "time_range": {
      "kind": "RELATIVE",
      "value": "last_30_days",
      "start": null,
      "end": null
    },
    "grain": "DAY",
    "comparison": null,
    "sort": null,
    "limit": null,
    "confirmed_terms": {},
    "assumptions": [],
    "unresolved": [
      {
        "field": "time_definition",
        "reason": "存在多个会改变结果的时间口径",
        "options": ["支付日期", "订单创建日期"],
        "blocking": true
      }
    ],
    "status": "CLARIFYING"
  }
}
```

The exact clarification wording is model-dependent. Clients should display `question` and submit
the user's reply to the same Session; they should not derive workflow authority from the wording.

### 6.2 Result response

Returned only after the final evidence branch has executed and received a PASSED verification.

Response — `200 OK`:

```json
{
  "type": "result",
  "session_id": "session_0123456789abcdef0123456789abcdef",
  "run_id": "run_1123456789abcdef0123456789abcdef",
  "answer": "最近30天的实际支付金额已按天汇总，明细见结果数据。",
  "data": {
    "columns": ["period", "paid_amount"],
    "rows": [
      ["2026-08-28", "1280.50"],
      ["2026-08-29", "963.00"]
    ]
  },
  "assumptions": {
    "requirement": [],
    "query_plan": []
  },
  "evidence": {
    "tables": ["fact_order"],
    "sql": "SELECT DATE(paid_at) AS period, SUM(paid_amount) AS paid_amount FROM fact_order WHERE paid_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY) GROUP BY DATE(paid_at)",
    "query_duration_ms": 8,
    "returned_row_count": 2,
    "repair_count": 0
  },
  "verification": {
    "status": "PASSED",
    "scope": "COVERAGE_BOUNDED",
    "policy_version": "verification-policy-v0.2",
    "coverage": 1.0,
    "unsupported": []
  },
  "synthesis": {
    "mode": "MODEL",
    "limitation": null
  }
}
```

The values above demonstrate the wire shape; they are not promised fixture values.

#### Result fields

| Field | Type | Authority |
| --- | --- | --- |
| `answer` | string | Model language admitted by deterministic grounding, or a deterministic fallback |
| `data.columns` | string array | Actual MySQL cursor metadata |
| `data.rows` | array of positional arrays | Exact bounded execution result |
| `assumptions.requirement` | string array | Canonical RequirementState assumptions |
| `assumptions.query_plan` | string array | Accepted QueryPlan assumptions |
| `evidence.tables` | string array | Physical tables in the final guarded capability |
| `evidence.sql` | string | Exact admitted SQL submitted to MySQL |
| `evidence.query_duration_ms` | integer ≥ 0 | Runtime duration |
| `evidence.returned_row_count` | integer ≥ 0 | Number of returned bounded rows |
| `evidence.repair_count` | integer ≥ 0 | Durable bounded repair count |
| `verification.status` | `"PASSED"` | Required for every result envelope |
| `verification.scope` | `"COVERAGE_BOUNDED"` | Verification does not claim universal semantic proof |
| `verification.policy_version` | string | Deterministic verification policy identity |
| `verification.coverage` | number 0–1 | Applied checks divided by applied plus unsupported checks |
| `verification.unsupported` | array | Explicit verification coverage limitations |
| `synthesis.mode` | enum | `MODEL` or `DETERMINISTIC_FALLBACK` |
| `synthesis.limitation` | string or null | Reason for a deterministic fallback or limitation |

An unsupported verification entry has this shape:

```json
{
  "category": "SEMANTIC",
  "name": "time_filter_equivalence",
  "detail": "The current policy cannot prove this semantic equivalence."
}
```

`category` is `STRUCTURAL`, `SEMANTIC`, or `EMPIRICAL`.

### 6.3 Failure response

Returned when the request cannot safely reach a verified result. A failure does not contain
unverified rows, provider envelopes, credentials, stack traces, or hidden reasoning.

Response — `200 OK`:

```json
{
  "type": "failure",
  "session_id": "session_0123456789abcdef0123456789abcdef",
  "run_id": "run_2123456789abcdef0123456789abcdef",
  "code": "PIPELINE_FAILED",
  "message": "本次请求未能安全完成。",
  "status": "FAILED"
}
```

Terminal failure statuses are:

| `status` | Safe public message | Meaning |
| --- | --- | --- |
| `POLICY_DENIED` | `请求未通过只读查询安全策略。` | SQL/policy authority denied execution |
| `QUERY_TOO_EXPENSIVE` | `查询成本超过当前允许范围。` | EXPLAIN/resource policy denied execution |
| `REPAIR_EXHAUSTED` | `查询修复次数已用尽, 无法安全返回结果。` | The bounded repair path could not safely recover |
| `FAILED` | `本次请求未能安全完成。` | Other safe terminal failure |

`code` is stable diagnostic text for the concrete failure, such as `DIALOGUE_CANNOT_RESOLVE`,
`PIPELINE_FAILED`, `SYNTHESIS_FAILED`, or a typed admission/runtime/verification repair code.
Clients should preserve unknown future codes and use `type` plus `status` as the primary workflow
switch.

## 7. Runs

### `GET /runs/{run_id}`

Returns durable lifecycle metadata for one Run. It does not return trace events, SQL, or result
rows.

```bash
curl http://127.0.0.1:8000/runs/run_1123456789abcdef0123456789abcdef
```

Response — `200 OK`:

```json
{
  "id": "run_1123456789abcdef0123456789abcdef",
  "session_id": "session_0123456789abcdef0123456789abcdef",
  "status": "COMPLETED",
  "repair_count": 0,
  "started_at": "2026-08-30T10:01:00Z",
  "completed_at": "2026-08-30T10:01:08Z",
  "error_code": null
}
```

Run statuses:

```text
RECEIVED
UNDERSTANDING
CLARIFYING
RETRIEVING
PLANNING
VALIDATING
EXECUTING
VERIFYING
SYNTHESIZING
COMPLETED
POLICY_DENIED
QUERY_TOO_EXPENSIVE
REPAIR_EXHAUSTED
FAILED
```

Terminal statuses are `CLARIFYING`, `COMPLETED`, `POLICY_DENIED`, `QUERY_TOO_EXPENSIVE`,
`REPAIR_EXHAUSTED`, and `FAILED`. Each inbound user message receives a new Run; a clarification
reply never resumes the previous terminal Run.

Unknown Run — `404 Not Found`:

```json
{
  "detail": {
    "code": "NOT_FOUND",
    "message": "Run does not exist"
  }
}
```

## 8. HTTP errors

HTTP errors are distinct from the HTTP-200 typed `failure` domain envelope.

| HTTP status | When |
| ---: | --- |
| `404` | Session or Run does not exist |
| `422` | Request JSON, message length/content, or unknown fields fail validation |
| `503` | Conversation runtime is not configured in the application process |
| `5xx` | Unexpected infrastructure failure; the client must not assume the message was not accepted |

Validation example — `422 Unprocessable Entity`:

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "content"],
      "msg": "Value error, content must contain a non-whitespace character",
      "input": "   "
    }
  ]
}
```

Runtime unavailable — `503 Service Unavailable`:

```json
{
  "detail": {
    "code": "CONVERSATION_RUNTIME_UNAVAILABLE",
    "message": "Conversation runtime is not configured."
  }
}
```

In normal production composition, model/runtime startup diagnostics fail the application startup
instead of starting a partially configured conversation service.

## 9. Complete multi-turn example

The example uses `jq` only to extract IDs for shell convenience.

```bash
BASE_URL=http://127.0.0.1:8000

SESSION_ID="$(
  curl --silent --show-error --request POST "$BASE_URL/sessions" |
    jq --raw-output '.id'
)"

curl --silent --show-error \
  --request POST "$BASE_URL/sessions/$SESSION_ID/messages" \
  --header 'Content-Type: application/json' \
  --data '{"content":"看一下最近销售情况"}' |
  jq

# If the response type is "clarification", answer in the same Session.
curl --silent --show-error \
  --request POST "$BASE_URL/sessions/$SESSION_ID/messages" \
  --header 'Content-Type: application/json' \
  --data '{"content":"实际支付金额，最近30天，按天统计"}' |
  jq

curl --silent --show-error "$BASE_URL/sessions/$SESSION_ID" | jq
```

Clarification wording and whether a particular prompt reaches `result` are model-bound behavior,
not fixed API promises. The response envelope and safety authority are deterministic.

## 10. Client integration guidance

A client should implement this state machine:

```text
POST message
  ├─ clarification → display question → collect reply → POST to same Session
  ├─ result        → display answer, data, evidence, verification, limitations
  └─ failure       → display safe message and retain run_id for support/audit
```

Recommended client rules:

1. Switch on `type`, not HTTP `200` alone.
2. Treat IDs and `code` values as opaque strings.
3. Preserve `DECIMAL` strings exactly.
4. Display verification limitations and assumptions with the result.
5. Do not execute the returned SQL on another database; it is evidence for the server-side run.
6. Serialize messages per Session and avoid blind retries.
7. Give the user a way to start a new Session when the analytical intent changes materially.
8. Log `session_id` and `run_id`, but never server credentials or unnecessary result rows.

## 11. Current limitations

- No HTTP authentication, user/tenant model, CORS contract, or rate limiting.
- No session/message/run listing or pagination.
- No message-history endpoint.
- No trace/artifact endpoint.
- No cancellation, streaming, or asynchronous job protocol.
- No idempotency key.
- No database-write API.
- The frozen M15 canonical behavioral verdict is `REJECTED`; this API is an architecture and
  controlled-harness baseline, not an accepted Product NL2SQL release.

These limitations must not be bypassed by exposing internal repositories or execution services
directly.
