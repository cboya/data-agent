# EP-002 — Portability Validation

**Status:** ACTIVE — M17 External MySQL Portability / implementation and live conformance complete
**Owner:** Codex implementation agent(s), human architecture review
**Phase-1 baseline:** `main@795b86f412630ba36238c0de1baa1e291ba13863`

## 1. Goal

Validate that the frozen harness can replace its model runtime and analytics MySQL source through
adapter/composition changes rather than behavioral rewrites.

Phase 2 has exactly two milestones:

```text
M16 — Model Provider Portability
M17 — External MySQL Portability
```

M16 must merge and freeze before M17 begins.

## 2. Frozen Phase-1 state

```text
M0–M15                        COMPLETE / FROZEN
M15 Canonical Evaluation      COMPLETE
M15 Behavioral Verdict        REJECTED
Architecture/Harness Baseline VALIDATED

Product NL2SQL MVP            NOT ACCEPTED
Behavioral remediation        NOT AUTHORIZED
MVP release/tag               NOT AUTHORIZED
```

The Phase-1 Golden Dataset, Oracle Dataset, behavioral thresholds, prompts, security policies,
public RequirementState/QueryPlan/ExecutionResult contracts, M8–M15 authorities, and historical
acceptance evidence remain unchanged. Phase 2 does not optimize against the 59 Golden cases.

## 3. Non-goals

Do not add:

- PostgreSQL, ClickHouse, DuckDB, Trino, or another SQL dialect;
- multi-source querying;
- native non-SQL querying;
- document/RAG support;
- an external vector database;
- multi-agent behavior;
- behavioral Golden fitting;
- a release or tag.

One milestone is delivered through one focused PR and stops for substantive review before merge.

## 4. M16 — Model Provider Portability

### Objective

Prove that the application can select either the existing Ollama reference runtime or one narrow
OpenAI-compatible REST conformance profile without provider-specific behavior entering dialogue,
retrieval, planning, repair, answer, verification, conversation orchestration, or evaluation.

### Scope

Implement only:

- provider-neutral runtime composition selected by configuration;
- `OpenAICompatibleChatModel`;
- `OpenAICompatibleEmbeddingModel`;
- `OpenAICompatibleStartupDiagnostics`;
- bounded authenticated JSON transport;
- honest remote identity/fingerprint assurance;
- deterministic conformance tests;
- one bounded real-provider control-flow smoke.

Ollama remains the default/reference provider and retains its immutable digest drift protection.

### Remote conformance profile

The first profile is deliberately narrow:

```text
POST /chat/completions
    messages
    response_format.type = json_schema
    response_format.json_schema.strict = true
    bounded max_completion_tokens

POST /embeddings
    array input
    float vectors indexed one-for-one with inputs

identity profile = openai_models_by_id
    GET /models/{model_id}
    model presence and the strongest identity metadata actually exposed

identity profile = cloudflare_workers_ai
    GET /accounts/{account_id}/ai/models/search?search={model_id}
    exactly one exact configured-name match
    expected Text Generation / Text Embeddings task
    stable task ID, source, and created-at metadata

Authorization: Bearer <secret>
```

The adapter does not claim compatibility with every product using the “OpenAI-compatible” label.
Provider responses remain untrusted and must pass the existing Pydantic/domain policies.

### Identity invariant

Do not fabricate a weights digest. A remote fingerprint binds at least:

```text
provider
base-endpoint identity
model/deployment ID
provider revision/snapshot when exposed
identity assurance
declared adapter capabilities
bounded descriptive provider metadata
```

Initial assurance classes are:

```text
IMMUTABLE_PROVIDER_REVISION
PINNED_DEPLOYMENT
ALIAS_ONLY
```

If the conformance endpoint exposes no revision/snapshot, the adapter records `ALIAS_ONLY` and no
digest/revision. Such evidence may validate portability but cannot be represented as strong
reproducibility or Product acceptance. Existing Ollama fingerprint values continue to bind a real
digest and fail closed on tag drift.

