"""Opt-in bounded live smoke for the M16 OpenAI-compatible profile."""

import asyncio
import os
from contextlib import suppress

import httpx
import pytest

from data_agent.api import create_app
from data_agent.config import Settings
from data_agent.contracts.requirement import (
    MetricRequirement,
    RequirementState,
    RequirementStatus,
    ResolutionStatus,
)
from data_agent.dialogue.errors import InvalidProviderEvidenceError
from data_agent.dialogue.service import DialogueEngine
from data_agent.model_runtime.composition import start_model_runtime
from data_agent.model_runtime.errors import ModelAdapterError
from data_agent.model_runtime.ports import ModelIdentityAssurance
from data_agent.planning.errors import PlannerError
from data_agent.planning.runtime import load_current_planner_runtime

pytestmark = [pytest.mark.integration]


@pytest.mark.skipif(
    os.getenv("RUN_OPENAI_COMPATIBLE_INTEGRATION") != "1",
    reason="set RUN_OPENAI_COMPATIBLE_INTEGRATION=1 for the bounded remote-provider smoke",
)
def test_openai_compatible_control_flow_smoke() -> None:
    async def smoke() -> None:
        settings = Settings()  # type: ignore[call-arg]
        assert settings.model_runtime_provider == "openai_compatible"
        runtime = await start_model_runtime(settings)
        assert runtime.diagnostics.provider == "openai_compatible"
        assert runtime.diagnostics.chat.identity_assurance in {
            ModelIdentityAssurance.IMMUTABLE_PROVIDER_REVISION,
            ModelIdentityAssurance.ALIAS_ONLY,
        }
        assert runtime.diagnostics.embedding.identity_assurance in {
            ModelIdentityAssurance.IMMUTABLE_PROVIDER_REVISION,
            ModelIdentityAssurance.ALIAS_ONLY,
        }

        dialogue = DialogueEngine(chat_model=runtime.chat_model)
        try:
            dialogue_outcome = await dialogue.understand(
                requirement=RequirementState(
                    version="v0.1",
                    status=RequirementStatus.INCOMPLETE,
                ),
                latest_user_message="查询全部时间范围的订单量",
            )
            assert dialogue_outcome.requirement.status in {
                RequirementStatus.READY,
                RequirementStatus.CLARIFYING,
            }
            if dialogue_outcome.requirement.status is RequirementStatus.READY:
                assert not any(
                    ambiguity.blocking for ambiguity in dialogue_outcome.requirement.unresolved
                )
        except (ModelAdapterError, InvalidProviderEvidenceError):
            # Typed fail-closed is an accepted wire/control-flow outcome for this smoke.
            pass

        planner_runtime = await load_current_planner_runtime(settings)
        retrieval = await planner_runtime.retrieval.retriever.retrieve(
            "全部时间范围的订单量 order count all time"
        )
        assert retrieval.result.hits
        requirement = RequirementState(
            version="v0.1",
            goal="查询全部时间范围的订单量",
            metrics=[
                MetricRequirement(
                    term="订单量",
                    resolved_name="order_count",
                    definition="Count governed orders",
                    status=ResolutionStatus.CONFIRMED,
                )
            ],
            status=RequirementStatus.READY,
        )
        with suppress(ModelAdapterError, PlannerError):
            await planner_runtime.planner.plan(
                requirement=requirement,
                retrieval=retrieval.result,
                catalog=planner_runtime.retrieval.authority.assembled,
                expected_retrieval_index_fingerprint=(planner_runtime.retrieval.index.fingerprint),
            )

        app = create_app(settings)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://m16-smoke",
            ) as client:
                created = await client.post("/sessions")
                assert created.status_code == 201
                session_id = created.json()["id"]
                response = await client.post(
                    f"/sessions/{session_id}/messages",
                    json={"content": "查询全部时间范围的订单量"},
                )
        assert response.status_code == 200
        payload = response.json()
        assert payload["type"] in {"clarification", "result", "failure"}
        if payload["type"] == "result":
            assert payload["verification"]["status"] == "PASSED"
        api_key = settings.openai_compatible_api_key
        assert api_key is not None
        assert api_key.get_secret_value() not in response.text

    asyncio.run(smoke())
