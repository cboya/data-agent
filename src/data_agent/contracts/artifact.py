"""Bounded persisted run artifact contract."""

from enum import StrEnum
from typing import Any

from data_agent.contracts.base import AwareDateTime, ContractModel, NonEmptyString


class ArtifactType(StrEnum):
    REQUIREMENT_STATE = "REQUIREMENT_STATE"
    RETRIEVAL_RESULT = "RETRIEVAL_RESULT"
    QUERY_PLAN = "QUERY_PLAN"
    SQL_GUARD = "SQL_GUARD"
    EXPLAIN = "EXPLAIN"
    EXECUTION_METADATA = "EXECUTION_METADATA"
    VERIFICATION = "VERIFICATION"


class Artifact(ContractModel):
    id: NonEmptyString
    session_id: NonEmptyString
    run_id: NonEmptyString
    type: ArtifactType
    contract_version: NonEmptyString
    payload: dict[str, Any]
    created_at: AwareDateTime
