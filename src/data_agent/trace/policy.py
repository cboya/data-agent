"""Deterministic completeness and ordering policy for terminal Run traces."""

from __future__ import annotations

from itertools import pairwise

from data_agent.contracts.run import Run, RunStatus
from data_agent.trace.errors import TraceIntegrityError
from data_agent.trace.model import TraceEvent, TraceEventType

_DIRECT_SUCCESS = (
    TraceEventType.RUN_RECEIVED,
    TraceEventType.DIALOGUE_COMPLETED,
    TraceEventType.RETRIEVAL_COMPLETED,
    TraceEventType.PLANNING_COMPLETED,
    TraceEventType.SQL_ADMISSION_COMPLETED,
    TraceEventType.EXECUTION_COMPLETED,
    TraceEventType.VERIFICATION_COMPLETED,
    TraceEventType.SYNTHESIS_COMPLETED,
    TraceEventType.RUN_TERMINATED,
)
_CLARIFICATION = (
    TraceEventType.RUN_RECEIVED,
    TraceEventType.DIALOGUE_COMPLETED,
    TraceEventType.RUN_TERMINATED,
)
_ATTEMPT_ZERO_PATH = _DIRECT_SUCCESS[:-1]
_ATTEMPT_ONE_PATH = (
    TraceEventType.PLANNING_COMPLETED,
    TraceEventType.SQL_ADMISSION_COMPLETED,
    TraceEventType.EXECUTION_COMPLETED,
    TraceEventType.VERIFICATION_COMPLETED,
    TraceEventType.SYNTHESIS_COMPLETED,
)
_SUCCESS_OUTCOMES = {
    TraceEventType.RUN_RECEIVED: "RECEIVED",
    TraceEventType.DIALOGUE_COMPLETED: "SUCCEEDED",
    TraceEventType.RETRIEVAL_COMPLETED: "SUCCEEDED",
    TraceEventType.PLANNING_COMPLETED: "SUCCEEDED",
    TraceEventType.SQL_ADMISSION_COMPLETED: "SUCCEEDED",
    TraceEventType.EXECUTION_COMPLETED: "SUCCEEDED",
    TraceEventType.VERIFICATION_COMPLETED: "PASSED",
    TraceEventType.REPAIR_COMPLETED: "SUCCEEDED",
    TraceEventType.SYNTHESIS_COMPLETED: "SUCCEEDED",
    TraceEventType.RUN_TERMINATED: "TERMINATED",
}
_NON_FAILURE_OUTCOMES = frozenset(_SUCCESS_OUTCOMES.values())


