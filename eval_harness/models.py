"""Strict source and report models for final MVP acceptance."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_agent.model_runtime.ports import ModelIdentityAssurance


class _EvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class GoldenTurn(_EvalModel):
    content: str = Field(min_length=1)
    expected_type: Literal["clarification", "result", "failure"]


class GoldenCase(_EvalModel):
    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]+$")
    category: Literal[
        "simple",
        "aggregation",
        "join_trap",
        "multi_turn",
        "failure",
        "repair_empty",
    ]
    turns: tuple[GoldenTurn, ...] = Field(min_length=1, max_length=3)
    required_tables: tuple[str, ...]
    expected_columns: tuple[str, ...]
    oracle: str | None = None
    repair_expectation: Literal["FORBIDDEN", "ALLOWED", "REQUIRED"] = "ALLOWED"

    @model_validator(mode="after")
    def expectation_is_coherent(self) -> Self:
        final_type = self.turns[-1].expected_type
        if final_type == "result":
            if self.oracle is None or not self.required_tables or not self.expected_columns:
                raise ValueError("result Golden case requires oracle, tables, and columns")
        elif self.oracle is not None or self.expected_columns:
            raise ValueError("non-result Golden case cannot carry a result Oracle")
        if self.category == "multi_turn" and len(self.turns) < 2:
            raise ValueError("multi-turn Golden case requires at least two turns")
        return self


class GoldenSuite(_EvalModel):
    version: Literal["golden-v0.1"]
    cases: tuple[GoldenCase, ...] = Field(min_length=50)

    @model_validator(mode="after")
    def coverage_is_frozen(self) -> Self:
        ids = [case.id for case in self.cases]
        categories = {case.category for case in self.cases}
        required = {"simple", "aggregation", "join_trap", "multi_turn", "failure", "repair_empty"}
        if len(ids) != len(set(ids)) or categories != required:
            raise ValueError("Golden cases are duplicated or category coverage is incomplete")
        return self


class OracleSuite(_EvalModel):
    version: Literal["oracle-v0.1"]
    queries: dict[str, str] = Field(min_length=1)


class EvaluationEnvironmentV01(_EvalModel):
    """Historical Phase-1 identity retained for exact report validation."""

    version: Literal["evaluation-environment-v0.1"] = "evaluation-environment-v0.1"
    git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    golden_version: str
    golden_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_schema_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_index_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    chat_model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    ollama_runtime_version: str
    ollama_request_timeout_seconds: float = Field(gt=0)
    ollama_max_output_tokens: int = Field(ge=256)
    dialogue_prompt_version: str
    planning_prompt_version: str
    repair_prompt_version: str
    answer_prompt_version: str
    sql_guard_policy_version: str
    explain_policy_version: str
    query_runtime_policy_version: str
    verification_policy_version: str
    repair_policy_version: str
    answer_grounding_policy_version: str
    trace_schema_version: str
    evaluation_timezone: Literal["UTC"] = "UTC"
    python_version: str
    dependency_lock_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvaluationEnvironmentV02(_EvalModel):
    """Provider-neutral identity for all newly issued canonical evaluations."""

    version: Literal["evaluation-environment-v0.2"] = "evaluation-environment-v0.2"
    git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    golden_version: str
    golden_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_schema_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_index_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_provider: str = Field(min_length=1, pattern=r"\S")
    model_runtime_version: str = Field(min_length=1, pattern=r"\S")
    chat_model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    chat_identity_assurance: ModelIdentityAssurance
    embedding_model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_identity_assurance: ModelIdentityAssurance
    model_request_timeout_seconds: float = Field(gt=0)
    model_max_output_tokens: int = Field(ge=256)
    product_acceptance_identity_eligible: bool
    dialogue_prompt_version: str
    planning_prompt_version: str
    repair_prompt_version: str
    answer_prompt_version: str
    sql_guard_policy_version: str
    explain_policy_version: str
    query_runtime_policy_version: str
    verification_policy_version: str
    repair_policy_version: str
    answer_grounding_policy_version: str
    trace_schema_version: str
    evaluation_timezone: Literal["UTC"] = "UTC"
    python_version: str
    dependency_lock_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def product_eligibility_matches_identity_assurance(self) -> Self:
        eligible = all(
            assurance is not ModelIdentityAssurance.ALIAS_ONLY
            for assurance in (
                self.chat_identity_assurance,
                self.embedding_identity_assurance,
            )
        )
        if self.product_acceptance_identity_eligible is not eligible:
            raise ValueError(
                "Product acceptance identity eligibility does not match model assurance"
            )
        return self


type EvaluationEnvironment = Annotated[
    EvaluationEnvironmentV01 | EvaluationEnvironmentV02,
    Field(discriminator="version"),
]


class GoldenCaseResult(_EvalModel):
    id: str
    category: str
    passed: bool
    session_id: str
    response_types: tuple[str, ...]
    run_ids: tuple[str, ...]
    run_statuses: tuple[str, ...]
    run_error_codes: tuple[str | None, ...]
    trace_event_ids: tuple[str, ...]
    trace_payload_fingerprints: tuple[str, ...]
    failed_trace_events: tuple[str, ...]
    observed_tables: tuple[str, ...]
    observed_columns: tuple[str, ...]
    failure_stage: str | None
    oracle_passed: bool | None
    trace_passed: bool
    repair_count: int = Field(ge=0)
    errors: tuple[str, ...]


class GoldenMetrics(_EvalModel):
    case_count: int = Field(ge=50)
    result_case_count: int = Field(ge=1)
    e2e_pass_rate: float = Field(ge=0, le=1)
    result_oracle_pass_rate: float = Field(ge=0, le=1)
    trace_integrity_rate: float = Field(ge=0, le=1)
    unnecessary_clarification_rate: float = Field(ge=0, le=1)
    unauthorized_execution_count: int = Field(ge=0)
    failed_verification_synthesis_count: int = Field(ge=0)
    numeric_grounding_violation_count: int = Field(ge=0)
    repair_bound_violation_count: int = Field(ge=0)
    verified_oracle_mismatch_count: int = Field(ge=0)


class GoldenReport(_EvalModel):
    version: Literal["golden-report-v0.1"] = "golden-report-v0.1"
    environment: EvaluationEnvironment
    metrics: GoldenMetrics
    cases: tuple[GoldenCaseResult, ...]
    passed: bool


class FinalAcceptanceReport(_EvalModel):
    version: Literal["mvp-acceptance-v0.1"] = "mvp-acceptance-v0.1"
    environment: EvaluationEnvironment
    stages: dict[str, dict[str, Any]]
    golden: GoldenReport
    passed: bool

    @model_validator(mode="after")
    def product_acceptance_requires_eligible_identity(self) -> Self:
        if (
            self.passed
            and isinstance(self.environment, EvaluationEnvironmentV02)
            and not self.environment.product_acceptance_identity_eligible
        ):
            raise ValueError("Product acceptance requires eligible model identity assurance")
        return self
