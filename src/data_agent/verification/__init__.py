"""Deterministic, evidence-only M12 verification."""

from data_agent.verification.context import VerificationContext, build_verification_context
from data_agent.verification.errors import VerificationError, VerificationIntegrityError
from data_agent.verification.evidence import (
    CoverageDisposition,
    VerificationCoverageGap,
    VerificationEvidenceIdentity,
    VerificationTrace,
)
from data_agent.verification.service import DeterministicVerifier

__all__ = [
    "CoverageDisposition",
    "DeterministicVerifier",
    "VerificationContext",
    "VerificationCoverageGap",
    "VerificationError",
    "VerificationEvidenceIdentity",
    "VerificationIntegrityError",
    "VerificationTrace",
    "build_verification_context",
]
