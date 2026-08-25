import re

from data_agent.catalog.semantic import load_assembled_catalog
from data_agent.planning.prompt import PLANNER_SYSTEM_PROMPT


def test_system_prompt_contains_no_concrete_catalog_table_identifier() -> None:
    prompt = PLANNER_SYSTEM_PROMPT.casefold()

    for document in load_assembled_catalog().documents:
        table = re.escape(str(document.table).casefold())
        assert re.search(rf"\b{table}\b", prompt) is None
