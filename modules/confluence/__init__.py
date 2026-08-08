"""Contratos y semantica descriptiva aislada del Gate CE-1."""

from .contracts import (
    CE1_CONTRACT,
    CE1_SCHEMA,
    CE1_SCHEMA_VERSION,
    CE1ContractViolation,
    validate_comparison_rule,
    validate_dependency,
    validate_observation,
    validate_semantic_relation,
    validate_synthesis,
)
from .descriptive import build_descriptive_synthesis

__all__ = (
    "CE1_CONTRACT",
    "CE1_SCHEMA",
    "CE1_SCHEMA_VERSION",
    "CE1ContractViolation",
    "build_descriptive_synthesis",
    "validate_comparison_rule",
    "validate_dependency",
    "validate_observation",
    "validate_semantic_relation",
    "validate_synthesis",
)
