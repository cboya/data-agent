# M15 final integrated-run failure attribution

## Verdict

The canonical clean sequence reached `task eval`, but final acceptance did not complete.

```text
source Git head                 2945a3ff13312a945c6a2e235e81e6f4159d6126
EvaluationEnvironment          122d45dc5446cca9a18de1af7406600208ef4723597fca7538a550e8a2e4c2d3
task reset                     PASS
task bootstrap                 PASS
task quality                   PASS — 493 passed / 7 skipped
task eval                      FAIL — exit 201
canonical latest.json written  NO
PR #15                         DRAFT
MVP                            NOT ACCEPTED
```

The retained `evals/reports/latest.json` still belongs to `3be2534`; it is historical evidence
only and is not evidence for this run.

## Preflight evidence

Deterministic M8, M12, M13, M14, and M15 integrity gates passed. The six-case bound-model smoke
also passed its control-plane gate:

```text
typed outcomes                 6 / 6
valid READY                    2
safe stops                     4
unsafe READY                   0
unsafe durable mutation        0
```

## Fresh mutually-exclusive attribution

The Golden suite contains 59 cases. Forty-one cases completed before the abort, one case aborted,
and 17 cases were not executed. The exact partition is:

| Bucket | Class | Count | Earliest owner |
|---|---|---:|---|
| PASS | pass | 6 | — |
| DIALOGUE_STRUCTURED_FAILURE | ordinary model behavior | 15 | M8 |
| PLANNING_FAILURE | ordinary model behavior | 5 | M9 |
| SQL_ADMISSION_FAILURE | ordinary behavior, fail closed | 1 | M9/M10 |
| VERIFICATION_FAILURE | ordinary behavior, fail closed | 12 | M9/M12/M13 |
| ANSWER_SYNTHESIS_FAILURE | ordinary behavior, fail closed | 2 | M14 |
| INFRASTRUCTURE_CONTROL_FLOW_ABORT | architecture/control-flow or infrastructure | 1 | M15/local MySQL |
| NOT_EXECUTED_AFTER_ABORT | not observed | 17 | consequence of abort |

The machine-readable companion contains every exact case ID. Counts sum to 59.

The independent stage suite separately reported Dialogue FAIL (`action_accuracy=0.433`,
`state_accuracy=0.400`, clarification recall `0.000`) while Retrieval, Planning, SQL Guard,
Runtime, Verification, Repair, and Answer stage evals passed. Those Dialogue failures and the 35
completed-prefix Golden failures are behavioral-quality evidence; they do not by themselves prove
a reopened trust-boundary defect.

## Fatal control-flow evidence

The fatal case is `join-paid-orders-category`:

```text
session                         session_ea3336aadcff437f99e0ace1e3e52655
run                             run_e14247da9f504eaabaca8e1aa004b711
persisted status                PLANNING
persisted trace                 RUN_RECEIVED → DIALOGUE_COMPLETED → RETRIEVAL_COMPLETED
failed operation                append PLANNING_COMPLETED
root exception                  MySQL OperationalError 2013 / read timeout
surface                         TraceError: trace persistence failed closed
SQL admission/execution         NOT REACHED
```

The runtime correctly refused to continue without durable trace evidence, so this is not an
unauthorized-execution path. However, the exception escaped the public request and aborted
`run_golden`; the run remained non-terminal with an incomplete trace, and no new canonical
`FinalAcceptanceReport` was written. The final trace-integrity and 59-case behavioral thresholds
therefore cannot be adjudicated. The completed prefix contained no observed verified/Oracle
mismatch, but the frozen full-suite invariant remains **NOT ADJUDICATED**, not PASS.

## Decision boundary

```text
M15 Behavioral Acceptance       FAIL
M15 Final Substantive Review     NOT AUTHORIZED
PR #15                           DRAFT
MVP Baseline                     NOT ACCEPTED
Upstream remediation             NOT AUTHORIZED
```

The next substantive decision is narrow: determine whether the single MySQL/trace abort is an
environmental rerun condition or an M15 evaluation/control-flow defect. This incomplete run does
not authorize reopening M8–M14 semantics.