class TraceCompletenessPolicy:
    """Reject a trace that cannot prove the durable terminal Run path."""

    def validate(self, run: Run, events: tuple[TraceEvent, ...]) -> None:
        if not events:
            raise TraceIntegrityError("terminal Run has no trace events")
        if tuple(event.sequence for event in events) != tuple(range(1, len(events) + 1)):
            raise TraceIntegrityError("trace sequence is not contiguous from one")
        if len({str(event.id) for event in events}) != len(events):
            raise TraceIntegrityError("trace event ids are not unique")
        if any(event.run_id != run.id or event.session_id != run.session_id for event in events):
            raise TraceIntegrityError("trace identity does not match its Run")
        if any(later.occurred_at < earlier.occurred_at for earlier, later in pairwise(events)):
            raise TraceIntegrityError("trace timestamps move backwards")
        if events[0].event_type is not TraceEventType.RUN_RECEIVED:
            raise TraceIntegrityError("trace does not begin with RUN_RECEIVED")
        if events[-1].event_type is not TraceEventType.RUN_TERMINATED:
            raise TraceIntegrityError("trace does not end with RUN_TERMINATED")
        terminal_status = events[-1].payload.get("terminal_status")
        if terminal_status != run.status.value:
            raise TraceIntegrityError("terminal trace status does not match durable Run")

        types = tuple(event.event_type for event in events)
        if run.status is RunStatus.CLARIFYING:
            if types != _CLARIFICATION:
                raise TraceIntegrityError("clarification trace has an unexpected stage path")
            self._require_success_outcomes(events)
            return
        if run.status is RunStatus.COMPLETED:
            self._validate_completed(run, events, types)
            return
        self._validate_failure(run, events)

    def _validate_completed(
        self,
        run: Run,
        events: tuple[TraceEvent, ...],
        types: tuple[TraceEventType, ...],
    ) -> None:
        repair_events = [
            event for event in events if event.event_type is TraceEventType.REPAIR_COMPLETED
        ]
        if run.repair_count == 0:
            if types != _DIRECT_SUCCESS or any(event.attempt != 0 for event in events):
                raise TraceIntegrityError("direct success trace is incomplete or reordered")
            self._require_success_outcomes(events)
            return
        if run.repair_count != 1 or len(repair_events) != 1:
            raise TraceIntegrityError("repaired success has inconsistent repair evidence")
        repair_index = events.index(repair_events[0])
        if repair_events[0].attempt != 1:
            raise TraceIntegrityError("repair event must identify attempt one")
        required_prefix = (
            TraceEventType.RUN_RECEIVED,
            TraceEventType.DIALOGUE_COMPLETED,
            TraceEventType.RETRIEVAL_COMPLETED,
            TraceEventType.PLANNING_COMPLETED,
        )
        if types[:4] != required_prefix or repair_index < 5:
            raise TraceIntegrityError("repaired success is missing its original failed branch")
        if events[repair_index - 1].payload.get("outcome") in {
            "SUCCEEDED",
            "PASSED",
            "TERMINATED",
        }:
            raise TraceIntegrityError("repair does not follow failed stage evidence")
        if (
            repair_events[0].payload.get("eligible") is not True
            or repair_events[0].payload.get("outcome") != "SUCCEEDED"
        ):
            raise TraceIntegrityError("repaired success has invalid repair outcome evidence")
        replacement = tuple(event.event_type for event in events[repair_index + 1 :])
        if replacement != (
            TraceEventType.PLANNING_COMPLETED,
            TraceEventType.SQL_ADMISSION_COMPLETED,
            TraceEventType.EXECUTION_COMPLETED,
            TraceEventType.VERIFICATION_COMPLETED,
            TraceEventType.SYNTHESIS_COMPLETED,
            TraceEventType.RUN_TERMINATED,
        ):
            raise TraceIntegrityError("repaired success is missing replacement-branch evidence")
        if any(event.attempt != 0 for event in events[:repair_index]):
            raise TraceIntegrityError("original branch must be attempt zero")
        if any(event.attempt != 1 for event in events[repair_index:]):
            raise TraceIntegrityError("replacement branch must be attempt one")
        self._require_success_outcomes(events[: repair_index - 1])
        self._require_success_outcomes(events[repair_index:])

    def _validate_failure(self, run: Run, events: tuple[TraceEvent, ...]) -> None:
        if len(events) < 2:
            raise TraceIntegrityError("failed Run trace has no failure-stage evidence")
        if any(event.event_type is TraceEventType.SYNTHESIS_COMPLETED for event in events):
            synthesis = next(
                event for event in events if event.event_type is TraceEventType.SYNTHESIS_COMPLETED
            )
            if synthesis.payload.get("outcome") == "SUCCEEDED":
                raise TraceIntegrityError("failed Run cannot retain successful synthesis evidence")
        if (
            len([event for event in events if event.event_type is TraceEventType.RUN_TERMINATED])
            != 1
        ):
            raise TraceIntegrityError("failed Run trace has multiple terminal events")
        body = events[:-1]
        if events[0].payload.get("outcome") != "RECEIVED":
            raise TraceIntegrityError("failed trace has invalid receipt outcome")
        if events[-1].payload.get("outcome") != "TERMINATED":
            raise TraceIntegrityError("failed trace has invalid terminal outcome")
        repair_indexes = [
            index
            for index, event in enumerate(body)
            if event.event_type is TraceEventType.REPAIR_COMPLETED
        ]
        if len(repair_indexes) > 1:
            raise TraceIntegrityError("failed Run trace has multiple repair events")
        if not repair_indexes:
            if run.repair_count != 0:
                raise TraceIntegrityError("durable repair count has no trace evidence")
            types = tuple(event.event_type for event in body)
            if types != _ATTEMPT_ZERO_PATH[: len(types)]:
                raise TraceIntegrityError("failed Run stage path is reordered or discontinuous")
            if any(event.attempt != 0 for event in events):
                raise TraceIntegrityError("unrepaired failure must remain attempt zero")
            if len(body) > 1:
                self._require_success_outcomes(body[:-1])
                if body[-1].payload.get("outcome") in _NON_FAILURE_OUTCOMES:
                    raise TraceIntegrityError("failed trace has no failed-stage outcome")
            return
        repair_index = repair_indexes[0]
        original = body[:repair_index]
        repair = body[repair_index]
        replacement = body[repair_index + 1 :]
        original_types = tuple(event.event_type for event in original)
        if original_types != _ATTEMPT_ZERO_PATH[: len(original_types)]:
            raise TraceIntegrityError("failed original branch is reordered or discontinuous")
        if len(original) not in {5, 6, 7}:
            raise TraceIntegrityError(
                "repair must follow an admission, execution, or verification failure"
            )
        if original[-1].payload.get("outcome") in {"SUCCEEDED", "PASSED", "TERMINATED"}:
            raise TraceIntegrityError("repair does not follow failed stage evidence")
        if any(event.attempt != 0 for event in original):
            raise TraceIntegrityError("failed original branch must be attempt zero")
        eligible = repair.payload.get("eligible")
        outcome = repair.payload.get("outcome")
        if eligible is False:
            if repair.attempt != 0 or replacement or outcome != "NOT_ELIGIBLE":
                raise TraceIntegrityError(
                    "ineligible repair evidence has an invalid attempt branch"
                )
            if run.repair_count != 0:
                raise TraceIntegrityError("ineligible repair cannot consume durable repair count")
        elif eligible is True:
            zero_attempt_exhaustion = (
                outcome == "EXHAUSTED"
                and repair.attempt == 0
                and run.repair_count == 0
                and not replacement
            )
            if not zero_attempt_exhaustion and (repair.attempt != 1 or run.repair_count != 1):
                raise TraceIntegrityError("eligible repair must bind durable attempt one")
        else:
            raise TraceIntegrityError("repair evidence omits typed eligibility")
        replacement_types = tuple(event.event_type for event in replacement)
        if replacement_types != _ATTEMPT_ONE_PATH[: len(replacement_types)]:
            raise TraceIntegrityError("failed replacement branch is reordered or discontinuous")
        if any(event.attempt != 1 for event in replacement):
            raise TraceIntegrityError("replacement branch must be attempt one")
        if events[-1].attempt != repair.attempt:
            raise TraceIntegrityError("terminal attempt does not match repair evidence")
        self._require_success_outcomes(original[:-1])
        if replacement:
            self._require_success_outcomes(replacement[:-1])
            if replacement[-1].payload.get("outcome") in _NON_FAILURE_OUTCOMES:
                raise TraceIntegrityError("replacement failure has no failed-stage outcome")
        elif repair.payload.get("outcome") in _NON_FAILURE_OUTCOMES:
            raise TraceIntegrityError("repair failure has no failed outcome evidence")

    @staticmethod
    def _require_success_outcomes(events: tuple[TraceEvent, ...]) -> None:
        for event in events:
            expected = _SUCCESS_OUTCOMES[event.event_type]
            if event.payload.get("outcome") != expected:
                raise TraceIntegrityError(
                    f"{event.event_type.value} does not carry successful outcome evidence"
                )
