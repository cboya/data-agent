"""Complete identity binding for meaningful model acceptance claims."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from pathlib import Path

from data_agent.answer.grounding import ANSWER_GROUNDING_POLICY_VERSION
from data_agent.answer.prompt import ANSWER_PROMPT_VERSION
from data_agent.config import Settings
from data_agent.dialogue.prompt import DIALOGUE_PROMPT_VERSION
from data_agent.model_runtime.ports import ModelRuntimeDiagnostics
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
from eval_harness.models import EvaluationEnvironment

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
    diagnostics: ModelRuntimeDiagnostics,
    settings: Settings,
) -> EvaluationEnvironment:
    payload = {
        "version": "evaluation-environment-v0.1",
        "git_commit": require_clean_git_commit(),
        "golden_version": golden_version,
        "golden_fingerprint": golden_fingerprint,
        "generated_schema_fingerprint": authority.generated.fingerprint,
        "catalog_fingerprint": authority.assembled.catalog_fingerprint,
        "semantic_revision": authority.curated.semantic_revision,
        "retrieval_index_fingerprint": index.fingerprint,
        "chat_model_fingerprint": diagnostics.chat.value,
        "embedding_model_fingerprint": diagnostics.embedding.value,
        "ollama_runtime_version": diagnostics.runtime_version,
        "ollama_request_timeout_seconds": settings.ollama_request_timeout_seconds,
        "ollama_max_output_tokens": settings.ollama_max_output_tokens,
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
    return EvaluationEnvironment.model_validate(
        {
            **payload,
            "fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }
    )
