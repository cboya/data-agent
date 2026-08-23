import pymysql
import pytest

from data_agent.config import Settings
from data_agent.infrastructure.mysql_world import (
    FixtureSummary,
    fixture_summary,
    readonly_connection,
)


@pytest.mark.integration
def test_deterministic_fixture_summary(settings: Settings) -> None:
    assert fixture_summary(settings) == FixtureSummary(
        table_count=10,
        order_count=10,
        paid_amount_total="1545.00",
        successful_refund_total="110.00",
    )


@pytest.mark.integration
def test_runtime_principal_can_select(settings: Settings) -> None:
    connection = readonly_connection(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM fact_order")
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == 10
    finally:
        connection.close()


@pytest.mark.integration
def test_runtime_principal_cannot_write(settings: Settings) -> None:
    connection = readonly_connection(settings)
    try:
        with connection.cursor() as cursor, pytest.raises(pymysql.MySQLError) as error:
            cursor.execute("UPDATE dim_region SET province = province WHERE id = 1")
    finally:
        connection.close()
    assert error.value.args[0] == 1142
