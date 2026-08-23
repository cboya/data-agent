import pytest
from pydantic import ValidationError

from data_agent.contracts import (
    Cardinality,
    CatalogColumn,
    CatalogDocument,
    ExpectedColumn,
    QueryPlan,
    Relationship,
    RetrievalHit,
    RetrievalResult,
    SQLGuardResult,
)


def test_catalog_retrieval_and_query_contracts_compose() -> None:
    relationship = Relationship(
        version="v0.1",
        from_table="fact_order",
        from_column="user_id",
        to_table="dim_user",
        to_column="id",
        cardinality=Cardinality.MANY_TO_ONE,
        description="Each order belongs to one user",
        curated=True,
    )
    catalog = CatalogDocument(
        version="v0.1",
        table="fact_order",
        description="Order-level facts",
        columns=[CatalogColumn(name="paid_amount", data_type="decimal(12,2)")],
        generated_metadata_fingerprint="schema-sha256",
        semantic_revision="semantic-v1",
    )
    retrieval = RetrievalResult(
        version="v0.1",
        query="按地区统计实付金额",
        hits=[
            RetrievalHit(
                table="fact_order",
                lexical_rank=1,
                fused_score=1.0,
                source="SEED",
            )
        ],
        relationships=[relationship],
        index_fingerprint="index-sha256",
    )
    plan = QueryPlan(
        version="v0.1",
        intent="Sum paid amount",
        tables=[catalog.table],
        sql="SELECT SUM(paid_amount) AS paid_amount FROM fact_order",
        expected_columns=[ExpectedColumn(name="paid_amount", semantic_role="metric")],
    )

    assert retrieval.relationships == [relationship]
    assert plan.tables == [catalog.table]


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (
            RetrievalHit,
            {"table": "fact_order", "fused_score": 1.0, "source": "UNKNOWN"},
        ),
        (
            Relationship,
            {
                "version": "v0.1",
                "from_table": "fact_order",
                "from_column": "user_id",
                "to_table": "dim_user",
                "to_column": "id",
                "cardinality": "SOMETIMES",
                "description": "invalid enum",
                "curated": True,
            },
        ),
        (
            SQLGuardResult,
            {"status": "MAYBE", "referenced_tables": [], "violations": []},
        ),
    ],
)
def test_unknown_enum_values_fail(model: type[object], values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        model(**values)


def test_unknown_fields_fail_at_contract_boundary() -> None:
    with pytest.raises(ValidationError, match="unexpected"):
        CatalogColumn(
            name="paid_amount",
            data_type="decimal(12,2)",
            unexpected="not part of the contract",  # type: ignore[call-arg]
        )
