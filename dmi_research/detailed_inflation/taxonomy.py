"""Research mapping-status model and candidate computation taxonomy.

Detailed Inflation Substrate v0.1, Milestone 1 (prompt sections 6, 7, 8).

This module holds *substrate metadata*, not Core logic. Nothing here is wired
into ``dmi_calculator`` or any operational specification, and Core DMI remains
withdrawn and unimplemented.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

REGISTRY_DIR = Path(__file__).resolve().parents[2] / "registry" / "research"
TAXONOMY_PATH = REGISTRY_DIR / "detailed_inflation_taxonomy_v0_1.json"
ELI_MAP_PATH = REGISTRY_DIR / "eli_to_node_map_v0_1.json"

#: Structural form of a BLS CPI series identifier, e.g. ``CUUR0000SAF116``.
CPI_SERIES_ID_RE = re.compile(r"^CUU[RS][0-9]{4}[A-Z0-9]+$")

#: Structural form of a BLS Entry Level Item code, e.g. ``TB011``.
ELI_RE = re.compile(r"^[A-Z]{2}[0-9]{3}$")


class MappingStatus(str, Enum):
    """The five detailed-substrate mapping statuses.

    Milestone 1 populates ``DIRECT``, ``MULTI_SAME_NODE`` and preliminary
    ``UNRESOLVED`` automatically from the pinned concordance.
    ``TRANSFORMED`` and ``OUT_OF_SCOPE`` exist in the model and schema but
    require CE/CPI scope rules that are a later milestone's work. A UCC with
    no concordance row is **not** treated as ``OUT_OF_SCOPE``.
    """

    DIRECT = "DIRECT"
    MULTI_SAME_NODE = "MULTI_SAME_NODE"
    TRANSFORMED = "TRANSFORMED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    UNRESOLVED = "UNRESOLVED"


#: Statuses Milestone 1 is permitted to assign automatically.
MILESTONE_1_AUTOMATIC_STATUSES = frozenset(
    {MappingStatus.DIRECT, MappingStatus.MULTI_SAME_NODE, MappingStatus.UNRESOLVED}
)


class Classification(str, Enum):
    """Substrate classification used by a future Core-style decomposition."""

    FOOD = "FOOD"
    ENERGY = "ENERGY"
    OTHER = "OTHER"


#: Prompt section 7 classification rule, restated here so the registry can be
#: validated against it rather than trusted.
EXPECTED_CLASSIFICATIONS = {
    "FOOD": Classification.FOOD,
    "HOUSEHOLD_ENERGY": Classification.ENERGY,
    "MOTOR_FUEL": Classification.ENERGY,
}

REQUIRED_NODE_IDS = (
    "FOOD",
    "ALCOHOLIC_BEVERAGES",
    "SHELTER",
    "HOUSEHOLD_ENERGY",
    "WATER_SEWER_TRASH",
    "HOUSEHOLD_FURNISHINGS_OPERATIONS",
    "APPAREL",
    "TRANSPORT_COMMODITIES_EX_MOTOR_FUEL",
    "MOTOR_FUEL",
    "TRANSPORT_SERVICES",
    "MEDICAL_CARE",
    "RECREATION",
    "EDUCATION_COMMUNICATION",
    "OTHER_GOODS_SERVICES",
)

REQUIRED_NODE_FIELDS = (
    "category_id",
    "label",
    "reporting_parent",
    "classification",
    "candidate_cpi_series_id",
    "notes",
)


@dataclass(frozen=True)
class ComputationNode:
    category_id: str
    label: str
    reporting_parent: str
    classification: Classification
    candidate_cpi_series_id: str
    notes: str


class TaxonomyError(ValueError):
    """Raised when the research taxonomy registry is internally inconsistent."""


class UnknownEliError(KeyError):
    """Raised when an ELI cannot be resolved to a computation node.

    This is deliberately fatal. Silently dropping an unmapped ELI would
    understate the mapped share of expenditure and hide a concordance change.
    """


def load_taxonomy(path: Path = TAXONOMY_PATH) -> dict[str, ComputationNode]:
    """Load and validate the 14-node candidate taxonomy."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list):
        raise TaxonomyError(f"{path.name}: 'nodes' must be a list.")

    nodes: dict[str, ComputationNode] = {}
    for raw in raw_nodes:
        missing = [f for f in REQUIRED_NODE_FIELDS if f not in raw]
        if missing:
            raise TaxonomyError(
                f"{path.name}: node {raw.get('category_id')!r} is missing "
                f"required fields {missing}."
            )
        category_id = raw["category_id"]
        if category_id in nodes:
            raise TaxonomyError(f"{path.name}: duplicate node {category_id!r}.")
        try:
            classification = Classification(raw["classification"])
        except ValueError:
            raise TaxonomyError(
                f"{path.name}: node {category_id!r} has unknown classification "
                f"{raw['classification']!r}."
            )
        nodes[category_id] = ComputationNode(
            category_id=category_id,
            label=raw["label"],
            reporting_parent=raw["reporting_parent"],
            classification=classification,
            candidate_cpi_series_id=raw["candidate_cpi_series_id"],
            notes=raw["notes"],
        )

    validate_taxonomy(nodes, source=path.name)
    return nodes


