from data_agent.contracts.catalog import CatalogColumn, CatalogDocument
from data_agent.retrieval.document import project_catalog_document, tokenize
from tests.retrieval.factories import GENERATED_FINGERPRINT, SEMANTIC_REVISION


def _catalog_document(*, reverse: bool) -> CatalogDocument:
    rules = ["paid amount is authoritative", "avoid fan-out"]
    columns = [
        CatalogColumn(name="paid_amount", data_type="decimal", description="实际支付金额"),
        CatalogColumn(name="id", data_type="bigint", description="订单标识"),
    ]
    aliases = ["订单", "order"]
    use_cases = ["GMV", "支付金额"]
    if reverse:
        rules.reverse()
        columns.reverse()
        aliases.reverse()
        use_cases.reverse()
    return CatalogDocument(
        version="v0.1",
        table="fact_order",
        aliases=aliases,
        description="订单事实",
        business_rules=rules,
        columns=columns,
        typical_use_cases=use_cases,
        generated_metadata_fingerprint=GENERATED_FINGERPRINT,
        semantic_revision=SEMANTIC_REVISION,
    )


def test_projection_is_deterministic_and_preserves_semantic_fields() -> None:
    first = project_catalog_document(_catalog_document(reverse=False))
    second = project_catalog_document(_catalog_document(reverse=True))

    assert first == second
    assert first.builder_version == "retrieval-document-v0.1"
    assert "paid_amount" in first.text
    assert "实际支付金额" in first.text
    assert "avoid fan-out" in first.text


def test_bilingual_tokenization_splits_identifiers_and_cjk_bigrams() -> None:
    tokens = tokenize("Paid_Amount 最近支付金额")

    assert "paid_amount" in tokens
    assert "paid" in tokens
    assert "amount" in tokens
    assert "支付" in tokens
    assert "金额" in tokens