### Transport and contract invariants

- base URL is an absolute credential-free HTTP(S) URL;
- timeout, response bytes, output tokens, and embedding batch size are configured bounds;
- there is no hidden retry;
- every response is a bounded JSON object;
- transport, timeout, provider-status, envelope, and contract failures are typed;
- API keys never appear in errors, logs, traces, model context, or fingerprints;
- structured output is revalidated through the requested Pydantic type;
- embeddings are non-empty, finite, count-exact, index-exact, and dimension-consistent.

### Deterministic acceptance

Tests cover at least:

- provider selection and Ollama default preservation;
- remote chat request and JSON Schema shape;
- malformed/schema-invalid chat output;
- response-size and timeout bounds;
- provider HTTP error mapping and API-key redaction;
- embedding batch, count, index, finite-value, and dimension checks;
- remote diagnostics and stable fingerprint identity;
- alias-only identity honesty and revision drift failure;
- absence of OpenAI-compatible adapter imports/branches from M8–M15 business modules.

Run:

```text
focused M16 tests
task quality
```

### Real REST smoke

After deterministic gates, run one bounded provider smoke under the exact selected remote
configuration. It grades transport/control flow, not product quality:

```text
startup diagnostics                  PASS
one structured Dialogue call         PASS or typed fail-closed
one embedding/retrieval call         PASS
one structured Planner call          PASS or typed fail-closed
one public HTTP conversation path    terminates safely
unsafe READY                         0
unauthorized SQL execution           0
secret leakage                       0
```

Do not change prompts or run the complete M15 suite to make this smoke pass. A full remote-model
M15 run requires separate explicit authorization and a new complete EvaluationEnvironment.

### M16 merge gate

```text
focused M16 tests              PASS
task quality                   PASS
bounded remote REST smoke      PASS control-plane criteria
Delivery / Quality             PASS
substantive review             APPROVE
PR                             CLEAN
```

Stop before merge and do not begin M17.

## 5. M17 — External MySQL Portability

**Status:** ACTIVE — deterministic foundation authorized at
`main@616a37a44c7ca99101fef07dec39a6bc45eb693e`.

M17 replaces only the Analytics/Data Plane MySQL while retaining control-plane persistence. The
first tranche implements control/analytics endpoint separation, one credential-free active source
profile, external-safe non-mutating preflight, explicit table scope, and an independent catalog
workspace. Real external conformance, final PR creation, M15 reruns, release/tag creation, another
SQL dialect, and multi-source behavior are not authorized in this tranche.

## 6. Progress

```text
[x] M16 Model Provider Portability — COMPLETE / FROZEN
[~] M17 External MySQL Portability — READY FOR FOCUSED PR / SUBSTANTIVE REVIEW
```

### M16 closure evidence — 2026-08-30

```text
focused PR                         #19 — SQUASH MERGED
merge SHA                          616a37a44c7ca99101fef07dec39a6bc45eb693e
substantive review                 PASS / APPROVE
Delivery / Quality                 PASS
EvaluationEnvironment v0.2        COMPLETE / FROZEN
Model portability baseline        VALIDATED
Product NL2SQL MVP                 NOT ACCEPTED
release / tag                      NOT AUTHORIZED / NOT CREATED
```

### M16 implementation evidence — 2026-08-30

```text
Phase-1 baseline                    795b86f412630ba36238c0de1baa1e291ba13863
provider-neutral composition       PASS
Ollama default/digest protection   PASS
remote transport/contracts         PASS
remote identity assurance          PASS
provider-isolation invariant       PASS
focused M16 regression             PASS — 86 passed, 1 opt-in live skipped
task bootstrap                     PASS
retrieval-index-v0.2 fingerprint   318a5423d255eae477d41f4c5da5dfb71e2d1a31dcb27bf88b1e4147480862c4
Cloudflare remote bootstrap        PASS — retrieval index 6375bc55f26d1c8e41f21aa25b82076e635018af22f8fa1a1290dbcf73847feb
task quality                       PASS — 544 passed, 8 skipped
30B / M15 59-case evaluation       NOT RUN
bounded real-provider smoke        PASS — 1 passed in 28.93s
provider implementation head       30dfa0f
focused PR                         #19 — OPEN / CLEAN
remote Delivery / Quality          PASS — PR #19 at 30dfa0f
substantive review                 PENDING
```

