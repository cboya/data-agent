"""Standalone M9 planner evaluation without SQL parsing or execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Self

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from data_agent.catalog.semantic import AssembledSemanticCatalog
from data_agent.contracts.query import QueryPlan
from data_agent.contracts.requirement import RequirementState, RequirementStatus
from data_agent.contracts.retrieval import RetrievalHit, RetrievalResult
from data_agent.model_runtime.errors import ModelAdapterError
from data_agent.model_runtime.ports import ModelFingerprint
from data_agent.planning.errors import PlannerError, PlannerEvaluationError, PlannerPolicyError
from data_agent.planning.prompt import PLANNER_PROMPT_VERSION
from data_agent.planning.service import QueryPlanner

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PLANNER_EVAL_PATH = REPOSITORY_ROOT / "evals" / "planner.yaml"
PLANNER_REPORT_PATH = REPOSITORY_ROOT / "evals" / "reports" / "planner-latest.json"
OUT_OF_CONTEXT_PROBE_TABLE = "__m9_out_of_context_table__"


class _UniqueKeySafeLoader(yaml.SafeLoader):  # type: ignore[misc]
    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
        self.flatten_mapping(node)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as error:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable mapping key",
                    key_node.start_mark,
                ) from error
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key: {key}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


class _EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class PlannerEvalCase(_EvaluationModel):
    id: str = Field(min_length=1, pattern=r"\S")
    category: Literal[
        "single_table",
        "time_grain",
        "metric_semantics",
        "dimension_join",
        "relationship_path",
        "payment_attempt",
        "refund_net_revenue",
        "fan_out",
        "irrelevant_context",
        "expected_shape",
        "catalog_injection",
    ]
    requirement: RequirementState
    retrieved_tables: tuple[str, ...] = Field(min_length=1, max_length=8)
    required_tables: tuple[str, ...] = Field(min_length=1)
    expected_columns: tuple[str, ...] = Field(min_length=1)
    required_sql_terms: tuple[str, ...] = ()
    forbidden_sql_terms: tuple[str, ...] = ()

    @model_validator(mode="after")
    def case_is_ready_and_bounded(self) -> Self:
        if self.requirement.status is not RequirementStatus.READY:
            raise ValueError("planner eval requirement must be READY")
        for name, values in (
            ("retrieved tables", self.retrieved_tables),
            ("required tables", self.required_tables),
            ("expected columns", self.expected_columns),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"planner eval {name} must be unique")
        if not set(self.required_tables) <= set(self.retrieved_tables):
            raise ValueError("planner eval required tables must be retrieved")
        return self


class PlannerEvalSuite(_EvaluationModel):
    version: Literal["v0.1"]
    cases: tuple[PlannerEvalCase, ...] = Field(min_length=20, max_length=30)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> Self:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("planner eval case ids must be unique")
        return self


class PlannerCaseEvalResult(_EvaluationModel):
    id: str
    category: str
    retrieved_tables: tuple[str, ...]
    required_tables: tuple[str, ...]
    proposal: QueryPlan | None = None
    structured_plan_parsed: bool
    allowed_table_compliant: bool
    out_of_context_probe_rejected: bool
    required_table_recall: float = Field(ge=0, le=1)
    plan_table_precision: float = Field(ge=0, le=1)
    exact_required_table_set: bool
    expected_column_accuracy: float = Field(ge=0, le=1)
    representative_sql_generated: bool
    errors: tuple[str, ...] = ()


class PlannerEvalMetrics(_EvaluationModel):
    case_count: int = Field(ge=20, le=30)
    structured_plan_parse_rate: float = Field(ge=0, le=1)
    allowed_table_compliance: float = Field(ge=0, le=1)
    out_of_context_declared_table_rejection: float = Field(ge=0, le=1)
    required_table_recall: float = Field(ge=0, le=1)
    plan_table_precision: float = Field(ge=0, le=1)
    exact_required_table_set_accuracy: float = Field(ge=0, le=1)
    expected_column_accuracy: float = Field(ge=0, le=1)
    representative_sql_generation_rate: float = Field(ge=0, le=1)


class PlannerEvalIdentity(_EvaluationModel):
    suite_version: str
    prompt_version: str
    provider: str
    model: str
    model_digest: str | None
    model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_version: str
    retrieval_index_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_schema_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class PlannerEvalReport(_EvaluationModel):
    version: Literal["v0.1"] = "v0.1"
    identity: PlannerEvalIdentity
    metrics: PlannerEvalMetrics
    cases: tuple[PlannerCaseEvalResult, ...]
    passed: bool
    epistemic_boundary: Literal[
        "proposal-only; no SQL parsing, execution, or result correctness claim"
    ] = "proposal-only; no SQL parsing, execution, or result correctness claim"


def load_planner_eval_suite(path: Path = PLANNER_EVAL_PATH) -> PlannerEvalSuite:
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeySafeLoader)
        return PlannerEvalSuite.model_validate(payload)
    except (OSError, yaml.YAMLError, ValidationError) as error:
        raise PlannerEvaluationError("planner evaluation suite is missing or invalid") from error


def _frozen_retrieval_result(
    case: PlannerEvalCase,
    *,
    catalog: AssembledSemanticCatalog,
    index_fingerprint: str,
) -> RetrievalResult:
    selected = set(case.retrieved_tables)
    relationships = [
        relationship
        for relationship in catalog.relationships
        if str(relationship.from_table) in selected and str(relationship.to_table) in selected
    ]
    return RetrievalResult(
        version="v0.1",
        query=str(case.requirement.goal or case.id),
        hits=[
            RetrievalHit(
                table=table,
                lexical_rank=rank if rank <= 4 else None,
                semantic_rank=rank if rank <= 4 else None,
                fused_score=1.0 / rank if rank <= 4 else 0.0,
                reason="frozen planner eval schema slice",
                source="SEED" if rank <= 4 else "GRAPH_EXPANSION",
            )
            for rank, table in enumerate(case.retrieved_tables, start=1)
        ],
        relationships=relationships,
        index_fingerprint=index_fingerprint,
    )


def _evaluation_error(error: Exception) -> str:
    cause = error.__cause__
    if isinstance(cause, ValidationError):
        details = "; ".join(
            f"{'.'.join(str(value) for value in item['loc'])}: {item['msg']}"
            for item in cause.errors(include_input=False)[:5]
        )
        return f"{type(error).__name__}: {details}"
    return f"{type(error).__name__}: {error}"


def _score_case(
    case: PlannerEvalCase,
    proposal: QueryPlan | None,
    *,
    accepted: bool,
) -> tuple[float, float, bool, float, bool]:
    if proposal is None or not accepted:
        return 0.0, 0.0, False, 0.0, False
    planned = {str(table) for table in proposal.tables}
    required = set(case.required_tables)
    required_recall = len(planned & required) / len(required)
    table_precision = len(planned & required) / len(planned) if planned else 0.0
    exact = planned == required
    actual_columns = {str(column.name) for column in proposal.expected_columns}
    expected_columns = set(case.expected_columns)
    column_accuracy = len(actual_columns & expected_columns) / len(expected_columns)
    sql = str(proposal.sql).casefold()

    def evidence_term(term: str) -> str:
        """Tolerate SQL aliases without claiming to parse or authorize the SQL."""
        folded = term.casefold()
        if "." in folded and folded.split(".", 1)[0].startswith(("fact_", "dim_")):
            return folded.split(".", 1)[1]
        return folded

    representative = all(evidence_term(term) in sql for term in case.required_sql_terms) and all(
        evidence_term(term) not in sql for term in case.forbidden_sql_terms
    )
    return required_recall, table_precision, exact, column_accuracy, representative


async def run_planner_evaluation(
    planner: QueryPlanner,
    *,
    suite: PlannerEvalSuite,
    catalog: AssembledSemanticCatalog,
    retrieval_index_fingerprint: str,
    chat_fingerprint: ModelFingerprint,
    runtime_version: str,
) -> PlannerEvalReport:
    results: list[PlannerCaseEvalResult] = []
    for case in suite.cases:
        proposal: QueryPlan | None = None
        parsed = False
        accepted = False
        probe_rejected = False
        errors: list[str] = []
        try:
            retrieval = _frozen_retrieval_result(
                case,
                catalog=catalog,
                index_fingerprint=retrieval_index_fingerprint,
            )
            context = planner.build_context(
                requirement=case.requirement,
                retrieval=retrieval,
                catalog=catalog,
                expected_retrieval_index_fingerprint=retrieval_index_fingerprint,
            )
            proposal = await planner.propose(context)
            parsed = True
            try:
                planner.accept(context=context, proposal=proposal)
                accepted = True
            except PlannerPolicyError as error:
                errors.append(_evaluation_error(error))

            probe = proposal.model_copy(
                update={"tables": [*proposal.tables, OUT_OF_CONTEXT_PROBE_TABLE]}
            )
            try:
                planner.accept(context=context, proposal=probe)
            except PlannerPolicyError:
                probe_rejected = True
            if not probe_rejected:
                errors.append("out-of-context declared-table probe was accepted")
        except (PlannerError, ModelAdapterError, ValidationError, ValueError) as error:
            errors.append(_evaluation_error(error))

        recall, precision, exact, column_accuracy, representative = _score_case(
            case,
            proposal,
            accepted=accepted,
        )
        results.append(
            PlannerCaseEvalResult(
                id=case.id,
                category=case.category,
                retrieved_tables=case.retrieved_tables,
                required_tables=case.required_tables,
                proposal=proposal,
                structured_plan_parsed=parsed,
                allowed_table_compliant=accepted,
                out_of_context_probe_rejected=probe_rejected,
                required_table_recall=recall,
                plan_table_precision=precision,
                exact_required_table_set=exact,
                expected_column_accuracy=column_accuracy,
                representative_sql_generated=representative,
                errors=tuple(errors),
            )
        )

    count = len(results)
    metrics = PlannerEvalMetrics(
        case_count=count,
        structured_plan_parse_rate=sum(result.structured_plan_parsed for result in results) / count,
        allowed_table_compliance=sum(result.allowed_table_compliant for result in results) / count,
        out_of_context_declared_table_rejection=(
            sum(result.out_of_context_probe_rejected for result in results) / count
        ),
        required_table_recall=sum(result.required_table_recall for result in results) / count,
        plan_table_precision=sum(result.plan_table_precision for result in results) / count,
        exact_required_table_set_accuracy=(
            sum(result.exact_required_table_set for result in results) / count
        ),
        expected_column_accuracy=(
            sum(result.expected_column_accuracy for result in results) / count
        ),
        representative_sql_generation_rate=(
            sum(result.representative_sql_generated for result in results) / count
        ),
    )
    return PlannerEvalReport(
        identity=PlannerEvalIdentity(
            suite_version=suite.version,
            prompt_version=PLANNER_PROMPT_VERSION,
            provider=chat_fingerprint.provider,
            model=chat_fingerprint.model,
            model_digest=chat_fingerprint.digest,
            model_fingerprint=chat_fingerprint.value,
            runtime_version=runtime_version,
            retrieval_index_fingerprint=retrieval_index_fingerprint,
            catalog_fingerprint=catalog.catalog_fingerprint,
            generated_schema_fingerprint=catalog.generated_metadata_fingerprint,
            semantic_revision=catalog.semantic_revision,
        ),
        metrics=metrics,
        cases=tuple(results),
        passed=(
            metrics.structured_plan_parse_rate == 1.0
            and metrics.allowed_table_compliance == 1.0
            and metrics.out_of_context_declared_table_rejection == 1.0
            and metrics.required_table_recall >= 0.95
            and metrics.plan_table_precision >= 0.90
            and metrics.exact_required_table_set_accuracy >= 0.90
            and metrics.expected_column_accuracy >= 0.90
        ),
    )


def write_planner_eval_report(
    report: PlannerEvalReport,
    *,
    output_path: Path = PLANNER_REPORT_PATH,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    try:
        temporary_path.write_text(serialized, encoding="utf-8")
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def format_planner_eval_summary(report: PlannerEvalReport) -> str:
    metrics = report.metrics
    status = "PASS" if report.passed else "FAIL"
    return (
        f"Planner eval {status}: cases={metrics.case_count}, "
        f"parse={metrics.structured_plan_parse_rate:.3f}, "
        f"allowed={metrics.allowed_table_compliance:.3f}, "
        f"escape_rejection={metrics.out_of_context_declared_table_rejection:.3f}, "
        f"table_recall={metrics.required_table_recall:.3f}, "
        f"table_precision={metrics.plan_table_precision:.3f}, "
        f"exact_set={metrics.exact_required_table_set_accuracy:.3f}, "
        f"columns={metrics.expected_column_accuracy:.3f}, "
        f"representative_sql={metrics.representative_sql_generation_rate:.3f}"
    )
