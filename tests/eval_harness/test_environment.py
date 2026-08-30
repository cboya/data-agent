from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import SecretStr, TypeAdapter, ValidationError

import eval_harness.environment as environment_module
from data_agent.config import Settings
from data_agent.model_runtime.composition import (
    ModelRuntimeResourceEvidence,
    start_model_runtime,
)
from data_agent.model_runtime.openai_compatible import JsonObject
from data_agent.model_runtime.ports import (
    ModelFingerprint,
    ModelIdentityAssurance,
)
from data_agent.retrieval.index import RetrievalIndex
from data_agent.retrieval.runtime import CurrentCatalogAuthority
from eval_harness.environment import build_environment
from eval_harness.golden import _passes_golden_gates
from eval_harness.models import (
    EvaluationEnvironment,
    EvaluationEnvironmentV01,
    EvaluationEnvironmentV02,
    FinalAcceptanceReport,
    GoldenMetrics,
    GoldenReport,
)
from eval_harness.runner import _passes_final_acceptance


class StubTransport:
    def __init__(self, responses: list[JsonObject]) -> None:
        self._responses = list(responses)

    async def request(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
    ) -> JsonObject:
        del method, path, payload
        if not self._responses:
            raise AssertionError("unexpected transport request")
        return self._responses.pop(0)


def _descriptor(model: str) -> JsonObject:
    return {
        "id": model,
        "object": "model",
        "created": 1_777_593_600,
        "owned_by": "test-provider",
        "provider_version": "provider-test",
    }


def _authority_and_index() -> tuple[CurrentCatalogAuthority, RetrievalIndex]:
    authority = cast(
        CurrentCatalogAuthority,
        SimpleNamespace(
            generated=SimpleNamespace(fingerprint="1" * 64),
            assembled=SimpleNamespace(catalog_fingerprint="2" * 64),
            curated=SimpleNamespace(semantic_revision="3" * 64),
        ),
    )
    index = cast(RetrievalIndex, SimpleNamespace(fingerprint="4" * 64))
    return authority, index


def _passing_metrics() -> GoldenMetrics:
    return GoldenMetrics(
        case_count=59,
        result_case_count=55,
        e2e_pass_rate=0.95,
        result_oracle_pass_rate=0.95,
        trace_integrity_rate=1.0,
        unnecessary_clarification_rate=0.05,
        unauthorized_execution_count=0,
        failed_verification_synthesis_count=0,
        numeric_grounding_violation_count=0,
        repair_bound_violation_count=0,
        verified_oracle_mismatch_count=0,
    )


def _build_environment(
    monkeypatch: pytest.MonkeyPatch,
    runtime: ModelRuntimeResourceEvidence,
) -> EvaluationEnvironmentV02:
    monkeypatch.setattr(environment_module, "require_clean_git_commit", lambda: "5" * 40)
    authority, index = _authority_and_index()
    return build_environment(
        golden_version="golden-v0.1",
        golden_fingerprint="6" * 64,
        authority=authority,
        index=index,
        model_runtime=runtime,
    )


