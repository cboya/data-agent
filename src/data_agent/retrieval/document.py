"""Deterministic retrieval-document projection from governed M6 catalog documents."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from data_agent.contracts.catalog import CatalogColumn, CatalogDocument

RETRIEVAL_DOCUMENT_BUILDER_VERSION: Literal["retrieval-document-v0.1"] = "retrieval-document-v0.1"

_SEGMENT_PATTERN = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*|[\u3400-\u4dbf\u4e00-\u9fff]+")
_CJK_PATTERN = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff]+$")


class RetrievalDocument(BaseModel):
    """Versioned derived text and tokens for one immutable catalog document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    builder_version: Literal["retrieval-document-v0.1"]
    table: str = Field(min_length=1, pattern=r"\S")
    text: str = Field(min_length=1, pattern=r"\S")
    tokens: tuple[str, ...] = Field(min_length=1)


def _normalized_sort(values: list[str]) -> list[str]:
    return sorted(values, key=lambda value: unicodedata.normalize("NFKC", value).casefold())


def tokenize(text: str) -> tuple[str, ...]:
    """Tokenize bilingual catalog/query text with no locale or external-service dependency."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    terms: list[str] = []
    for segment in _SEGMENT_PATTERN.findall(normalized):
        if _CJK_PATTERN.fullmatch(segment) is not None:
            terms.extend(segment)
            terms.extend(segment[index : index + 2] for index in range(len(segment) - 1))
            if len(segment) > 2:
                terms.append(segment)
            continue
        terms.append(segment)
        if "_" in segment:
            terms.extend(part for part in segment.split("_") if part)
    return tuple(terms)


def _column_line(column: CatalogColumn) -> str:
    aliases = ", ".join(_normalized_sort([str(alias) for alias in column.aliases])) or "-"
    description = str(column.description) if column.description is not None else "-"
    return (
        f"- {column.name} | type={column.data_type} | aliases={aliases} | description={description}"
    )


def project_catalog_document(document: CatalogDocument) -> RetrievalDocument:
    """Create a canonical retrieval projection without mutating M6 semantic authority."""
    aliases = ", ".join(_normalized_sort([str(alias) for alias in document.aliases])) or "-"
    business_rules = _normalized_sort([str(rule) for rule in document.business_rules])
    use_cases = _normalized_sort([str(use_case) for use_case in document.typical_use_cases])
    columns = sorted(document.columns, key=lambda column: str(column.name))

    lines = [
        f"Table: {document.table}",
        f"Aliases: {aliases}",
        f"Description: {document.description}",
        "Business rules:",
        *(f"- {rule}" for rule in business_rules),
        "Columns:",
        *(_column_line(column) for column in columns),
        "Typical use cases:",
        *(f"- {use_case}" for use_case in use_cases),
    ]
    text = "\n".join(lines)
    return RetrievalDocument(
        builder_version=RETRIEVAL_DOCUMENT_BUILDER_VERSION,
        table=str(document.table),
        text=text,
        tokens=tokenize(text),
    )
