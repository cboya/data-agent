"""Append-only user-visible message contract."""

from enum import StrEnum

from data_agent.contracts.base import AwareDateTime, ContractModel, NonEmptyString


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Message(ContractModel):
    id: NonEmptyString
    session_id: NonEmptyString
    role: MessageRole
    content: NonEmptyString
    created_at: AwareDateTime
