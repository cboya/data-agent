"""Immutable MySQL Artifact repository with typed payload revalidation."""

import json
from typing import cast

import pymysql
from pydantic import ValidationError

from data_agent.config import Settings
from data_agent.contracts.artifact import Artifact, ArtifactType
from data_agent.contracts.base import ContractModel
from data_agent.contracts.execution import ExecutionResult, ExplainResult, SQLGuardResult
from data_agent.contracts.query import QueryPlan
from data_agent.contracts.requirement import RequirementState
from data_agent.contracts.retrieval import RetrievalResult
from data_agent.contracts.verification import VerificationResult
from data_agent.persistence.errors import CorruptRecordError, PersistenceInvariantError
from data_agent.persistence.mysql.common import (
    control_connection,
    corrupt_record,
    from_database_datetime,
    raise_write_error,
    require_string,
    to_database_datetime,
)

_PAYLOAD_TYPES: dict[ArtifactType, type[ContractModel]] = {
    ArtifactType.REQUIREMENT_STATE: RequirementState,
    ArtifactType.RETRIEVAL_RESULT: RetrievalResult,
    ArtifactType.QUERY_PLAN: QueryPlan,
    ArtifactType.SQL_GUARD: SQLGuardResult,
    ArtifactType.EXPLAIN: ExplainResult,
    ArtifactType.EXECUTION_METADATA: ExecutionResult,
    ArtifactType.VERIFICATION: VerificationResult,
}


def _validate_artifact(artifact: Artifact) -> Artifact:
    if artifact.contract_version != "v0.1":
        raise PersistenceInvariantError("unsupported Artifact contract_version")
    try:
        payload_model = _PAYLOAD_TYPES[artifact.type].model_validate(artifact.payload)
        payload = payload_model.model_dump(mode="json")
        return Artifact.model_validate({**artifact.model_dump(), "payload": payload})
    except (KeyError, ValidationError, ValueError) as error:
        if isinstance(error, PersistenceInvariantError):
            raise
        raise corrupt_record("agent_artifact.payload_json", error) from error


def _artifact_from_row(row: tuple[object, ...]) -> Artifact:
    try:
        artifact = Artifact.model_validate(
            {
                "id": row[0],
                "session_id": row[1],
                "run_id": row[2],
                "type": row[3],
                "contract_version": row[4],
                "payload": json.loads(require_string(row[5], field="agent_artifact.payload_json")),
                "created_at": from_database_datetime(row[6], field="agent_artifact.created_at"),
            }
        )
        return _validate_artifact(artifact)
    except (ValidationError, ValueError) as error:
        if isinstance(error, CorruptRecordError):
            raise
        raise corrupt_record("agent_artifact", error) from error


class MySQLArtifactRepository:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def append(self, artifact: Artifact) -> Artifact:
        validated = _validate_artifact(artifact)
        connection = control_connection(self._settings)
        try:
            with connection.cursor() as cursor:
                try:
                    cursor.execute(
                        "INSERT INTO agent_artifact "
                        "(id, session_id, run_id, artifact_type, contract_version, "
                        "payload_json, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (
                            validated.id,
                            validated.session_id,
                            validated.run_id,
                            validated.type.value,
                            validated.contract_version,
                            json.dumps(validated.payload),
                            to_database_datetime(validated.created_at),
                        ),
                    )
                except pymysql.MySQLError as error:
                    raise_write_error(error, record=f"Artifact {validated.id}")
        finally:
            connection.close()
        return validated

    def list_for_run(self, run_id: str) -> list[Artifact]:
        connection = control_connection(self._settings)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, session_id, run_id, artifact_type, contract_version, "
                    "payload_json, created_at FROM agent_artifact WHERE run_id = %s "
                    "ORDER BY created_at, id",
                    (run_id,),
                )
                rows = cast(tuple[tuple[object, ...], ...], cursor.fetchall())
        finally:
            connection.close()
        return [_artifact_from_row(row) for row in rows]
