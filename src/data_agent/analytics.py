"""Single-active-source identity and scope for the analytics data plane."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_agent.config import Settings

MAX_ANALYTICS_SOURCE_TABLES = 100


def _fingerprint(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AnalyticsSourceProfile(BaseModel):
    """Credential-free identity for exactly one selected MySQL analytics surface."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["analytics-source-profile-v0.1"] = "analytics-source-profile-v0.1"
    source_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    mode: Literal["SYNTHETIC", "EXTERNAL"]
    backend: Literal["mysql"] = "mysql"
    database: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_]+$")
    allowed_tables: tuple[str, ...] = Field(min_length=1, max_length=MAX_ANALYTICS_SOURCE_TABLES)
    catalog_workspace: str = Field(
        min_length=1,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    )
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def build(
        cls,
        *,
        source_id: str,
        mode: Literal["SYNTHETIC", "EXTERNAL"],
        database: str,
        allowed_tables: tuple[str, ...],
        catalog_workspace: str,
    ) -> Self:
        canonical_tables = tuple(sorted(allowed_tables))
        payload: dict[str, object] = {
            "version": "analytics-source-profile-v0.1",
            "source_id": source_id,
            "mode": mode,
            "backend": "mysql",
            "database": database,
            "allowed_tables": canonical_tables,
            "catalog_workspace": catalog_workspace,
        }
        return cls(
            source_id=source_id,
            mode=mode,
            database=database,
            allowed_tables=canonical_tables,
            catalog_workspace=catalog_workspace,
            fingerprint=_fingerprint(payload),
        )

    @model_validator(mode="after")
    def scope_is_canonical_and_untampered(self) -> Self:
        if any(re.fullmatch(r"[A-Za-z0-9_]{1,64}", table) is None for table in self.allowed_tables):
            raise ValueError("allowed table names must be MySQL-safe identifiers")
        if list(self.allowed_tables) != sorted(self.allowed_tables):
            raise ValueError("allowed tables must be canonically sorted")
        if len(self.allowed_tables) != len(set(self.allowed_tables)):
            raise ValueError("allowed tables must be unique")
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        if self.fingerprint != _fingerprint(payload):
            raise ValueError("analytics source profile fingerprint does not match its content")
        return self


def active_analytics_source(settings: Settings) -> AnalyticsSourceProfile:
    """Build the one active credential-free profile from validated settings."""

    return AnalyticsSourceProfile.build(
        source_id=settings.analytics_source_id,
        mode=settings.analytics_source_mode,
        database=settings.mysql_database,
        allowed_tables=settings.analytics_allowed_tables,
        catalog_workspace=settings.analytics_catalog_workspace,
    )
