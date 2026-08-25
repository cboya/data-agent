"""Internal immutable identities issued by deterministic M10 admission."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from data_agent.contracts.execution import ExplainResult, GuardStatus, SQLGuardResult
from data_agent.contracts.query import QueryPlan

_CAPABILITY_TOKEN = object()


@dataclass(frozen=True, order=True)
class PhysicalTable:
    schema: str | None
    name: str

    @property
    def qualified_name(self) -> str:
        return self.name if self.schema is None else f"{self.schema}.{self.name}"


def _sql_digest(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _query_plan_fingerprint(plan: QueryPlan) -> str:
    canonical = json.dumps(
        plan.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GuardedSQL:
    """Post-guard, pre-EXPLAIN candidate; only the Harness provider may consume it."""

    sql: str
    sql_digest: str
    query_plan_fingerprint: str
    physical_tables: tuple[PhysicalTable, ...]
    guard_result: SQLGuardResult
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _CAPABILITY_TOKEN:
            raise ValueError("GuardedSQL can only be issued by SQLGuard")
        if self.guard_result.status is not GuardStatus.PASSED:
            raise ValueError("GuardedSQL requires passed guard evidence")
        if self.sql_digest != _sql_digest(self.sql):
            raise ValueError("GuardedSQL SQL digest mismatch")


@dataclass(frozen=True)
class GuardedQuery:
    """M10 execution capability for future M11; not a public domain contract."""

    sql: str
    sql_digest: str
    query_plan_fingerprint: str
    physical_tables: tuple[PhysicalTable, ...]
    guard_result: SQLGuardResult
    explain_result: ExplainResult
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _CAPABILITY_TOKEN:
            raise ValueError("GuardedQuery can only be issued by M10 admission")
        if self.guard_result.status is not GuardStatus.PASSED:
            raise ValueError("GuardedQuery requires passed guard evidence")
        if not self.explain_result.accepted:
            raise ValueError("GuardedQuery requires accepted EXPLAIN evidence")
        if self.sql_digest != _sql_digest(self.sql):
            raise ValueError("GuardedQuery SQL digest mismatch")


def issue_guarded_sql(
    plan: QueryPlan,
    *,
    physical_tables: tuple[PhysicalTable, ...],
    guard_result: SQLGuardResult,
) -> GuardedSQL:
    sql = str(plan.sql)
    return GuardedSQL(
        sql=sql,
        sql_digest=_sql_digest(sql),
        query_plan_fingerprint=_query_plan_fingerprint(plan),
        physical_tables=physical_tables,
        guard_result=guard_result,
        _token=_CAPABILITY_TOKEN,
    )


def issue_guarded_query(candidate: GuardedSQL, explain_result: ExplainResult) -> GuardedQuery:
    return GuardedQuery(
        sql=candidate.sql,
        sql_digest=candidate.sql_digest,
        query_plan_fingerprint=candidate.query_plan_fingerprint,
        physical_tables=candidate.physical_tables,
        guard_result=candidate.guard_result,
        explain_result=explain_result,
        _token=_CAPABILITY_TOKEN,
    )