The deterministic implementation and authorized real-provider gates are complete. M16 remains
active and cannot merge until the focused PR passes remote Delivery / Quality and substantive
review. No Golden, Oracle, prompt, threshold, or M8–M15 behavioral file changed.

### M16 narrow substantive-review remediation — 2026-08-30

```text
EvaluationEnvironment v0.1        PRESERVED / HISTORICAL
EvaluationEnvironment v0.2        PROVIDER-NEUTRAL / NEW RUNS
composition-owned runtime facts   PASS
actual selected timeout/tokens    PASS
provider + assurance binding      PASS
ALIAS_ONLY Product hard gate      PASS
immutable Ollama eligibility      PASS
focused deterministic regression PASS — 71 passed
task quality                      PASS — 548 passed, 8 skipped
Cloudflare live smoke             NOT RERUN — adapter unchanged
M15 59-case evaluation            NOT RUN
remediation implementation head   619395c
remote Delivery / Quality         PASS — PR #19 at 619395c
```

The remediation changes only evaluation identity and final Product-adjudication eligibility.
Golden/Oracle truth, D-035 behavioral and safety thresholds, M8–M14 behavior, model prompts,
Cloudflare adapter behavior, and retrieval semantics remain unchanged. At that closure point M17
remained unauthorized; the later activation baseline is recorded above.

### M17 deterministic foundation evidence — 2026-08-30

```text
protected baseline                    616a37a44c7ca99101fef07dec39a6bc45eb693e
control/analytics endpoint split      PASS
single active source profile          PASS
external synthetic-bootstrap denial  PASS
allowlist-scoped introspection        PASS
bounded read-only preflight           PASS
catalog workspace isolation           PASS
generated fingerprint isolation       PASS
secret-free profile/report/artifacts  PASS
synthetic default regression          PASS
focused M17 regression                PASS — 36 passed
task bootstrap                        PASS
synthetic retrieval fingerprint       318a5423d255eae477d41f4c5da5dfb71e2d1a31dcb27bf88b1e4147480862c4
task quality                          PASS — 560 passed, 8 skipped
real external MySQL connection        NOT RUN / NOT AUTHORIZED IN THIS TRANCHE
M15 59-case evaluation                NOT RUN
final M17 PR                          NOT CREATED
```

This tranche changes only configuration/composition, bounded metadata intake, and local artifact
selection. It does not change planner dialect, retrieval ranking, SQL admission, EXPLAIN policy,
guarded execution, M8–M15 behavior, Golden/Oracle truth, or Product acceptance state. M17 remains
active pending separately authorized real external conformance.

### M17 independent MySQL conformance evidence — 2026-08-30

