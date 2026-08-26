"""Internal immutable identities issued by deterministic M10 admission."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from data_agent.contracts.execution import ExplainResult, GuardStatus, SQLGuardResult
from data_agent.contracts.query import QueryPlan

_CAPABILITY_TOKEN = object()
_SHA256_HEX_LENGTH = 64


@dataclass(frozen=True, order=True)
class PhysicalTable:
    schema: str | None
    name: str

    @property
    def qualified_name(self) -> str:
        return self.name if self.schema is None else f"{self.schema}.{self.name}"


def _sql_digest(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def query_plan_fingerprint(plan: QueryPlan) -> str:
    """Return the canonical M9 plan identity bound by M10 capabilities."""

    canonical = json.dumps(
        plan.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == _SHA256_HEX_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


def _capability_fingerprint(
    *,
    sql_digest: str,
    query_plan_fingerprint: str,
    execution_namespace: str,
    guard_policy_version: str,
    explain_policy_version: str | None,
    physical_tables: tuple[PhysicalTable, ...],
    guard_result: SQLGuardResult,
    explain_result: ExplainResult | None,
) -> str:
    payload = {
        "sql_digest": sql_digest,
        "query_plan_fingerprint": query_plan_fingerprint,
        "execution_namespace": execution_namespace,
        "guard_policy_version": guard_policy_version,
        "explain_policy_version": explain_policy_version,
        "physical_tables": [
            {"schema": table.schema, "name": table.name} for table in physical_tables
        ],
        "guard_result": guard_result.model_dump(mode="json"),
        "explain_result": (
            None if explain_result is None else explain_result.model_dump(mode="json")
        ),
    }
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GuardedSQL:
    """Post-guard, pre-EXPLAIN candidate; only the Harness provider may consume it."""

    sql: str
    sql_digest: str
    query_plan_fingerprint: str
    execution_namespace: str
    guard_policy_version: str
    capability_fingerprint: str
    physical_tables: tuple[PhysicalTable, ...]
    guard_result: SQLGuardResult
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        self.verify_integrity()

    def verify_integrity(self) -> None:
        if self._token is not _CAPABILITY_TOKEN:
            raise ValueError("GuardedSQL can only be issued by SQLGuard")
        if self.guard_result.status is not GuardStatus.PASSED:
            raise ValueError("GuardedSQL requires passed guard evidence")
        if self.sql_digest != _sql_digest(self.sql):
            raise ValueError("GuardedSQL SQL digest mismatch")
        if not _is_sha256(self.query_plan_fingerprint):
            raise ValueError("GuardedSQL QueryPlan fingerprint is invalid")
        if not self.execution_namespace.strip():
            raise ValueError("GuardedSQL execution namespace is missing")
        if not self.guard_policy_version.strip():
            raise ValueError("GuardedSQL guard policy identity is missing")
        expected = _capability_fingerprint(
            sql_digest=self.sql_digest,
            query_plan_fingerprint=self.query_plan_fingerprint,
            execution_namespace=self.execution_namespace,
            guard_policy_version=self.guard_policy_version,
            explain_policy_version=None,
            physical_tables=self.physical_tables,
            guard_result=self.guard_result,
            explain_result=None,
        )
        if self.capability_fingerprint != expected:
            raise ValueError("GuardedSQL capability fingerprint mismatch")


@dataclass(frozen=True)
class GuardedQuery:
    """M10 execution capability for future M11; not a public domain contract."""

    sql: str
    sql_digest: str
    query_plan_fingerprint: str
    execution_namespace: str
    guard_policy_version: str
    explain_policy_version: str
    capability_fingerprint: str
    physical_tables: tuple[PhysicalTable, ...]
    guard_result: SQLGuardResult
    explain_result: ExplainResult
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        self.verify_integrity()

    def verify_integrity(
        self,
        *,
        expected_guard_policy_version: str | None = None,
        expected_explain_policy_version: str | None = None,
    ) -> None:
        if self._token is not _CAPABILITY_TOKEN:
            raise ValueError("GuardedQuery can only be issued by M10 admission")
        if self.guard_result.status is not GuardStatus.PASSED:
            raise ValueError("GuardedQuery requires passed guard evidence")
        if not self.explain_result.accepted:
            raise ValueError("GuardedQuery requires accepted EXPLAIN evidence")
        if self.sql_digest != _sql_digest(self.sql):
            raise ValueError("GuardedQuery SQL digest mismatch")
        if not _is_sha256(self.query_plan_fingerprint):
            raise ValueError("GuardedQuery QueryPlan fingerprint is invalid")
        if not self.execution_namespace.strip():
            raise ValueError("GuardedQuery execution namespace is missing")
        if not self.guard_policy_version.strip() or not self.explain_policy_version.strip():
            raise ValueError("GuardedQuery policy identity is missing")
        expected = _capability_fingerprint(
            sql_digest=self.sql_digest,
            query_plan_fingerprint=self.query_plan_fingerprint,
            execution_namespace=self.execution_namespace,
            guard_policy_version=self.guard_policy_version,
            explain_policy_version=self.explain_policy_version,
            physical_tables=self.physical_tables,
            guard_result=self.guard_result,
            explain_result=self.explain_result,
        )
        if self.capability_fingerprint != expected:
            raise ValueError("GuardedQuery capability fingerprint mismatch")
        if (
            expected_guard_policy_version is not None
            and self.guard_policy_version != expected_guard_policy_version
        ):
            raise ValueError("GuardedQuery guard policy identity is stale")
        if (
            expected_explain_policy_version is not None
            and self.explain_policy_version != expected_explain_policy_version
        ):
            raise ValueError("GuardedQuery EXPLAIN policy identity is stale")


def issue_guarded_sql(
    plan: QueryPlan,
    *,
    physical_tables: tuple[PhysicalTable, ...],
    guard_result: SQLGuardResult,
    execution_namespace: str,
    guard_policy_version: str,
) -> GuardedSQL:
    sql = str(plan.sql)
    sql_digest = _sql_digest(sql)
    plan_fingerprint = query_plan_fingerprint(plan)
    return GuardedSQL(
        sql=sql,
        sql_digest=sql_digest,
        query_plan_fingerprint=plan_fingerprint,
        execution_namespace=execution_namespace,
        guard_policy_version=guard_policy_version,
        capability_fingerprint=_capability_fingerprint(
            sql_digest=sql_digest,
            query_plan_fingerprint=plan_fingerprint,
            execution_namespace=execution_namespace,
            guard_policy_version=guard_policy_version,
            explain_policy_version=None,
            physical_tables=physical_tables,
            guard_result=guard_result,
            explain_result=None,
        ),
        physical_tables=physical_tables,
        guard_result=guard_result,
        _token=_CAPABILITY_TOKEN,
    )


def issue_guarded_query(
    candidate: GuardedSQL,
    explain_result: ExplainResult,
    *,
    explain_policy_version: str,
) -> GuardedQuery:
    capability_fingerprint = _capability_fingerprint(
        sql_digest=candidate.sql_digest,
        query_plan_fingerprint=candidate.query_plan_fingerprint,
        execution_namespace=candidate.execution_namespace,
        guard_policy_version=candidate.guard_policy_version,
        explain_policy_version=explain_policy_version,
        physical_tables=candidate.physical_tables,
        guard_result=candidate.guard_result,
        explain_result=explain_result,
    )
    return GuardedQuery(
        sql=candidate.sql,
        sql_digest=candidate.sql_digest,
        query_plan_fingerprint=candidate.query_plan_fingerprint,
        execution_namespace=candidate.execution_namespace,
        guard_policy_version=candidate.guard_policy_version,
        explain_policy_version=explain_policy_version,
        capability_fingerprint=capability_fingerprint,
        physical_tables=candidate.physical_tables,
        guard_result=candidate.guard_result,
        explain_result=explain_result,
        _token=_CAPABILITY_TOKEN,
    )
