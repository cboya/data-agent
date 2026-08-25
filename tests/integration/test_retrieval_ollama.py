import asyncio
import os

import pytest

from data_agent.config import Settings
from data_agent.retrieval.runtime import load_current_retrieval_runtime

pytestmark = [
    pytest.mark.integration,
    pytest.mark.ollama,
    pytest.mark.skipif(
        os.environ.get("RUN_OLLAMA_INTEGRATION") != "1",
        reason="set RUN_OLLAMA_INTEGRATION=1 to exercise the bound retrieval index",
    ),
]


def test_real_bound_index_serves_bilingual_hybrid_query() -> None:
    settings = Settings()  # type: ignore[call-arg]
    runtime = asyncio.run(load_current_retrieval_runtime(settings))

    trace = asyncio.run(runtime.retriever.retrieve("各地区用户的实际支付金额"))

    tables = [str(hit.table) for hit in trace.result.hits]
    assert "fact_order" in tables[:5]
    assert "dim_user" in tables[:5]
    assert "dim_region" in tables[:5]
    assert trace.result.index_fingerprint == runtime.index.fingerprint