```text
conformance source                    disposable independent MySQL 8.4.11
analytics / control endpoint split   PASS — 127.0.0.1:3307 / 127.0.0.1:3306
source ID / workspace                product-opinion-conformance
source-profile fingerprint           d7fbab6a75014c3bd997856d42e07ccc60888c3cc817108ee249db4653b6bf40
allowlisted surface                  4 tables / 26 columns / 3 foreign keys
reader privilege                     SELECT on exactly 4 tables; no database wildcard grant
out-of-scope table read              DENIED — MySQL 1142
database write probe                 DENIED — MySQL 1142
table / column comment coverage      1.000 / 1.000
raw opinion text / personal data     NONE / NONE

generated-schema fingerprint         c80817f373f110ceb4b697027edd036edb7a8c27cf8a1d4dc348c269ff317e9a
semantic revision                    ad9891070e19906aaecaeebcbb7fe8a00431555577e67a8c891a4476b2f14f9e
assembled-catalog fingerprint        7cb481d9d151278bb5ad8b2908b670125ca1962466081abc3c31167d855a888f
retrieval-index fingerprint          5b5d4afe04648c5f7a57ad9dd22868bdea406ccd669ecc74acf77b009daef211
embedding fingerprint                0112ea4d6590628288600ebd612ee8b094001c1e181c4eda9a64493d205c138f
embedding identity assurance         IMMUTABLE_PROVIDER_REVISION
Ollama runtime / index format        0.33.1 / retrieval-index-v0.2
retrieval-document builder           retrieval-document-v0.1
hybrid retrieval smoke               PASS — only the 4 governed tables returned
M6 relationship authority            PASS — exactly 3 curated, FK-backed relationships

SQL Guard                            PASS
real JSON EXPLAIN                    PASS — fact/product join admitted
bounded read-only execution          PASS — one attempt, 2 rows, not truncated
product-opinion result               FITNESS_BAND 5/1/0; SMARTWATCH 5/2/1
                                     (events / negative / high-risk)
opt-in external conformance test     PASS — 1 passed
focused deterministic regression     PASS — 27 passed, 1 opt-in live skipped
synthetic task bootstrap             PASS — reference index 318a5423d...
task quality                         PASS — 560 passed, 9 skipped
M15 59-case evaluation               NOT RUN
Product NL2SQL MVP                   NOT ACCEPTED / UNCHANGED
release / tag                        NOT AUTHORIZED / NOT CREATED
```

The external surface contains deterministic synthetic observations for autonomous-driving cars,
smartwatches, and fitness bands. It is an independently located MySQL source used only to prove
portability; it is not production connectivity or Product behavioral evidence. Environment-owner
provisioning created the schema/data and reduced the reader to four table-level `SELECT` grants.
The application path remained non-mutating: bounded metadata intake, in-memory semantic assembly,
retrieval indexing/search, SQL Guard, JSON EXPLAIN, and one capability-only bounded `SELECT`.

### M17 substantive-review remediation evidence — 2026-08-30

```text
review baseline                        PR #20 head 02cec38306e3b9ca3955efae1f17431edcd74656
active profile → generated database   FAIL-CLOSED / PASS
active profile → exact table surface  FAIL-CLOSED / PASS
stale workspace database regression   PASS
stale wider-allowlist regression       PASS

MYSQL_ROOT_PASSWORD setting           OPTIONAL
external Settings with root=None      PASS
external preflight with root=None     PASS — deterministic connection evidence
runtime/EXPLAIN redaction root=None   PASS
synthetic bootstrap root=None         TYPED FAIL before container/admin operation
control migration root=None           TYPED FAIL before admin connection
live external unusable admin secret   PASS — preflight + conformance 1 passed

focused blocker regression            PASS — 69 passed
synthetic task bootstrap               PASS — reference index 318a5423d...
task quality                           PASS — 565 passed, 9 skipped
M15 59-case evaluation                 NOT RUN
M8–M15 / Golden / Oracle / thresholds UNCHANGED
release / tag                          NOT AUTHORIZED / NOT CREATED
```

The remediation changes only source-authority admission and admin-credential configuration.
Current catalog loading now rejects workspace artifacts before curated/assembled/index use when
their generated database or exact table surface differs from the active profile. External runtime
composition no longer requires an admin secret; every operation that actually needs root authority
uses one explicit fail-closed credential guard.

## 7. Decision log

### 2026-08-30 — M16 OpenAI-compatible profile and honest identity

**Decision:** Keep the existing model Ports. Select providers only through model-runtime
composition. Implement one Chat Completions + Embeddings + model-descriptor conformance profile
using bounded standard-library HTTP. Preserve Ollama as the default. Evolve internal
`ModelFingerprint` identity metadata only as necessary to represent endpoint, optional provider
revision, and assurance; an alias-only remote model has no fabricated digest.

