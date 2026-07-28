"""Reporting contracts, claim rendering, and submission validation."""

from .claims import ClaimInterval, ClaimRecord, ClaimsBundle, load_claims, write_claims
from .contracts import (
    FigureSpec,
    ModelRegistry,
    ModelSpec,
    SensitivityFamily,
    VisualContract,
    load_model_registry,
    load_visual_contract,
)
from .science import GateEvaluation, evaluate_all_science_gates, evaluate_science_gate

__all__ = [
    "ClaimInterval",
    "ClaimRecord",
    "ClaimsBundle",
    "FigureSpec",
    "GateEvaluation",
    "ModelRegistry",
    "ModelSpec",
    "SensitivityFamily",
    "VisualContract",
    "evaluate_all_science_gates",
    "evaluate_science_gate",
    "load_claims",
    "load_model_registry",
    "load_visual_contract",
    "write_claims",
]
