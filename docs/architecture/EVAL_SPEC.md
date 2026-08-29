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

The frozen MVP suite is `evals/golden.yaml`; its trusted static result Oracles are isolated in
`evals/oracles.yaml`. Neither source is runtime or model context.

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

The standalone M13 gate has two bounded corpora. A deterministic eligibility/safety corpus covers
repairable formulation, every nonrepairable policy/integrity/runtime class, verification coverage
non-triggering, exhausted budget, and concurrent atomic claim. It reports classification accuracy,
policy/integrity zero-model-call accuracy, and bound enforcement. A separate bounded real-model
corpus covers syntax, unknown-column, and one selected verification formulation failure through a
new M9→M12 branch. Cross-Run replay and typed-stage/Run-state mismatch regressions must prove zero
attempt consumption and zero model calls, alongside the real same-Run atomic concurrency gate. It
reports eligible first-attempt success, post-repair M12 pass, repair/model
counts, and prompt/model/runtime/failure fingerprints. It makes no general self-healing claim.

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

The provider-free M8 readiness-remediation gate is separate from the model-dependent dialogue
target. It replays the exact 35 diagnosis-proven false-clarification cases plus frozen true-
ambiguity controls through provider proposal, provisional patch merge, blocking policy, final
decision, and canonical state. It requires:

- all 35 exact known false-clarification cases are present;
- unnecessary clarification count on those cases = 0;
- necessary clarification recall on true-ambiguity controls = 1.00;
- false READY count on true-ambiguity controls = 0;
- insufficient-provider-evidence false READY count = 0;
- the three legacy cases without exact resolved/unresolved subject evidence (`simple-paid-users`,
  `join-units-order`, and `join-units-attempts-order`) produce typed invalid evidence, not a
  decision, while a separate structurally complete control for the empty-state case preserves both
  requested metrics and the requested dimension before reaching READY;
- action, exact canonical state, stable reason-code, and optional-scope preservation accuracy =
  1.00.

This exact-defect gate does not replace or tighten the final model-dependent M15 unnecessary-
clarification threshold. Runtime policy never reads Golden expected answers.

Time-ambiguity cases must also prove that a guessed concrete time range does not survive into
canonical state merely because the model correctly chose ASK.

Permanent provider-free time-range admission regressions additionally require:

- `RELATIVE/recent` cannot authorize READY and produces typed invalid provider evidence;
- canonical `RELATIVE/last_30_days` remains admitted;
- the existing exact bounded date-interval representation remains admitted;
- the rejected proposal emits no public `DialogueDecision` and causes no durable state mutation.

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
- frozen verified/Oracle mismatch count = 0.

The last item is an exact release hard gate, separate from any probabilistic Golden Oracle pass
rate. The six frozen M15 diagnostic regressions (four unrequested-grain and two unprovable public
output-shape cases) must never finish with both M12 `PASSED` and deterministic Oracle `FAILED`.
Their source Golden and Oracle truth are not rewritten by the M12 suite.
The frozen M12 suite also contains metric-only and requested-dimension aggregates whose hidden
`GROUP BY` keys refine result grain; both must be semantic failures even when their public columns
match the READY requirement exactly. A missing or ambiguous requested-dimension M6 source is
nonrepairable and must consume zero M13 attempts/model calls.
The suite also freezes MySQL's source-column-first `GROUP BY` resolution: a grouping name that
collides with an input column must not be accepted as a transformed SELECT alias, while a proven
noncolliding alias and a valid SELECT ordinal remain accepted.

Verification coverage is reported, not optimized into a false pass. A green M12 report means all
currently encoded applicable invariants classified the controlled mutations correctly; it does
not claim global SQL equivalence or business-answer correctness.

The standalone M13 deterministic gate additionally requires:

- eligibility classification accuracy = 1.00;
- policy/integrity zero-model-call accuracy = 1.00;
- configured repair-bound enforcement = 1.00;
- concurrent claim does not exceed the durable bound.
- cross-Run branch replay and failure-stage/Run-state mismatch consume zero attempts and make zero
  model calls.

The bounded real-model M13 report must separately show eligible first-attempt success and final
post-repair M12 pass for each frozen case; it does not weaken any M10–M12 gate.

The standalone deterministic M14 answer gate additionally requires every metric to be `1.00`:

- grounding decision accuracy;
- hallucinated numeric-fact rejection;
- request/context-to-result numeric-authority separation;
- arithmetic-derived percentage rejection;
- invalid/missing positional-reference rejection;
- exact Decimal API fidelity;
- unsupported verification-limitation visibility.

The separate three-case real-Ollama answer smoke reports structured parse plus deterministic
grounding success, non-empty usefulness, positional-reference validity, prompt-injection
resistance, and the one-call bound. It does not grade exact wording or claim general answer
quality. End-to-end HTTP smoke independently covers one-turn success, multi-turn clarification,
bounded repaired success, and terminal policy failure.

These values are MVP engineering gates for the synthetic world, not claims about production accuracy.

### Final M15 public-API acceptance

The canonical runner executes every standalone stage gate, then at least 50 cases through
`POST /sessions` and `POST /sessions/{id}/messages`. It inspects the typed response, publicly
readable Run, and persisted append-only trace. Trusted result assertions compare typed values from
static eval-only SELECT Oracles without exact SQL equality; Golden SQL never enters runtime or
prompt context. Fixed absolute dates are required wherever wall-clock-relative interpretation
would change result truth.

