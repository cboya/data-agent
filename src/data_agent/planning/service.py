"""Provider-neutral M9 structured QueryPlan proposal service."""

from __future__ import annotations

from dataclasses import dataclass

from data_agent.catalog.semantic import AssembledSemanticCatalog
from data_agent.contracts.query import QueryPlan
from data_agent.contracts.requirement import RequirementState
from data_agent.contracts.retrieval import RetrievalResult
from data_agent.model_runtime.ports import ChatModel
from data_agent.planning.context import PlannerContext, PlannerContextBuilder
from data_agent.planning.policy import PlannerPolicy
from data_agent.planning.prompt import PLANNER_PROMPT_VERSION


@dataclass(frozen=True)
class PlanningTrace:
    context: PlannerContext
    plan: QueryPlan
    prompt_version: str
    model_fingerprint: str | None
    runtime_version: str | None
    retrieval_index_fingerprint: str
    allowed_tables: tuple[str, ...]


class QueryPlanner:
    def __init__(
        self,
        *,
        chat_model: ChatModel,
        context_builder: PlannerContextBuilder | None = None,
        policy: PlannerPolicy | None = None,
        model_fingerprint: str | None = None,
        runtime_version: str | None = None,
    ) -> None:
        self._chat_model = chat_model
        self._context_builder = context_builder or PlannerContextBuilder()
        self._policy = policy or PlannerPolicy()
        self._model_fingerprint = model_fingerprint
        self._runtime_version = runtime_version

    async def plan(
        self,
        *,
        requirement: RequirementState,
        retrieval: RetrievalResult,
        catalog: AssembledSemanticCatalog,
        expected_retrieval_index_fingerprint: str,
    ) -> PlanningTrace:
        context = self.build_context(
            requirement=requirement,
            retrieval=retrieval,
            catalog=catalog,
            expected_retrieval_index_fingerprint=expected_retrieval_index_fingerprint,
        )
        proposal = await self.propose(context)
        return self.accept(context=context, proposal=proposal)

    def build_context(
        self,
        *,
        requirement: RequirementState,
        retrieval: RetrievalResult,
        catalog: AssembledSemanticCatalog,
        expected_retrieval_index_fingerprint: str,
    ) -> PlannerContext:
        allowed = {str(hit.table) for hit in retrieval.hits}
        documents = tuple(
            document for document in catalog.documents if str(document.table) in allowed
        )
        return self._context_builder.build(
            requirement=requirement,
            retrieval=retrieval,
            catalog=catalog,
            documents=documents,
            expected_retrieval_index_fingerprint=expected_retrieval_index_fingerprint,
        )

    async def propose(self, context: PlannerContext) -> QueryPlan:
        return await self._chat_model.structured(
            messages=self._context_builder.messages(context),
            response_type=QueryPlan,
            purpose=PLANNER_PROMPT_VERSION,
        )

    def accept(self, *, context: PlannerContext, proposal: QueryPlan) -> PlanningTrace:
        plan = self._policy.validate(proposal, context=context)
        return PlanningTrace(
            context=context,
            plan=plan,
            prompt_version=PLANNER_PROMPT_VERSION,
            model_fingerprint=self._model_fingerprint,
            runtime_version=self._runtime_version,
            retrieval_index_fingerprint=context.identity.retrieval_index_fingerprint,
            allowed_tables=tuple(str(table) for table in context.allowed_tables),
        )
