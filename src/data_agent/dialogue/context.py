"""Bounded context projection for the M8 dialogue model call."""

from __future__ import annotations

import json
from dataclasses import dataclass

from data_agent.contracts.requirement import RequirementState
from data_agent.dialogue.errors import DialogueContextError
from data_agent.dialogue.prompt import DIALOGUE_SYSTEM_PROMPT


@dataclass(frozen=True)
class DialogueContextBuilder:
    max_user_characters: int = 4_000
    max_context_characters: int = 32_000

    def __post_init__(self) -> None:
        if self.max_user_characters < 1 or self.max_context_characters < 1:
            raise ValueError("dialogue context bounds must be positive")

    def build(
        self,
        *,
        requirement: RequirementState,
        latest_user_message: str,
        last_assistant_clarification: str | None = None,
    ) -> list[dict[str, str]]:
        if not latest_user_message.strip():
            raise DialogueContextError("latest user message cannot be blank")
        if len(latest_user_message) > self.max_user_characters:
            raise DialogueContextError("latest user message exceeds the dialogue context bound")
        if last_assistant_clarification is not None:
            if not last_assistant_clarification.strip():
                raise DialogueContextError("last assistant clarification cannot be blank")
            if len(last_assistant_clarification) > 240:
                raise DialogueContextError(
                    "last assistant clarification exceeds its contract bound"
                )

        payload = json.dumps(
            {
                "current_requirement_state": requirement.model_dump(mode="json"),
                "last_assistant_clarification": last_assistant_clarification,
                "latest_user_message": latest_user_message,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        total_characters = len(DIALOGUE_SYSTEM_PROMPT) + len(payload)
        if total_characters > self.max_context_characters:
            raise DialogueContextError("projected dialogue context exceeds the configured bound")
        return [
            {"role": "system", "content": DIALOGUE_SYSTEM_PROMPT},
            {"role": "user", "content": payload},
        ]
