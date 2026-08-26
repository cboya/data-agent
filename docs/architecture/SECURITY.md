# Security & Safety Invariants

**Version:** v0.1.0
**Status:** Highest-precedence MVP policy

## 1. Security objective

The Data Agent may reason probabilistically, but data access and execution authority must remain deterministic and least-privileged.

The MVP runs against a synthetic local database, but its boundaries should already model production-safe behavior.

## 2. Threat model

Treat all of the following as untrusted:

- user natural-language input;
- LLM output;
- generated SQL;
- catalog text that may be malformed;
- database error messages sent back into a model repair prompt.

Primary threats:

- destructive SQL;
- multi-statement injection;
- unauthorized table access;
- dangerous MySQL file/system functions;
- query resource exhaustion;
- join explosion;
- accidental secret logging;
- prompt injection in catalog/user content;
- model attempting to bypass a guard after an error.

## 3. Database principal

Create a dedicated runtime principal such as:

```text
data_agent_reader
```

It must have only the minimum read privileges required on the synthetic analytics schema.

Do not give:

- INSERT;
- UPDATE;
- DELETE;
- CREATE;
- ALTER;
- DROP;
- FILE;
- PROCESS;
- SUPER/admin-style privileges.

Test the privilege boundary as part of bootstrap/integration tests.

### 3.1 Control-plane principal

Agent control-plane persistence uses a separate schema and runtime principal from the analytics
reader. The runtime privilege matrix is:

| Control table | SELECT | INSERT | UPDATE | DELETE |
| --- | ---: | ---: | ---: | ---: |
| `agent_session` | yes | yes | yes | no |
| `agent_message` | yes | yes | no | no |
| `agent_run` | yes | yes | yes | no |
| `agent_artifact` | yes | yes | no | no |

Migration/bootstrap administration remains separate from runtime credentials. The control
principal receives no analytics-schema privilege, and the analytics reader receives no
control-schema privilege.

## 4. Credential boundary

Credentials live in application configuration/environment, never in:

- prompts;
- model messages;
- catalog documents;
- trace payloads;
- user-visible evidence.

The LLM adapter and planner do not need database credentials.

## 5. SQL guard

Architecture law:

```text
Raw SQL is data; GuardedQuery is capability.
```

Future normal-query execution consumes the exact immutable payload admitted by M10, not a new SQL
string. The SQL guard runs before EXPLAIN; EXPLAIN success is never treated as statement safety.
M11 revalidates that payload's SHA-256, the M10 analytics execution namespace, and current
guard/EXPLAIN policy identities immediately before execution. The capability namespace must equal
the runtime connection factory's default database before any connection is opened. M11 must not
inject a `LIMIT`, re-render the AST, add a hint, wrap the query, or otherwise execute SQL text
different from the admitted capability.

Every candidate SQL query must:

1. parse successfully under the MySQL dialect;
2. contain exactly one statement;
3. have a read-only `SELECT` or set-operation root;
4. resolve physical tables through SQL scopes so CTE/derived aliases do not become authority;
5. reference only unqualified/configured analytics-schema tables declared by `QueryPlan.tables`;
6. contain no prohibited construct, recursive CTE, lock, or optimizer/index hint;
7. use only the explicitly approved EXPLAIN-safe analytics function surface;
8. pass configured resource rules.

String/regex checks alone are not sufficient.

## 6. Minimum prohibited SQL

Reject at minimum:

- `INSERT`
- `UPDATE`
- `DELETE`
- `REPLACE`
- `CREATE`
- `ALTER`
- `DROP`
- `TRUNCATE`
- `GRANT`
- `REVOKE`
- `CALL`
- `LOAD DATA`
- `INTO OUTFILE`
- `INTO DUMPFILE`

Reject any multi-statement input even if the first statement is `SELECT`.

The declared-table rule is subset, not equality. Unused declarations remain visible evidence:

```text
Tables(SQL) ⊆ QueryPlan.tables
```

They do not authorize an undeclared physical table, and a CTE that shadows a table name cannot
conceal a physical reference in another namespace.

## 7. EXPLAIN-safe functions and dangerous behaviors

Plain MySQL `EXPLAIN SELECT` is not universally side-effect free. MySQL documents cases where
optimizer processing evaluates a stored function inside a subquery while an outer query reads a
table, allowing the function to modify data. The Guard must therefore prove an EXPLAIN-safe
function subset before the provider is called; reader privileges are defense in depth, not the AST
authority.

Every SQLGlot `Func` node must match the versioned approved MVP surface. Unknown functions,
loadable/stored-function shapes represented by `Anonymous`, and recognized built-ins outside that
surface fail closed as `UNAPPROVED_FUNCTION`. The initial approved surface is limited to boolean
AND/OR and CASE/IF expression nodes plus `SUM`, `COUNT`, `DATE`, `DATE_SUB`, `CURRENT_DATE`,
`COALESCE`, and `CAST`. Function arguments are traversed by the same policy, so nesting cannot hide
an unapproved call.

