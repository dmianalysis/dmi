"""Detailed Inflation Substrate v0.1 -- research modules.

Milestone 1 reproduces the 2024 Consumer Expenditure -> CPI mapping
feasibility audit from authoritative BLS source files. It builds no weights,
acquires no CPI data, and computes no index. Core DMI remains withdrawn and
unimplemented.

See ``docs/research/DETAILED_INFLATION_SUBSTRATE.md``.
"""

RESEARCH_OUTPUT_ROOT = "data/research/detailed_inflation"

# Trees a research command must never create or modify.
FORBIDDEN_OUTPUT_ROOTS = (
    "data/outputs",
    "deploy/data/outputs",
)