def test_remote_environment_uses_composition_selected_identity_and_bounds(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_model = "chat-deployment"
    embedding_model = "embed-deployment"
    remote = Settings.model_validate(
        {
            **settings.model_dump(),
            "model_runtime_provider": "openai_compatible",
            "openai_compatible_base_url": "https://models.example.test/v1",
            "openai_compatible_identity_profile": "openai_models_by_id",
            "openai_compatible_api_key": SecretStr("remote-test-secret"),
            "openai_compatible_chat_model": chat_model,
            "openai_compatible_embed_model": embedding_model,
            "openai_compatible_request_timeout_seconds": 47,
            "openai_compatible_max_output_tokens": 1_024,
            "ollama_request_timeout_seconds": 11,
            "ollama_max_output_tokens": 512,
        }
    )
    chat = _descriptor(chat_model)
    embedding = _descriptor(embedding_model)
    runtime = asyncio.run(
        start_model_runtime(
            remote,
            openai_compatible_transport=StubTransport([chat, embedding, chat, embedding]),
        )
    )

    environment = _build_environment(monkeypatch, runtime.resource_evidence)

    assert environment.version == "evaluation-environment-v0.2"
    assert environment.model_provider == "openai_compatible"
    assert environment.model_runtime_version == "provider-test"
    assert environment.chat_model_fingerprint == runtime.diagnostics.chat.value
    assert environment.embedding_model_fingerprint == runtime.diagnostics.embedding.value
    assert environment.chat_identity_assurance is ModelIdentityAssurance.ALIAS_ONLY
    assert environment.embedding_identity_assurance is ModelIdentityAssurance.ALIAS_ONLY
    assert environment.model_request_timeout_seconds == 47
    assert environment.model_request_timeout_seconds != remote.ollama_request_timeout_seconds
    assert environment.model_max_output_tokens == 1_024
    assert environment.model_max_output_tokens != remote.ollama_max_output_tokens
    assert not environment.product_acceptance_identity_eligible


def test_alias_only_identity_cannot_produce_product_acceptance(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alias = ModelFingerprint(
        provider="openai_compatible",
        model="mutable-alias",
        digest=None,
        capabilities=("completion",),
        endpoint_identity="7" * 64,
        identity_assurance=ModelIdentityAssurance.ALIAS_ONLY,
    )
    embedding = ModelFingerprint(
        provider="openai_compatible",
        model="mutable-embedding-alias",
        digest=None,
        capabilities=("embedding",),
        endpoint_identity="7" * 64,
        identity_assurance=ModelIdentityAssurance.ALIAS_ONLY,
    )
    environment = _build_environment(
        monkeypatch,
        ModelRuntimeResourceEvidence(
            provider="openai_compatible",
            runtime_version="not-exposed",
            chat_fingerprint=alias,
            embedding_fingerprint=embedding,
            request_timeout_seconds=60,
            max_output_tokens=2_048,
        ),
    )
    metrics = _passing_metrics()
    golden = GoldenReport(
        environment=environment,
        metrics=metrics,
        cases=(),
        passed=True,
    )

    assert _passes_golden_gates(metrics)
    assert not _passes_final_acceptance(
        stages_passed=True,
        golden_passed=True,
        environment=environment,
    )
    with pytest.raises(ValidationError, match="eligible model identity"):
        FinalAcceptanceReport(
            environment=environment,
            stages={"all": {"passed": True}},
            golden=golden,
            passed=True,
        )


def test_immutable_ollama_identity_remains_product_acceptance_eligible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat = ModelFingerprint(
        provider="ollama",
        model="chat",
        digest="sha256:chat",
        capabilities=("completion",),
    )
    embedding = ModelFingerprint(
        provider="ollama",
        model="embedding",
        digest="sha256:embedding",
        capabilities=("embedding",),
    )
    environment = _build_environment(
        monkeypatch,
        ModelRuntimeResourceEvidence(
            provider="ollama",
            runtime_version="0.33.1",
            chat_fingerprint=chat,
            embedding_fingerprint=embedding,
            request_timeout_seconds=60,
            max_output_tokens=2_048,
        ),
    )

    assert environment.chat_identity_assurance is ModelIdentityAssurance.IMMUTABLE_PROVIDER_REVISION
    assert (
        environment.embedding_identity_assurance
        is ModelIdentityAssurance.IMMUTABLE_PROVIDER_REVISION
    )
    assert environment.product_acceptance_identity_eligible
    assert _passes_final_acceptance(
        stages_passed=True,
        golden_passed=True,
        environment=environment,
    )


def test_historical_v01_environment_round_trips_without_revision() -> None:
    historical: dict[str, Any] = {
        "version": "evaluation-environment-v0.1",
        "git_commit": "1" * 40,
        "golden_version": "golden-v0.1",
        "golden_fingerprint": "2" * 64,
        "generated_schema_fingerprint": "3" * 64,
        "catalog_fingerprint": "4" * 64,
        "semantic_revision": "5" * 64,
        "retrieval_index_fingerprint": "6" * 64,
        "chat_model_fingerprint": "7" * 64,
        "embedding_model_fingerprint": "8" * 64,
        "ollama_runtime_version": "0.33.1",
        "ollama_request_timeout_seconds": 60.0,
        "ollama_max_output_tokens": 2_048,
        "dialogue_prompt_version": "dialogue-understanding-v0.21",
        "planning_prompt_version": "query-planning-v0.3",
        "repair_prompt_version": "query-repair-v0.1",
        "answer_prompt_version": "answer-synthesis-v0.2",
        "sql_guard_policy_version": "sql-guard-v0.2",
        "explain_policy_version": "explain-policy-v0.1",
        "query_runtime_policy_version": "query-runtime-v0.2",
        "verification_policy_version": "verification-policy-v0.2",
        "repair_policy_version": "repair-policy-v0.1",
        "answer_grounding_policy_version": "answer-grounding-v0.2",
        "trace_schema_version": "trace-event-v0.1",
        "evaluation_timezone": "UTC",
        "python_version": "3.14.7",
        "dependency_lock_fingerprint": "9" * 64,
        "fingerprint": "a" * 64,
    }

    environment: EvaluationEnvironment = TypeAdapter(EvaluationEnvironment).validate_python(
        historical
    )

    assert isinstance(environment, EvaluationEnvironmentV01)
    assert environment.model_dump(mode="json") == historical
    golden = GoldenReport(
        environment=environment,
        metrics=_passing_metrics(),
        cases=(),
        passed=True,
    )
    report = FinalAcceptanceReport(
        environment=environment,
        stages={"historical": {"passed": True}},
        golden=golden,
        passed=True,
    )
    assert report.passed
