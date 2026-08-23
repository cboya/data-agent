"""Shared validation primitives for domain contracts."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

ContractVersion = Literal["v0.1"]
NonEmptyString = Annotated[str, StringConstraints(pattern=r"\S")]


def _require_timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


AwareDateTime = Annotated[datetime, AfterValidator(_require_timezone_aware)]


class ContractModel(BaseModel):
    """Strict base for values crossing a domain or persistence boundary."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        allow_inf_nan=False,
    )