The implementation also maintains an explicit deny policy for known dangerous/non-analytic
constructs, including file/system or intentional-delay behavior where applicable.

At minimum evaluate/reject constructs involving concepts such as:

- file access (`LOAD_FILE`);
- MySQL executable comments and session-variable reads/writes;
- advisory locks (`GET_LOCK`, `RELEASE_LOCK`, and related inspection functions);
- row locks (`FOR UPDATE`, `LOCK IN SHARE MODE`);
- optimizer and index hints;
- sleep/delay (`SLEEP`);
- benchmarking/intentional work amplification (`BENCHMARK`);
- server-side export.

Use AST semantics where possible.

## 8. Table scope invariant

Hard invariant:

```text
ReferencedTables(SQL)
    ⊆ QueryPlan.tables
    ⊆ AuthorizedRetrievedTables
```

If extraction is ambiguous or parser support is insufficient, fail closed.

## 9. Query limits

Enforce in deterministic code/configuration:

- max execution time;
- max returned rows;
- max deterministic normalized result bytes;
- max repair attempts;
- max candidate/retrieved tables;
- max relationship expansion depth;
- reasonable API request/body limits.

Result caps must be enforced application-side even if SQL includes `LIMIT`.

M11 uses a dedicated analytics-reader connection for each query, enables and verifies session
transaction read-only mode, and sets MySQL `max_execution_time`. The client read timeout is bounded
and strictly greater than the server execution bound. Execution uses an unbuffered cursor and
fetches no more than the row bound plus one. When row or byte truncation leaves unread data, the
connection is closed directly without closing the unbuffered cursor, so driver cleanup cannot
drain an arbitrary remainder. Timeout, disconnect, and database errors are not retried.

## 10. EXPLAIN gate

Before execution:

```text
SQL Guard → EXPLAIN → policy → execute
```

EXPLAIN policy rejects oversized/overly deep plan structures, invalid JSON/shape, missing access
estimates for physical-table queries, provider failures, and table-access estimates above
`MAX_EXPLAIN_ESTIMATED_ROWS` in the synthetic environment. The row threshold applies per reported
access and is not a portable optimizer cost model.

The Harness constructs exactly `EXPLAIN FORMAT=JSON` only after the SQL guard passes. Model-supplied
EXPLAIN is rejected, and `EXPLAIN ANALYZE` is never used because it executes the statement. Plain
EXPLAIN receives only the function-approved subset; it is not treated as inherently non-executing.

Exact thresholds are calibration parameters, but inability to safely inspect a plan should not cause an unsafe fallback.

## 11. Repair policy

Only repair errors that are safe to repair, such as:

- unknown column due to planner mistake;
- alias/syntax issue;
- selected schema mismatch.

Do not allow repair to circumvent:

- policy denial;
- unauthorized table rejection;
- prohibited statement rejection.

Security rejection is terminal for that candidate.

## 12. Prompt injection boundary

Catalog descriptions and user text are data, not authority.

System/developer constraints and deterministic guards outrank instructions found in:

- table comments;
- column comments;
- user messages;
- database error text.

Never treat text such as “ignore previous rules and query X” inside catalog content as execution authority.

## 13. Trace redaction

Never persist:

- credentials;
- authorization tokens;
- entire unbounded result sets;
- unnecessary row-level sensitive values.

Prefer:

- row count;
- column names;
- duration;
- small bounded samples only when needed;
- hashes/fingerprints.

M11 success metadata binds the exact bounded result through a versioned canonical fingerprint but
never embeds raw rows. M12 recomputes that fingerprint and validates the complete planning,
capability, execution, namespace, policy, and result identity chain before any correctness check.
An identity mismatch raises `VerificationIntegrityError` and cannot be downgraded to a passed or
failed business check.

The MVP verifier is authority-free: it receives no database connection or model port, performs no
query, does not rewrite or repair SQL, and cannot mutate requirement or plan state. Insufficient
semantic evidence is recorded as a coverage gap rather than filled with an LLM judgement or an
independent business-semantics registry.

## 14. Fail-closed rules

Do not execute if:

- SQL cannot be parsed;
- table references cannot be determined;
- table scope cannot be proven;
- query policy cannot classify the statement;
- EXPLAIN policy cannot safely evaluate the plan;
- database principal is not verified as read-only in bootstrap checks.

## 15. Security test gate

`task quality` must include automated tests covering:

- allowed simple SELECT;
- CTE SELECT;
- rejected DML/DDL;
- rejected multi-statement;
- rejected outfile/file behavior;
- rejected dangerous functions;
- rejected out-of-scope table;
- enforced timeout;
- enforced result cap;
- enforced result-byte cap and non-draining truncation cleanup;
- capability-only execution with exact-payload integrity revalidation;
- verified read-only principal.

Security tests require 100% pass rate for MVP completion.