Final hard gates are:

- trace integrity and terminal completeness = `1.00`;
- unauthorized execution count = `0`;
- synthesis after failed verification count = `0`;
- numeric grounding violation count = `0`;
- repair-bound violation count = `0`.

Behavioral gates are Golden E2E pass rate `>= 0.90`, result-Oracle pass rate `>= 0.90`, and
unnecessary clarification rate `<= 0.10`, while preserving all prior stage targets including M7
Recall@5/Recall@10. `evals/reports/latest.json` includes case stage, Run IDs, trace assertion
failures, stage reports, and the canonical `EvaluationEnvironment` fingerprint.

The frozen model-neutral profile contains 59 cases: 55 Oracle-backed results over 54 distinct
semantic/result Oracles, plus four safe terminal failures. Category coverage is 15 simple, 22
aggregation/time, 11 relationship/trap, four multi-turn clarification/correction, three
repair/empty cases, and four policy failures. Two result Oracles prove empty populations and one
formulation permits the single allowed repair when needed. A stronger model is not required to
fail its first branch merely to manufacture repair evidence; the standalone M13 eval retains the
deterministic repair gate. Exact-result requests use fixed absolute dates.

Case selection is not calibrated to the weakest available model. The initial 8B local-model run
is diagnostic evidence; a stronger local Ollama model may provide final behavioral acceptance only
under its own complete environment fingerprint. Model changes never change Golden sources,
Oracles, or deterministic gates.

`EvaluationEnvironment v0.1` must bind at least Git commit, Golden version/fingerprint, generated
schema, semantic catalog fingerprint/revision, retrieval index, chat/embedding model fingerprints,
Ollama runtime, dialogue/planning/repair/answer prompt versions, guard/EXPLAIN/runtime/
verification/repair/grounding policies, trace schema, Python runtime, and dependency lock. A model
acceptance result missing any bound identity is invalid rather than partially reproducible.
The runner refuses to issue an environment identity from a dirty Git worktree and fixes Golden
temporal interpretation to UTC with absolute-date result cases.

If calibration shows a target is structurally inappropriate, revise this file explicitly with
rationale; do not silently lower a test. Changing the frozen case source, model identity, prompt,
catalog, or policy invalidates the earlier environment-bound acceptance result.

### M15 behavioral-failure attribution

`task m15-attribution` derives an eval-only diagnostic report from an already completed canonical
report; it does not call a model, execute a query, or change acceptance status. The derived report
must bind the source Git/environment/Golden fingerprints, provide a case-reached stage funnel, and
assign every Golden case to exactly one terminal bucket so the bucket counts equal the frozen case
count. Per-case evidence includes Run IDs, trace-event IDs, retained failure codes, and owning
frozen milestone candidates.

Stage-funnel counts mean "reached or passed at least once" and are not themselves a partition for
multi-turn cases. Terminal buckets are the partition. Unknown evidence must stay unknown: if the
source report did not retain clarification blocker fields, same-input standalone replay, or a
typed model-failure cause, attribution records `EVIDENCE_UNAVAILABLE`, `NOT_REPLAYED`, or
`UNCLASSIFIED` instead of inferring a field from user text or treating a zero classified count as
proof that the failure did not occur. `M12 PASSED + Oracle FAILED` result branches are reported as
a dedicated high-priority set.

### M15 targeted behavioral diagnosis

`task m15-behavioral-diagnosis` is an eval-only follow-up to a completed attribution report. It
must not run the complete Golden suite or change runtime behavior, prompts/policies, Golden or
Oracle truth, behavioral thresholds, model choice, timeout, or output-token bounds. Before any
model call it fails closed unless the retained effect environment and live chat/embedding model
fingerprints, Ollama version, dialogue prompt, timeout, and output ceiling match exactly; frozen
runtime, Golden, and Oracle source must have no diff from the effect commit.

The M8 replay case set is exactly the 35 cases assigned to unnecessary clarification by the bound
attribution report. It records every replayed turn's expected/original/standalone action, blocking
field and model-facing subject term, structured `DialogueProposal`, normalized
`DialogueDecision`, `RequirementPatch`, merged `RequirementState`, typed structured-call outcome,
and prompt/model/environment identity. No hidden reasoning is retained. Every case belongs to
exactly one of four ownership classes, and their counts must sum to 35. A checkpoint is reusable
only under the same full diagnostic identity.

The false-accept forensic set is exactly the six retained `M12 PASSED + Oracle FAILED` cases. A
model rerun is permitted only because the canonical source report did not retain the full
`RequirementState → PlannerContext → QueryPlan → SQL → ExecutionResult → VerificationTrace`
chain and clean reset removed the referenced control rows. Each targeted replay records that
chain plus the static Oracle, whether the retained public shape was reproduced, earliest semantic
divergence, and exclusive M9/M12/both/human-review ownership. It stops model activity after M12;
an eval-only deterministic synthesis placeholder may complete persistence but creates no M14
behavior claim. Machine-readable and human-readable reports remain diagnostic evidence: they do
not make PR #15 ready or authorize remediation of a frozen milestone.

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
