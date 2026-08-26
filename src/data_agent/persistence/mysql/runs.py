"""MySQL Run repository with atomic state-machine transitions."""

from datetime import datetime
from typing import cast

import pymysql
from pydantic import ValidationError

from data_agent.config import Settings
from data_agent.contracts.run import Run, RunStatus
from data_agent.persistence.errors import (
    CorruptRecordError,
    PersistenceInvariantError,
    RecordNotFoundError,
    RepairAttemptsExhaustedError,
)
from data_agent.persistence.mysql.common import (
    control_connection,
    corrupt_record,
    from_database_datetime,
    raise_write_error,
    require_int,
    require_string,
    to_database_datetime,
)
from data_agent.run_state import TERMINAL_RUN_STATUSES, RunStateMachine


def _run_from_row(row: tuple[object, ...]) -> Run:
    try:
        completed_at = (
            None
            if row[5] is None
            else from_database_datetime(row[5], field="agent_run.completed_at")
        )
        error_code = (
            None if row[6] is None else require_string(row[6], field="agent_run.error_code")
        )
        run = Run.model_validate(
            {
                "id": row[0],
                "session_id": row[1],
                "status": row[2],
                "repair_count": require_int(row[3], field="agent_run.repair_count"),
                "started_at": from_database_datetime(row[4], field="agent_run.started_at"),
                "completed_at": completed_at,
                "error_code": error_code,
            }
        )
        RunStateMachine.require_consistent(run)
        return run
    except (ValidationError, ValueError) as error:
        if isinstance(error, CorruptRecordError):
            raise
        raise corrupt_record("agent_run", error) from error


class MySQLRunRepository:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(self, run: Run) -> Run:
        RunStateMachine.require_initial(run)
        connection = control_connection(self._settings)
        try:
            with connection.cursor() as cursor:
                try:
                    cursor.execute(
                        "INSERT INTO agent_run "
                        "(id, session_id, status, repair_count, started_at, "
                        "completed_at, error_code) "
                        "VALUES (%s, %s, %s, %s, %s, NULL, NULL)",
                        (
                            run.id,
                            run.session_id,
                            run.status.value,
                            run.repair_count,
                            to_database_datetime(run.started_at),
                        ),
                    )
                except pymysql.MySQLError as error:
                    raise_write_error(error, record=f"Run {run.id}")
        finally:
            connection.close()
        return run

    def get(self, run_id: str) -> Run:
        connection = control_connection(self._settings)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, session_id, status, repair_count, started_at, "
                    "completed_at, error_code FROM agent_run WHERE id = %s",
                    (run_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if row is None:
            raise RecordNotFoundError(f"Run {run_id} does not exist")
        return _run_from_row(cast(tuple[object, ...], row))

    def transition(
        self,
        run_id: str,
        target: RunStatus,
        *,
        transitioned_at: datetime,
        error_code: str | None = None,
    ) -> Run:
        connection = control_connection(self._settings, autocommit=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, session_id, status, repair_count, started_at, "
                    "completed_at, error_code FROM agent_run WHERE id = %s FOR UPDATE",
                    (run_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RecordNotFoundError(f"Run {run_id} does not exist")
                current = _run_from_row(cast(tuple[object, ...], row))
                RunStateMachine.transition(current.status, target)
                completed_at = transitioned_at if target in TERMINAL_RUN_STATUSES else None
                updated = Run.model_validate(
                    {
                        **current.model_dump(),
                        "status": target,
                        "completed_at": completed_at,
                        "error_code": error_code,
                    }
                )
                RunStateMachine.require_consistent(updated)
                cursor.execute(
                    "UPDATE agent_run SET status = %s, completed_at = %s, error_code = %s "
                    "WHERE id = %s",
                    (
                        target.value,
                        None if completed_at is None else to_database_datetime(completed_at),
                        error_code,
                        run_id,
                    ),
                )
            connection.commit()
            return updated
        except (RecordNotFoundError, ValidationError, ValueError):
            connection.rollback()
            raise
        except pymysql.MySQLError as error:
            connection.rollback()
            raise_write_error(error, record=f"Run {run_id}")
        finally:
            connection.close()

    def claim_repair(
        self,
        run_id: str,
        *,
        max_attempts: int,
        expected_status: RunStatus,
    ) -> Run:
        """Atomically validate the failure stage and consume one repair attempt."""

        if max_attempts < 0:
            raise ValueError("repair-attempt bound cannot be negative")
        connection = control_connection(self._settings, autocommit=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, session_id, status, repair_count, started_at, "
                    "completed_at, error_code FROM agent_run WHERE id = %s FOR UPDATE",
                    (run_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RecordNotFoundError(f"Run {run_id} does not exist")
                current = _run_from_row(cast(tuple[object, ...], row))
                if current.repair_count >= max_attempts:
                    raise RepairAttemptsExhaustedError(
                        f"Run {run_id} exhausted its repair-attempt bound"
                    )
                if current.status is not expected_status:
                    raise PersistenceInvariantError(
                        "Run status does not match repair failure stage: "
                        f"expected {expected_status.value}, found {current.status.value}"
                    )
                if current.status is not RunStatus.VALIDATING:
                    RunStateMachine.transition(current.status, RunStatus.VALIDATING)
                updated = Run.model_validate(
                    {
                        **current.model_dump(),
                        "status": RunStatus.VALIDATING,
                        "repair_count": current.repair_count + 1,
                        "completed_at": None,
                        "error_code": None,
                    }
                )
                RunStateMachine.require_consistent(updated)
                cursor.execute(
                    "UPDATE agent_run SET status = %s, repair_count = %s, "
                    "completed_at = NULL, error_code = NULL WHERE id = %s",
                    (RunStatus.VALIDATING.value, updated.repair_count, run_id),
                )
            connection.commit()
            return updated
        except (
            RecordNotFoundError,
            RepairAttemptsExhaustedError,
            PersistenceInvariantError,
            ValidationError,
            ValueError,
        ):
            connection.rollback()
            raise
        except pymysql.MySQLError as error:
            connection.rollback()
            raise_write_error(error, record=f"Run {run_id}")
        finally:
            connection.close()