**Evidence:** Phase-1 services already accept provider-neutral `ChatModel`, `EmbeddingModel`, and
`ModelRuntimeDiagnostics`. The remaining hard bindings are composition helpers and Ollama-only
configuration. Standard remote model descriptors do not guarantee a weights digest or runtime
version, so pretending that a mutable model alias is immutable would weaken M7/M15 identity.

**Consequences:** Remote portability can be proven without changing M8–M15 behavioral authority.
Remote indexes bind the weaker but explicit identity and stale-check against it. A future provider
profile that exposes a verifiable immutable revision may raise assurance; `ALIAS_ONLY` evidence
cannot independently authorize Product acceptance.

### 2026-08-30 — M16 retrieval identity format amendment

**Decision:** Advance only the generated retrieval-index identity format from
`retrieval-index-v0.1` to `retrieval-index-v0.2` so the persisted embedding identity includes
optional digest, endpoint identity, optional provider revision, and assurance.

**Evidence:** The v0.1 Pydantic identity required a non-empty digest and could not serialize an
honest alias-only remote model. Adding fields while retaining the same format version would make
old and new canonical fingerprints ambiguous.

**Consequences:** Existing generated v0.1 indexes fail closed and rebuild. M7 document projection,
cosine search, BM25, RRF, seed selection, relationship expansion, and eval gates are unchanged.

### 2026-08-30 — Explicit Cloudflare Workers AI identity profile

**Decision:** Preserve `GET /models/{id}` as the default identity source and add only the explicit
`cloudflare_workers_ai` identity profile. That profile accepts exactly the official Workers AI
OpenAI-compatible base shape, derives the same-account model-catalog endpoint, and requires one
exact configured-name match with the expected `Text Generation` or `Text Embeddings` task before
startup and every model request. Stable catalog task/source/creation metadata is fingerprinted;
provider revision and digest remain absent, so assurance is `ALIAS_ONLY`.

**Evidence:** The authorized Cloudflare conformance run reached the configured provider, but
`GET /models/{id}` returned HTTP 405. Cloudflare documents only Chat Completions and Embeddings on
its OpenAI-compatible surface, while its authenticated account model catalog uniquely returned the
configured Chat and Embedding aliases and governed task classifications. Token verification passed.

**Consequences:** There is no automatic fallback and no weakening of the standard profile. Missing,
ambiguous, task-mismatched, or changed Cloudflare catalog evidence fails closed. The change remains
inside `model_runtime`; M8–M15 behavior, prompts, Golden/Oracle truth, and product thresholds are
unchanged.

### 2026-08-30 — Provider-neutral evaluation identity and Product eligibility

**Decision:** Preserve `EvaluationEnvironment v0.1` exactly for historical Phase-1 evidence and
issue `evaluation-environment-v0.2` for every new canonical run. The new environment consumes the
provider, runtime version, model fingerprints/assurances, request timeout, and output-token bound
from composition-owned selected-runtime evidence. It does not reselect provider-specific settings
inside `eval_harness`.

**Evidence:** The M16 review found that the v0.1 builder always recorded `settings.ollama_*`, even
when composition selected the OpenAI-compatible provider. Deterministic regressions now use
deliberately different Ollama and remote bounds and prove that v0.2 records the remote values,
both identity assurances, and the provider. Additional regressions prove alias-only denial,
immutable Ollama eligibility, and byte-for-byte field preservation when parsing v0.1.

**Consequences:** `ALIAS_ONLY` remains valid for M16 smoke and diagnostic/model-effect evidence,
but it cannot independently make the canonical Product verdict pass even when ordinary stage,
behavioral, and safety gates pass. Immutable Ollama digest identities remain eligible. D-035
thresholds and all Golden/Oracle truth remain unchanged; no model run is required for this
evaluation-control-plane amendment.

### 2026-08-30 — M17 single-source profile and external-safe preflight

