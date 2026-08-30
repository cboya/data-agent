"""Complete identity binding for meaningful model acceptance claims."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from pathlib import Path

from data_agent.answer.grounding import ANSWER_GROUNDING_POLICY_VERSION
from data_agent.answer.prompt import ANSWER_PROMPT_VERSION
from data_agent.dialogue.prompt import DIALOGUE_PROMPT_VERSION
from data_agent.model_runtime.composition import ModelRuntimeResourceEvidence
from data_agent.planning.prompt import PLANNER_PROMPT_VERSION
from data_agent.query_runtime.service import QUERY_RUNTIME_POLICY_VERSION
from data_agent.repair.evidence import REPAIR_POLICY_VERSION
from data_agent.repair.prompt import QUERY_REPAIR_PROMPT_VERSION
from data_agent.retrieval.index import RetrievalIndex
from data_agent.retrieval.runtime import CurrentCatalogAuthority
from data_agent.sql_guard.explain import EXPLAIN_POLICY_VERSION
from data_agent.sql_guard.guard import SQL_GUARD_POLICY_VERSION
from data_agent.trace.model import TRACE_SCHEMA_VERSION
from data_agent.verification.evidence import VERIFICATION_POLICY_VERSION
from eval_harness.models import EvaluationEnvironmentV02

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_clean_git_commit() -> str:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        raise RuntimeError("final acceptance requires a clean Git worktree")
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def build_environment(
    *,
    golden_version: str,
    golden_fingerprint: str,
    authority: CurrentCatalogAuthority,
    index: RetrievalIndex,
    model_runtime: ModelRuntimeResourceEvidence,
) -> EvaluationEnvironmentV02:
    payload = {
        "version": "evaluation-environment-v0.2",
        "git_commit": require_clean_git_commit(),
        "golden_version": golden_version,
        "golden_fingerprint": golden_fingerprint,
        "generated_schema_fingerprint": authority.generated.fingerprint,
        "catalog_fingerprint": authority.assembled.catalog_fingerprint,
        "semantic_revision": authority.curated.semantic_revision,
        "retrieval_index_fingerprint": index.fingerprint,
        "model_provider": model_runtime.provider,
        "model_runtime_version": model_runtime.runtime_version,
        "chat_model_fingerprint": model_runtime.chat_fingerprint.value,
        "chat_identity_assurance": model_runtime.chat_fingerprint.identity_assurance.value,
        "embedding_model_fingerprint": model_runtime.embedding_fingerprint.value,
        "embedding_identity_assurance": (
            model_runtime.embedding_fingerprint.identity_assurance.value
        ),
        "model_request_timeout_seconds": model_runtime.request_timeout_seconds,
        "model_max_output_tokens": model_runtime.max_output_tokens,
        "product_acceptance_identity_eligible": (
            model_runtime.product_acceptance_identity_eligible
        ),
        "dialogue_prompt_version": DIALOGUE_PROMPT_VERSION,
        "planning_prompt_version": PLANNER_PROMPT_VERSION,
        "repair_prompt_version": QUERY_REPAIR_PROMPT_VERSION,
        "answer_prompt_version": ANSWER_PROMPT_VERSION,
        "sql_guard_policy_version": SQL_GUARD_POLICY_VERSION,
        "explain_policy_version": EXPLAIN_POLICY_VERSION,
        "query_runtime_policy_version": QUERY_RUNTIME_POLICY_VERSION,
        "verification_policy_version": VERIFICATION_POLICY_VERSION,
        "repair_policy_version": REPAIR_POLICY_VERSION,
        "answer_grounding_policy_version": ANSWER_GROUNDING_POLICY_VERSION,
        "trace_schema_version": TRACE_SCHEMA_VERSION,
        "evaluation_timezone": "UTC",
        "python_version": platform.python_version(),
        "dependency_lock_fingerprint": _sha256(REPOSITORY_ROOT / "uv.lock"),
    }
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return EvaluationEnvironmentV02.model_validate(
        {
            **payload,
            "fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }
    )
