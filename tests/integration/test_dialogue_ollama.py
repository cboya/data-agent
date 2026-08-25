import asyncio
import os

import pytest

from data_agent.config import Settings
from data_agent.contracts.dialogue import DialogueAction
from data_agent.dialogue.service import DialogueEngine
from data_agent.model_runtime.ollama import OllamaChatModel, OllamaStartupDiagnostics
from tests.dialogue.factories import empty_requirement

pytestmark = [
    pytest.mark.integration,
    pytest.mark.ollama,
    pytest.mark.skipif(
        os.environ.get("RUN_OLLAMA_INTEGRATION") != "1",
        reason="set RUN_OLLAMA_INTEGRATION=1 to exercise structured dialogue",
    ),
]


def test_real_ollama_structured_dialogue_reaches_ready() -> None:
    settings = Settings()  # type: ignore[call-arg]
    diagnostics = asyncio.run(OllamaStartupDiagnostics(settings).diagnose())
    engine = DialogueEngine(chat_model=OllamaChatModel(settings, fingerprint=diagnostics.chat))

    outcome = asyncio.run(
        engine.understand(
            requirement=empty_requirement(),
            latest_user_message="最近30天每天的实际支付金额 paid_amount",
        )
    )

    assert outcome.decision.action is DialogueAction.READY
    assert [str(value.resolved_name or value.term) for value in outcome.requirement.metrics] == [
        "paid_amount"
    ]
    assert outcome.requirement.time_range is not None
    assert outcome.requirement.time_range.value == "last_30_days"
    assert outcome.requirement.grain == "day"