**Decision:** Retain `MYSQL_HOST`/`MYSQL_PORT` as the analytics endpoint for local compatibility
and add independent control host/port settings. Compose exactly one active credential-free source
profile from configuration. Preserve the synthetic `catalog/generated` + `catalog/semantic`
workspace; place an external source beneath `catalog/workspaces/<workspace-id>`. External
preflight uses only the analytics reader and allowlist-scoped metadata queries. Synthetic admin
bootstrap remains a separate, mode-guarded path.

**Evidence:** Phase-1 control repositories, migrations, analytics introspection, EXPLAIN, and query
runtime all read the same host/port fields, while generated/semantic/index loaders use global path
constants. Without separation, external mode could reach admin provisioning and overwrite the
synthetic authority. `GeneratedSchemaMetadata v0.1` already supplies the correct provider-neutral
downstream boundary once introspection is scoped.

**Consequences:** The first tranche can be proven entirely with deterministic connection doubles
and the existing synthetic world. Real credentials and live external MySQL are deferred until the
non-mutating path, workspace isolation, semantic assembly, and retrieval identity compose. Missing
FK evidence remains a blocker rather than an invitation to infer relationships.

### 2026-08-30 — M17 disposable product-opinion conformance source

**Decision:** Use a short-lived, independently located MySQL 8.4 source to close the live M17
composition gate. The environment owner provisions four commented tables and deterministic
synthetic observations covering autonomous-driving cars, smartwatches, and fitness bands. The
application sees only the explicitly configured four-table surface through a reader with matching
table-level grants. Stable curated semantics live in the external workspace; generated schema,
assembled catalog, and retrieval index remain ignored rebuildable artifacts.

**Evidence:** The real preflight observed 4 tables, 26 columns, 3 single-column foreign keys, and
complete table/column comments. Semantic assembly and an immutable-digest Ollama embedding index
bound distinct generated, curated, catalog, and index fingerprints. A representative wearable
opinion query traversed SQL Guard, MySQL JSON EXPLAIN, and one bounded read-only execution. An
existing physical table outside the configured surface was denied by MySQL privileges.

**Consequences:** This profile proves one external analytics source can compose without changing
the MySQL dialect, planner, retrieval semantics, Guard/EXPLAIN/runtime policy, M8–M15 behavior, or
control-plane persistence. The fixture contains no raw opinion text or personal data and provides
no Product acceptance evidence. It does not authorize production credentials, multi-source
queries, M15 replay, a release, or a tag.

### 2026-08-30 — M17 active-scope binding and on-demand admin credential

**Decision:** Treat workspace paths as artifact locations, not sufficient authority. Before current
catalog loading, compare generated schema database and exact ordered table names with the active
`AnalyticsSourceProfile`; any mismatch is typed stale authority. Keep host/port outside this check.
Make `MYSQL_ROOT_PASSWORD` optional in `Settings`, and require it through one shared helper only
when synthetic bootstrap, control migration, principal provisioning, or verification explicitly
enters an admin path.

**Evidence:** Review found that a reused workspace could retain a removed table or a generated
snapshot from another database, while runtime configuration had already changed. Review also found
that a pure external reader configuration could not construct `Settings` without an unused root
secret. New regressions cover both stale scopes, exact `None` external configuration/preflight,
rootless EXPLAIN error handling, and pre-connection denial for synthetic bootstrap/control migration.

**Consequences:** Allowlist/database changes become immediate runtime authority and require artifact
rebuild before startup can continue. A logical source may still move between hosts without artifact
invalidation. External analytics needs reader credentials only; local synthetic/control admin work
still fails closed unless explicitly configured. No SQL, retrieval ranking, model, M8–M15, or
Product acceptance behavior changes.

## 8. Deviation rule

If a frozen boundary proves impossible to compose:

1. stop that implementation branch;
2. record the concrete failing assumption and a regression;
3. propose the smallest architecture amendment;
4. do not change behavior or truth sources without substantive authorization.
