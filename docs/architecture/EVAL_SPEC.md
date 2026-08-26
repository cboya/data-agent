# Evaluation Specification

**Version:** v0.1.0
**Status:** Acceptance authority for MVP behavior

## 1. Principle

The Golden Dataset defines whether the system works.

Do not evaluate Text-to-SQL by exact SQL string equality. Different SQL can be semantically equivalent.

Evaluate the pipeline by stage and by final evidence.

## 2. Deterministic test world

Evaluation runs against the Docker MySQL synthetic business world.

Requirements:

- deterministic schema;
- deterministic seed data;
- deterministic fixture facts;
- clean rebuild reproducibility;
- known expected analytical answers for selected cases.

A clean `task reset && task bootstrap` must recreate the same logical evaluation world.

## 3. Case categories

Initial Golden Dataset should reach at least 50 cases before declaring MVP complete.

Suggested distribution:

| Category | Target |
|---|---:|
| Simple/single-table | 10 |
| Time/aggregation semantics | 10 |
| Multi-table joins | 10 |
| Semantic retrieval | 8 |
| Clarification behavior | 7 |
| Security/failure behavior | 5 |

Early implementation may begin with the example cases under `evals/golden.example.yaml`.

## 4. Golden case contract

Each case may define:

```yaml
id: sales-001
turns:
  - role: user
    content: 最近30天每天实际支付金额是多少？
expected:
  final_action: result
  required_tables:
    - fact_order
  forbidden_tables: []
  semantic_constraints:
    metric: paid_amount
    time_column: paid_at
    grain: day
  expected_result:
    assertion: fixture_reference
    reference: paid_amount_last_30_days_daily
```

Multi-turn clarification:

```yaml
id: clarify-001
turns:
  - role: user
    content: 最近销售怎么样？
  - role: user
    content: 实际支付金额
  - role: user
    content: 最近30天按天
expected:
  clarification:
    first_turn: true
  final_action: result
```

## 5. Stage metrics

### 5.1 Requirement understanding

- metric semantic accuracy;
- time-range accuracy;
- grain accuracy;
- blocking ambiguity detection.

### 5.2 Clarification

- required clarification recall;
- unnecessary clarification rate;
- turns-to-ready.

M8 also reports standalone dialogue action accuracy, canonical state accuracy, explicit-clear
accuracy, correction accuracy, and multi-turn convergence. The frozen controlled-world M8 suite
contains at least 25 cases across complete, metric/time/grain ambiguity, non-blocking uncertainty,
explicit clear, correction, multi-turn, and mixed-language categories. It includes a mixed
resolved-plus-ambiguous member case within one collection and proves the resolved sibling survives
a bounded clarification turn without replaying the original user message. It runs without
retrieval, planning, or SQL.

### 5.3 Retrieval

- required table Recall@5;
- required table Recall@10;
- Precision@5;
- relationship-path recovery.

### 5.4 Query

- standalone M9 structured-plan parse rate;
- allowed declared-table compliance;
- out-of-context declared-table rejection;
- required-table recall;
- plan-table precision;
- exact required-table-set accuracy;
- expected-column accuracy where annotated;
- representative SQL generation evidence, explicitly without a correctness claim;
- standalone M10 adversarial guard decision accuracy;
- standalone M10 valid-case EXPLAIN admission accuracy;
- SQL parse, guard, physical-table scope, and EXPLAIN admission rates on the frozen accepted-M9
  proposal snapshot;
- SQL execution rate;
- semantic correctness;
- repair rate.

The standalone M11 runtime gate uses frozen deterministic queries admitted through M10 and reports:

- execution success rate;
- server timeout enforcement and single-attempt behavior;
- row and normalized-byte bound enforcement;
- capability-only admission and analytics-reader privilege enforcement;
- actual cursor-column/positional-row fidelity;
- exact `Decimal` fidelity.

It does not invoke an LLM and does not claim that an executed result semantically answers a user
requirement. That claim remains deferred to M12.

The standalone M12 verification gate uses frozen or constructed coherent M9–M11 evidence and
deterministic mutations. It reports structural, semantic, and empirical decision accuracy over
applicable cases; false accept/reject rates; identity-mismatch and truncation rejection; and the
ratio of applied checks to applied plus unsupported potential checks. Not-applicable and
unsupported coverage are recorded separately from passed checks. The verifier performs no model
or database call.

### 5.5 Result

- expected result assertion pass;
- numerical exactness/tolerance;
- verification pass;
- answer grounding.

### 5.6 System

- model calls per case;
- query count per case;
- latency;
- repair count.

## 6. MVP acceptance targets

These are initial controlled-world release gates.

### Hard gates

Must be 100%:

- security invariant tests;
- contract validation tests;
- deterministic fixture rebuild tests;
- result-grounding tests for deterministic numeric facts;
- no unauthorized SQL execution.

### Behavioral targets

On the frozen Golden Dataset:

- Required Table Recall@10 ≥ 0.95
- Required Table Recall@5 ≥ 0.90
- SQL parse rate on executable valid cases ≥ 0.98
- SQL execution rate after bounded repair ≥ 0.95
- final expected-result assertion pass rate ≥ 0.90
- unnecessary clarification rate ≤ 0.10

The standalone M8 dialogue gate additionally requires:

- action accuracy ≥ 0.90;
- canonical state accuracy ≥ 0.90;
- required clarification recall ≥ 0.90;
- unnecessary clarification rate ≤ 0.10;
- explicit-clear accuracy = 1.00;
- correction accuracy = 1.00;
- multi-turn convergence = 1.00.

Time-ambiguity cases must also prove that a guessed concrete time range does not survive into
canonical state merely because the model correctly chose ASK.

Collection-ambiguity cases must prove that blocking one metric/dimension subject does not erase a
different resolved member from the same collection. Any subsequent clarification turn must
recover that member from canonical `RequirementState`, not replayed raw history.

The standalone controlled-world M9 planner gate additionally requires:

- structured `QueryPlan` parse rate = 1.00;
- out-of-context declared-table acceptance = 0;
- required-table recall ≥ 0.95;
- plan-table precision ≥ 0.90;
- exact required-table-set accuracy ≥ 0.90;
- expected-column accuracy ≥ 0.90 where annotated.

M9 evaluation never executes generated SQL and does not claim SQL syntax, safety, executable, or
result correctness. Representative SQL evidence is bounded case-insensitive string observation,
not parsing or authorization. Those claims begin only after the M10–M12 deterministic boundaries
exist.

The standalone controlled-world M10 gate additionally requires:

- frozen adversarial guard decision accuracy = 1.00;
- frozen valid-case EXPLAIN admission accuracy = 1.00;
- unknown/stored-function-shaped SQL is rejected before the EXPLAIN provider is called;
- accepted-M9 proposal SQL parse rate ≥ 0.98;
- accepted-M9 proposal guard pass and physical-table scope compliance = 1.00.

The accepted-M9 proposal snapshot is immutable evidence from the accepted M9 head and is not
regenerated by M10. Its EXPLAIN admission rate is reported as calibration evidence: a provider or
optimizer rejection proves M10 failed closed and identifies input for future bounded M13 repair;
it is not silently reclassified as an M10 guard failure. M10 submits only `EXPLAIN FORMAT=JSON`
after proving the approved EXPLAIN-safe function surface, never submits the candidate as a normal
query, and makes no result or semantic-correctness claim.

The standalone deterministic M11 gate additionally requires every reported runtime metric to be
`1.00` on the frozen controlled-world suite. Its report binds the suite fingerprint, M10 guard and
EXPLAIN policy versions, M11 runtime policy version, PyMySQL/MySQL versions, analytics schema,
reader principal class, and all active execution/result bounds. Reports contain shape/count/timing
metadata only, never full result rows.

The standalone deterministic M12 gate additionally requires:

- structural decision accuracy = 1.00;
- semantic decision accuracy over applicable cases = 1.00;
- empirical decision accuracy over applicable cases = 1.00;
- false accept rate = 0;
- false reject rate = 0;
- evidence identity mismatch rejection = 1.00;
- PlannerContext semantic-content substitution rejection = 1.00;
- runtime truncation rejection = 1.00.

Verification coverage is reported, not optimized into a false pass. A green M12 report means all
currently encoded applicable invariants classified the controlled mutations correctly; it does
not claim global SQL equivalence or business-answer correctness.

These values are MVP engineering gates for the synthetic world, not claims about production accuracy.

If the first 50-case calibration shows a target is structurally inappropriate, revise this file explicitly with rationale; do not silently lower a test.

## 7. Semantic correctness

A query may execute and still be wrong.

Golden cases should encode constraints such as:

- “实际支付金额” uses `paid_amount`, not `total_amount`;
- payment time uses `paid_at`, not order creation time;
- order count is not count of payment-attempt rows;
- net revenue accounts for refunds when requested;
- multi-detail joins do not fan out metrics;
- region analysis follows the correct relationship path.

## 8. Retrieval evaluation isolation

Support evaluating retrieval without invoking SQL generation.

This makes failures attributable:

```text
missing table → retrieval problem
retrieved table, bad SQL → planner problem
correct SQL, bad explanation → synthesis problem
```

## 9. Model nondeterminism

Use low-temperature/deterministic settings where supported for structured planning/eval.

Eval runner must record:

- configured chat model;
- embedding model;
- relevant model options;
- catalog/index fingerprint.

A result without environment/model fingerprints is not fully reproducible.

## 10. Regression workflow

Every meaningful real failure should become one of:

- Golden Dataset case;
- deterministic unit test;
- security invariant test;
- catalog semantic correction.

Do not rely on prompt tweaks without a regression artifact.

## 11. Reporting

`task eval` should produce a human-readable summary plus machine-readable report.

Suggested output:

```text
evals/reports/latest.json
```

The report should include:

- environment fingerprint;
- case-level outcome;
- stage-level outcome;
- aggregate metrics;
- failures with trace/run IDs.
