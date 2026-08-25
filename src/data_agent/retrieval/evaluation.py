"""Standalone retrieval evaluation isolated from dialogue, planning, SQL, and synthesis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Self

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from data_agent.retrieval.errors import RetrievalEvaluationError
from data_agent.retrieval.index import RetrievalIndex
from data_agent.retrieval.service import HybridRetriever, relationship_id

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RETRIEVAL_EVAL_PATH = REPOSITORY_ROOT / "evals" / "retrieval.yaml"
RETRIEVAL_REPORT_PATH = REPOSITORY_ROOT / "evals" / "reports" / "retrieval-latest.json"


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


class RetrievalEvalCase(_EvaluationModel):
    id: str = Field(min_length=1, pattern=r"\S")
    query: str = Field(min_length=1, pattern=r"\S")
    required_tables: tuple[str, ...] = Field(min_length=1)
    relationship_path: tuple[str, ...] = ()

    @model_validator(mode="after")
    def required_values_are_unique(self) -> Self:
        if len(self.required_tables) != len(set(self.required_tables)):
            raise ValueError("retrieval eval required tables must be unique")
        if len(self.relationship_path) != len(set(self.relationship_path)):
            raise ValueError("retrieval eval relationship path entries must be unique")
        return self


class RetrievalEvalSuite(_EvaluationModel):
    version: Literal["v0.1"]
    cases: tuple[RetrievalEvalCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> Self:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("retrieval eval case ids must be unique")
        return self


class RetrievalCaseResult(_EvaluationModel):
    id: str
    query: str
    required_tables: tuple[str, ...]
    seed_tables: tuple[str, ...]
    final_tables: tuple[str, ...]
    seed_recall_at_5: float = Field(ge=0, le=1)
    seed_recall_at_10: float = Field(ge=0, le=1)
    final_recall_at_5: float = Field(ge=0, le=1)
    final_recall_at_10: float = Field(ge=0, le=1)
    final_precision_at_5: float = Field(ge=0, le=1)
    relationship_path_recovered: bool | None


class RetrievalEvalMetrics(_EvaluationModel):
    case_count: int = Field(ge=1)
    seed_recall_at_5: float = Field(ge=0, le=1)
    seed_recall_at_10: float = Field(ge=0, le=1)
    final_recall_at_5: float = Field(ge=0, le=1)
    final_recall_at_10: float = Field(ge=0, le=1)
    final_precision_at_5: float = Field(ge=0, le=1)
    mean_final_table_count: float = Field(ge=0)
    relationship_path_recovery: float = Field(ge=0, le=1)
    relationship_path_case_count: int = Field(ge=0)


class RetrievalEvalReport(_EvaluationModel):
    version: Literal["v0.1"] = "v0.1"
    index_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    index_identity: dict[str, object]
    metrics: RetrievalEvalMetrics
    cases: tuple[RetrievalCaseResult, ...]
    recall_at_5_target: float = 0.90
    recall_at_10_target: float = 0.95
    passed: bool


def load_retrieval_eval_suite(path: Path = RETRIEVAL_EVAL_PATH) -> RetrievalEvalSuite:
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeySafeLoader)
        return RetrievalEvalSuite.model_validate(payload)
    except (OSError, yaml.YAMLError, ValidationError) as error:
        raise RetrievalEvaluationError(
            "retrieval evaluation suite is missing or invalid"
        ) from error


def _recall(ranking: tuple[str, ...], required: set[str], limit: int) -> float:
    return len(required & set(ranking[:limit])) / len(required)


def _precision(ranking: tuple[str, ...], required: set[str], limit: int) -> float:
    considered = ranking[:limit]
    return len(required & set(considered)) / len(considered) if considered else 0.0


async def run_retrieval_evaluation(
    retriever: HybridRetriever,
    *,
    index: RetrievalIndex,
    suite: RetrievalEvalSuite,
) -> RetrievalEvalReport:
    case_results: list[RetrievalCaseResult] = []
    for case in suite.cases:
        trace = await retriever.retrieve(case.query)
        seed_tables = tuple(str(hit.table) for hit in trace.fused_candidates)
        final_tables = tuple(str(hit.table) for hit in trace.result.hits)
        required = set(case.required_tables)
        available_relationships = {
            relationship_id(relationship) for relationship in trace.result.relationships
        }
        path_recovered = (
            set(case.relationship_path) <= available_relationships
            if case.relationship_path
            else None
        )
        case_results.append(
            RetrievalCaseResult(
                id=case.id,
                query=case.query,
                required_tables=case.required_tables,
                seed_tables=seed_tables,
                final_tables=final_tables,
                seed_recall_at_5=_recall(seed_tables, required, 5),
                seed_recall_at_10=_recall(seed_tables, required, 10),
                final_recall_at_5=_recall(final_tables, required, 5),
                final_recall_at_10=_recall(final_tables, required, 10),
                final_precision_at_5=_precision(final_tables, required, 5),
                relationship_path_recovered=path_recovered,
            )
        )

    count = len(case_results)
    path_results = [
        result.relationship_path_recovered
        for result in case_results
        if result.relationship_path_recovered is not None
    ]
    metrics = RetrievalEvalMetrics(
        case_count=count,
        seed_recall_at_5=sum(result.seed_recall_at_5 for result in case_results) / count,
        seed_recall_at_10=sum(result.seed_recall_at_10 for result in case_results) / count,
        final_recall_at_5=sum(result.final_recall_at_5 for result in case_results) / count,
        final_recall_at_10=sum(result.final_recall_at_10 for result in case_results) / count,
        final_precision_at_5=sum(result.final_precision_at_5 for result in case_results) / count,
        mean_final_table_count=sum(len(result.final_tables) for result in case_results) / count,
        relationship_path_recovery=(
            sum(result is True for result in path_results) / len(path_results)
            if path_results
            else 1.0
        ),
        relationship_path_case_count=len(path_results),
    )
    return RetrievalEvalReport(
        index_fingerprint=index.fingerprint,
        index_identity=index.identity.model_dump(mode="json"),
        metrics=metrics,
        cases=tuple(case_results),
        passed=metrics.final_recall_at_5 >= 0.90 and metrics.final_recall_at_10 >= 0.95,
    )


def write_retrieval_eval_report(
    report: RetrievalEvalReport,
    *,
    output_path: Path = RETRIEVAL_REPORT_PATH,
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


def format_retrieval_eval_summary(report: RetrievalEvalReport) -> str:
    metrics = report.metrics
    status = "PASS" if report.passed else "FAIL"
    return (
        f"Retrieval eval {status}: cases={metrics.case_count}, "
        f"seed_recall@5={metrics.seed_recall_at_5:.3f}, "
        f"seed_recall@10={metrics.seed_recall_at_10:.3f}, "
        f"final_recall@5={metrics.final_recall_at_5:.3f}, "
        f"final_recall@10={metrics.final_recall_at_10:.3f}, "
        f"path_recovery={metrics.relationship_path_recovery:.3f}, "
        f"mean_tables={metrics.mean_final_table_count:.2f}"
    )
