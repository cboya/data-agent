# M15 final canonical acceptance evidence

## Verdict

The one authorized environmental rerun completed all 59 Golden cases and wrote a fresh canonical
report. The earlier MySQL/trace abort did not recur, including at the previously interrupted case.
This is therefore a valid behavioral acceptance result, not another infrastructure abort.

The canonical adjudication is **REJECTED**. This means the acceptance process completed and the
Product NL2SQL MVP did not pass; it does not rename behavioral failure as success. Separately, the
M15 evaluation infrastructure is implemented, substantively approved, and may close through the
approved PR #15 squash merge.

```text
source Git head                 431fb1fdbb5e8b6e94e0d1b59a7a4bc8bdd478ec
EvaluationEnvironment          c711d8bc5d7d25d0dddde7536e4ee8f17a6f4f8678a6e616893d85f7942fc607
task reset                     PASS
task bootstrap                 PASS
task quality                   PASS — 493 passed / 7 skipped / 1 known warning
task eval                      FAIL — complete 59-case report written
canonical report SHA-256       98b140964301dd6b6555afe379b9e0e90b95645c0c935832f0cdd66b54a9412e
PR #15                         DRAFT
MVP                            NOT ACCEPTED
```

The stale pre-run `latest.json`, which belonged to the old `3be2534` environment, was moved before
the clean sequence to `/private/tmp/m15-stale-latest-3be2534.json`. The canonical
`evals/reports/latest.json` is 327,612 bytes, binds the exact source head above, and was written only
after the complete run.

## Environment identity

The report binds the frozen final environment:

| Identity | Value |
|---|---|
| Golden | `golden-v0.1` / `53d969d1196877829cc89ee3070d75a1fea6ba88bfd5986fbe66beb21fcf93f7` |
| Generated schema | `7390d087d0c50d152dc7d3e0f0d76e2657a992921bba41606076e63e3f8dbd64` |
| Catalog | `b492ee596e681484d9fabdb8981e773bba78079e15effd7ea1f67e23d10c5b1f` |
| Semantic revision | `7f01061e15eabef2122a0fc99c647cf4a110d536eb52ad29a3859b89a0193d50` |
| Retrieval index | `f9da78a01e6d030185c4510ba394b860e0d79bd39c06ea625b95599aed76b9e4` |
| Chat model | `be7d8c949d1d85dc17e248c17db10be4634effd614fd20860d749082fbe7fe3e` |
| Embedding model | `0112ea4d6590628288600ebd612ee8b094001c1e181c4eda9a64493d205c138f` |
| Ollama | `0.33.1`, timeout `60s`, max output tokens `2048` |
| Prompts | dialogue `v0.21`, planning `v0.3`, repair `v0.1`, answer `v0.2` |
| Policies | SQL guard `v0.2`, runtime `v0.2`, verification `v0.2`, repair `v0.1`, answer grounding `v0.2`, trace `v0.1` |
| Dependencies / Python | `4473ef68cdc8e905df59ec32030728ceec1c88643d6acf9bd8d01a3c29d21a87` / `3.14.7` |

No model, prompt, policy, Golden/Oracle truth, threshold, timeout, or token ceiling changed.

## Stage gates

| Stage | Result | Selected evidence |
|---|---|---|
| Retrieval | PASS | final Recall@5 `0.9896`, Recall@10 `1.0000`, path recovery `1.0000` |
| Dialogue | **FAIL** | action `0.4333`, state `0.4000`, clarification recall `0.0000`, unnecessary clarification `0.0000` |
| Planning | PASS | required-table recall `0.9841`, precision `1.0000`, exact table set `0.9524` |
| SQL Guard | PASS | security guard/explain accuracy `1.0000`, proposal guard pass `1.0000` |
| Runtime | PASS | read-only, timeout, bounds, fidelity, no-hidden-retry all `1.0000` |
| Verification | PASS | false accept/reject `0`, verified/Oracle mismatch `0` |
| Repair | PASS | eligibility and all repair-bound invariants `1.0000` |
| Answer | PASS | grounding and numeric-integrity checks all `1.0000` |

## Golden behavioral result

```text
case count                         59
E2E pass                           10 / 59 = 0.1695
result Oracle pass                  6 / 55 = 0.1091
trace integrity                    1.0000
unnecessary clarification          0.0000
unauthorized execution             0
failed-verification synthesis      0
numeric-grounding violation        0
repair-bound violation             0
verified + Oracle mismatch         0
```

The epistemic-integrity hard gate remains closed correctly:
`verified_oracle_mismatch_count == 0`.

## Mutually-exclusive 59-case attribution

The canonical `failure_stage` provides the fresh, exhaustive terminal partition:

| Bucket | Count | Classification | Earliest bounded owner set |
|---|---:|---|---|
| PASS | 10 | pass | — |
| DIALOGUE | 18 | ordinary model behavior | M8 |
| PLANNING | 4 | ordinary model behavior | M9 |
| SQL_ADMISSION | 5 | ordinary behavior, fail closed | M9/M10 |
| VERIFICATION | 21 | ordinary behavior, fail closed | M9/M12/M13 |
| SYNTHESIS | 1 | ordinary behavior, fail closed | M14 |

Counts sum to 59. The machine-readable companion contains every exact case ID and proves each ID
appears exactly once. There are zero architecture/control-flow failures and zero environment aborts
in this run. The 49 failures are behavioral terminal outcomes; the owner-set labels are diagnostic
boundaries, not authorization to reopen any frozen milestone.

The existing `task m15-attribution` command was also attempted without model calls. It rejected the
new complete run because 63 dialogue turns are outside its historical confusion-cell taxonomy.
No evaluation-harness change was authorized or made. Consequently this evidence uses the canonical
report's already-frozen `golden.cases[].failure_stage` for the required mutually-exclusive
partition rather than altering the attribution schema after observing the run.

## Decision boundary

```text
previous environmental abort       did not recur
earlier MySQL timeout adjudication  INVALID / ABORTED
final canonical adjudication       REJECTED
M15 Evaluation Infrastructure      COMPLETE / FROZEN ON PR #15 MERGE
M15 Canonical Evaluation           COMPLETE
M15 Behavioral Verdict              REJECTED
Architecture / Harness Baseline     VALIDATED
Product NL2SQL MVP                  NOT ACCEPTED
M15 Final Substantive Review        APPROVED
PR #15                              APPROVED FOR SQUASH MERGE
Remediation                         NOT AUTHORIZED / NOT PERFORMED
MVP release / tag                   NOT AUTHORIZED
```

This publication records the observed result and the separate infrastructure approval. It
authorizes Ready/formal approval/squash merge of PR #15 only. It does not authorize another
canonical rerun, any M8–M15 behavior change, behavioral remediation, Product MVP acceptance,
release, or tag.