def validate_taxonomy(
    nodes: dict[str, ComputationNode], *, source: str = "taxonomy"
) -> None:
    """Assert the taxonomy matches the specification rather than trusting it."""
    missing = [node_id for node_id in REQUIRED_NODE_IDS if node_id not in nodes]
    if missing:
        raise TaxonomyError(f"{source}: missing required nodes {missing}.")
    extra = sorted(set(nodes) - set(REQUIRED_NODE_IDS))
    if extra:
        raise TaxonomyError(f"{source}: unexpected nodes {extra}.")

    for node_id, node in nodes.items():
        expected = EXPECTED_CLASSIFICATIONS.get(node_id, Classification.OTHER)
        if node.classification is not expected:
            raise TaxonomyError(
                f"{source}: node {node_id!r} is classified "
                f"{node.classification.value!r}; the section 7 rule requires "
                f"{expected.value!r}."
            )
        if not CPI_SERIES_ID_RE.match(node.candidate_cpi_series_id):
            raise TaxonomyError(
                f"{source}: node {node_id!r} candidate CPI series "
                f"{node.candidate_cpi_series_id!r} is not a well-formed BLS "
                "CPI series identifier."
            )

    series_ids = [node.candidate_cpi_series_id for node in nodes.values()]
    duplicates = sorted({s for s in series_ids if series_ids.count(s) > 1})
    if duplicates:
        raise TaxonomyError(
            f"{source}: candidate CPI series reused across nodes: {duplicates}."
        )


class EliNodeResolver:
    """Resolves a BLS ELI to exactly one candidate computation node.

    Resolution order is exact-override, then exact two-character ELI prefix.
    There is no fallback and no default node; an unmapped ELI raises
    :class:`UnknownEliError`.
    """

    def __init__(
        self,
        prefix_map: dict[str, str],
        overrides: dict[str, str],
        nodes: dict[str, ComputationNode],
    ) -> None:
        unknown = sorted(
            {n for n in list(prefix_map.values()) + list(overrides.values())}
            - set(nodes)
        )
        if unknown:
            raise TaxonomyError(
                f"ELI map references nodes absent from the taxonomy: {unknown}."
            )
        bad_prefixes = sorted(p for p in prefix_map if not re.fullmatch(r"[A-Z]{2}", p))
        if bad_prefixes:
            raise TaxonomyError(
                f"ELI map has malformed prefix keys: {bad_prefixes}."
            )
        bad_overrides = sorted(e for e in overrides if not ELI_RE.match(e))
        if bad_overrides:
            raise TaxonomyError(
                f"ELI map has malformed override keys: {bad_overrides}."
            )
        self._prefix_map = dict(prefix_map)
        self._overrides = dict(overrides)
        self._nodes = nodes

    def resolve(self, eli: str) -> str:
        """Return the ``category_id`` for ``eli``."""
        if not ELI_RE.match(eli):
            raise UnknownEliError(
                f"{eli!r} is not a well-formed BLS ELI code (expected two "
                "uppercase letters followed by three digits)."
            )
        if eli in self._overrides:
            return self._overrides[eli]
        node = self._prefix_map.get(eli[:2])
        if node is None:
            raise UnknownEliError(
                f"ELI {eli!r} (prefix {eli[:2]!r}) has no entry in "
                f"{ELI_MAP_PATH.name}. Add it deliberately; the resolver has "
                "no default node."
            )
        return node

    def node(self, category_id: str) -> ComputationNode:
        return self._nodes[category_id]

    @property
    def known_prefixes(self) -> frozenset[str]:
        return frozenset(self._prefix_map)


def load_eli_resolver(
    nodes: dict[str, ComputationNode], path: Path = ELI_MAP_PATH
) -> EliNodeResolver:
    """Load the ELI -> node map and bind it to a validated taxonomy."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    prefix_map = payload.get("eli_prefix_to_node")
    overrides_raw = payload.get("eli_overrides", {})
    if not isinstance(prefix_map, dict) or not prefix_map:
        raise TaxonomyError(f"{path.name}: 'eli_prefix_to_node' must be a non-empty object.")
    overrides = {eli: entry["node"] for eli, entry in overrides_raw.items()}
    return EliNodeResolver(prefix_map, overrides, nodes)
