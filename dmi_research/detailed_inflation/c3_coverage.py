"""Full-universe coverage assessment for the canonical ledger.

Detailed Inflation Substrate v0.1, task C3-B. Research only. Reads pinned BLS
LABSTAT flat files and the frozen canonical ledger, and writes only diagnostic
artifacts. It assigns no Track-A treatment to anything, adjudicates no scope
question, normalises nothing and computes no weight.

The question, and why it is not the reconciliation question
-----------------------------------------------------------
C3-A shows that every dollar inside the canonical ledger is accounted for
exactly once. That is a statement about the inside of a boundary and says
nothing about where the boundary is. The ledger's published basis is the
2024-active numeric UCCs of four CE domains -- Food, Alcoholic beverages,
Housing and Transportation -- because those are the domains Milestone 1
audited. A detailed DMI needs fourteen nodes, and ten CE domains have never
been through the same mapping and scope discipline.

So a ledger can reconcile perfectly and still be the wrong denominator. This
module measures how wrong, in dollars rather than in UCC counts, and refuses
to produce a ratio at all if the denominator cannot be defended.

Establishing the denominator rather than assuming it
----------------------------------------------------
The temptation is to take the 998 numeric item codes in ``cx.item`` and sum
them. That would be wrong twice over. Only 581 of them are 2024-active
expenditure series in the Income-Quintile demographic set; the rest are
inactive vintages or belong to the ``ADDENDA``, ``INCOME`` and ``CUCHARS``
categories, which are not expenditure and would double count or contaminate
the total. And additivity is a property to be tested, not assumed: Milestone 1
validated that numeric UCCs behave as leaves for four domains, and that result
does not transfer to ten domains nobody has checked.

:func:`validate_additivity` therefore runs the Milestone-1 parent
reconciliation over every domain in the universe, using the same rounding
bound derived from BLS's publication rounding rather than a tuned tolerance,
and additionally checks that the domain roots sum to the published grand
total. If any domain fails, the expenditure denominator is refused and the
coverage verdict is ``BLOCKED``. A count-based structural coverage figure is
still reported, because counting UCCs needs no additivity -- but it is
reported as a separate quantity and never as a stand-in for dollars.

Node attribution is provisional and says so
-------------------------------------------
Omitted UCCs carry a *candidate* DMI node derived from their CE domain, so
that omitted expenditure can be reported by node. That correspondence is a
diagnostic convenience declared in the coverage spec, not an adjudication:
every omitted UCC is marked as requiring scope adjudication, and C3 assigns
none. Reading a candidate node as a mapping decision would be exactly the
error this module exists to prevent.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from . import sources as S

REPO_ROOT = Path(__file__).resolve().parents[2]

TAXONOMY_PATH = REPO_ROOT / "registry/research/detailed_inflation_taxonomy_v0_1.json"
CONCORDANCE_PATH = REPO_ROOT / "registry/research/ucc_eli_concordance_2024_v0_1.tsv"

#: The published grand-total domain root. It is a parent of the other domains,
#: not a domain, so it never contributes leaves and is never summed alongside
#: them.
GRAND_TOTAL_SUBCATEGORY = "TOTALEXP"

#: CE domain -> candidate DMI node, for omitted-expenditure diagnostics only.
#:
#: This is a reporting convenience, not a mapping decision. It exists so that
#: "how much is missing, and from where" can be answered in node terms; every
#: UCC it touches is flagged ``requires_scope_adjudication``. The four audited
#: domains are absent because their UCCs are already in the ledger with real,
#: adjudicated node assignments.
CANDIDATE_NODE_BY_DOMAIN: Mapping[str, str | None] = {
    "APPAREL": "APPAREL",
    "HEALTH": "MEDICAL_CARE",
    "ENTRTAIN": "RECREATION",
    "EDUCATN": "EDUCATION_COMMUNICATION",
    "READING": "EDUCATION_COMMUNICATION",
    "PERSCARE": "OTHER_GOODS_SERVICES",
    "TOBACCO": "OTHER_GOODS_SERVICES",
    "MISC": "OTHER_GOODS_SERVICES",
    "CASHCONT": None,
    "INSPENSN": None,
}

#: CE domains that are expenditure by BLS category code but are not household
#: consumption. Cash contributions are transfers; personal insurance and
#: pensions are saving and risk transfer. Both are inside CE total
#: expenditures and outside anything a consumption price index would weight.
#:
#: They are *not* removed from the universe here. They are labelled, so that a
#: consumption-only denominator can be reported beside the full one and the
#: choice between them stays a human decision.
NONCONSUMPTION_DOMAINS: tuple[str, ...] = ("CASHCONT", "INSPENSN")

OMISSION_CLASSIFICATIONS: tuple[str, ...] = (
    "OUTSIDE_M1_AUDIT_SCOPE",
    "NONCONSUMPTION_OR_SCOPE_REVIEW_REQUIRED",
    "NOT_YET_TAXONOMY_RESOLVED",
    "PUBLISHED_BUT_NOT_CONCORDANCE_MAPPED",
    "INACTIVE_OR_VINTAGE_INAPPLICABLE",
    "DUPLICATE_OR_NONADDITIVE",
)


class C3CoverageError(RuntimeError):
    """The coverage universe cannot be constructed as declared."""


# ---------------------------------------------------------------------------
# The universe, derived from pinned sources
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UniverseCell:
    """One (ucc, population) published expenditure aggregate."""

    ucc: str
    subcategory_code: str
    population: str
    aggregate_millions: Decimal | None


@dataclass(frozen=True)
class Universe:
    """The 2024 Income-Quintile published expenditure universe."""

    cells: tuple[UniverseCell, ...]
    labels: Mapping[str, str]
    domain_by_ucc: Mapping[str, str]
    domain_parent: Mapping[tuple[str, str], Decimal | None]
    grand_total: Mapping[str, Decimal | None]
    domains: tuple[str, ...]

    @property
    def uccs(self) -> frozenset[str]:
        return frozenset(c.ucc for c in self.cells)

    def amount(self, ucc: str, population: str) -> Decimal | None:
        return self._by_key.get((ucc, population))

    @property
    def _by_key(self) -> Mapping[tuple[str, str], Decimal | None]:
        cached = getattr(self, "_amount_index", None)
        if cached is None:
            cached = {(c.ucc, c.population): c.aggregate_millions for c in self.cells}
            object.__setattr__(self, "_amount_index", cached)
        return cached


def _population_of(characteristics_code: str) -> str:
    label = S.POPULATIONS[characteristics_code]
    return "ALL_CU" if label == "All Consumer Units" else label


def _load_aggregates(
    aspect_path: Path, wanted: set[str], year: int
) -> dict[str, Decimal | None]:
    """Stream ``cx.aspect`` for the aggregate values of ``wanted``.

    ``cx.aspect`` is a 700MB file of which a few thousand rows matter, so the
    scan is positional and the cheapest discriminating field is tested first.
    A dict-based reader over thirteen million rows costs minutes for no gain.
    """
    target_year = str(year)
    aggregates: dict[str, Decimal | None] = {}
    with aspect_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader)
        header = [c.strip() for c in header]
        i_series = header.index("series_id")
        i_year = header.index("year")
        i_period = header.index("period")
        i_aspect = header.index("aspect_type")
        i_value = header.index("value")
        for row in reader:
            if row[i_year].strip() != target_year:
                continue
            if row[i_aspect].strip() != S.ASPECT_AGGREGATE:
                continue
            if row[i_period].strip() != S.ANNUAL_PERIOD:
                continue
            series_id = row[i_series].strip()
            if series_id not in wanted:
                continue
            value = row[i_value].strip()
            aggregates[series_id] = Decimal(value) if value not in ("", "-") else None
    return aggregates


def build_universe(
    series_path: Path, item_path: Path, aspect_path: Path, *, year: int = 2024
) -> Universe:
    """Construct the published expenditure universe from pinned BLS files.

    Membership is derived entirely from series metadata -- expenditure
    category, Income-Quintile demographics, one of the six populations, and
    activity in the target year -- and from the numeric-UCC test. No UCC list
    is written down anywhere in this module.
    """
    series = S.load_series(series_path)
    selected = [
        r
        for r in series
        if r.category_code == S.EXPENDITURE_CATEGORY_CODE
        and r.demographics_code == S.INCOME_QUINTILE_DEMOGRAPHICS_CODE
        and r.characteristics_code in S.POPULATIONS
        and r.begin_year <= year <= r.end_year
    ]
    if not selected:
        raise C3CoverageError(
            f"no {year} Income-Quintile expenditure series selected from {series_path}"
        )

    wanted = {r.series_id for r in selected}
    aggregates = _load_aggregates(aspect_path, wanted, year)

    items = {}
    with item_path.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle, delimiter="\t"):
            items[(raw["subcategory_code"].strip(), raw["item_code"].strip())] = raw[
                "item_text"
            ].strip()

    cells: list[UniverseCell] = []
    labels: dict[str, str] = {}
    domain_by_ucc: dict[str, str] = {}
    for record in selected:
        if not S.is_numeric_ucc(record.item_code):
            continue
        population = _population_of(record.characteristics_code)
        cells.append(
            UniverseCell(
                ucc=record.item_code,
                subcategory_code=record.subcategory_code,
                population=population,
                aggregate_millions=aggregates.get(record.series_id),
            )
        )
        labels.setdefault(
            record.item_code,
            items.get((record.subcategory_code, record.item_code), ""),
        )
        domain_by_ucc.setdefault(record.item_code, record.subcategory_code)

    domain_parent: dict[tuple[str, str], Decimal | None] = {}
    grand_total: dict[str, Decimal | None] = {}
    for record in selected:
        if record.item_code != record.subcategory_code:
            continue
        population = _population_of(record.characteristics_code)
        value = aggregates.get(record.series_id)
        if record.subcategory_code == GRAND_TOTAL_SUBCATEGORY:
            grand_total[population] = value
        domain_parent[(record.subcategory_code, population)] = value

    domains = tuple(
        sorted(
            {
                r.subcategory_code
                for r in selected
                if r.subcategory_code != GRAND_TOTAL_SUBCATEGORY
            }
        )
    )
    return Universe(
        cells=tuple(
            sorted(cells, key=lambda c: (c.ucc, POPULATIONS.index(c.population)))
        ),
        labels=labels,
        domain_by_ucc=domain_by_ucc,
        domain_parent=domain_parent,
        grand_total=grand_total,
        domains=domains,
    )


# ---------------------------------------------------------------------------
# Additivity: tested, never assumed
# ---------------------------------------------------------------------------

POPULATIONS: tuple[str, ...] = ("ALL_CU", "Q1", "Q2", "Q3", "Q4", "Q5")

#: BLS publishes aggregate expenditures rounded to whole millions, so each
#: figure carries at most half a unit of error. Summing ``n`` leaves and
#: differencing against one published parent admits at most ``0.5 * (n + 1)``.
#: This is the Milestone-1 bound, derived from the rounding rule and not
#: tuned; a double count of even the smallest leaf exceeds it by orders of
#: magnitude.
ROUNDING_UNIT = Decimal("1")


@dataclass(frozen=True)
class AdditivityResult:
    domain: str
    population: str
    leaf_count: int
    leaves_with_amount: int
    leaf_sum: Decimal
    published_parent: Decimal | None
    difference: Decimal | None
    bound: Decimal
    additive: bool


def validate_additivity(universe: Universe) -> list[AdditivityResult]:
    """Sum each domain's numeric leaves against its published parent.

    This is the Milestone-1 test run over the whole universe rather than four
    domains of it. A domain whose numeric codes nested inside one another
    would overshoot its parent by far more than rounding can explain.
    """
    results: list[AdditivityResult] = []
    for domain in universe.domains:
        for population in POPULATIONS:
            leaves = [
                c
                for c in universe.cells
                if c.subcategory_code == domain and c.population == population
            ]
            if not leaves:
                continue
            present = [c for c in leaves if c.aggregate_millions is not None]
            leaf_sum = sum((c.aggregate_millions for c in present), Decimal(0))
            parent = universe.domain_parent.get((domain, population))
            bound = ROUNDING_UNIT / 2 * (len(present) + 1)
            difference = None if parent is None else leaf_sum - parent
            results.append(
                AdditivityResult(
                    domain=domain,
                    population=population,
                    leaf_count=len(leaves),
                    leaves_with_amount=len(present),
                    leaf_sum=leaf_sum,
                    published_parent=parent,
                    difference=difference,
                    bound=bound,
                    additive=difference is not None and abs(difference) <= bound,
                )
            )
    return results


@dataclass(frozen=True)
class GrandTotalResult:
    population: str
    domain_root_sum: Decimal
    published_grand_total: Decimal | None
    difference: Decimal | None
    bound: Decimal
    additive: bool


def validate_grand_total(universe: Universe) -> list[GrandTotalResult]:
    """Check that the domain roots sum to the published total expenditure.

    Domain-level additivity alone would not catch a domain that is itself a
    child of another domain. This catches it.
    """
    out: list[GrandTotalResult] = []
    for population in POPULATIONS:
        roots = [
            universe.domain_parent.get((d, population)) for d in universe.domains
        ]
        present = [v for v in roots if v is not None]
        total = sum(present, Decimal(0))
        published = universe.grand_total.get(population)
        bound = ROUNDING_UNIT / 2 * (len(present) + 1)
        difference = None if published is None else total - published
        out.append(
            GrandTotalResult(
                population=population,
                domain_root_sum=total,
                published_grand_total=published,
                difference=difference,
                bound=bound,
                additive=difference is not None and abs(difference) <= bound,
            )
        )
    return out


def additivity_established(
    domain_results: Sequence[AdditivityResult],
    grand_results: Sequence[GrandTotalResult],
) -> bool:
    """Whether an additive expenditure denominator may be used at all."""
    return (
        bool(domain_results)
        and all(r.additive for r in domain_results)
        and bool(grand_results)
        and all(r.additive for r in grand_results)
    )


# ---------------------------------------------------------------------------
# Omission ledger
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OmittedRow:
    ucc: str
    label: str
    published_ce_domain: str
    candidate_dmi_node: str
    node_resolution_status: str
    ce_source: str
    amounts: Mapping[str, Decimal | None]
    currently_in_canonical_ledger: bool
    omission_classification: str
    concordance_status: str
    requires_scope_adjudication: bool
    requires_pumd: bool
    requires_new_domain_audit: bool
    note: str


def load_concordance(path: Path = CONCORDANCE_PATH) -> dict[str, str]:
    """``ucc -> ce_source`` for every UCC the 2024 CE->CPI concordance names."""
    out: dict[str, str] = {}
    for row in csv.DictReader(path.read_text(encoding="utf-8").splitlines(), delimiter="\t"):
        ucc = row["ucc"].strip()
        if ucc:
            out.setdefault(ucc, row["ce_source"].strip())
    return out


def omitted_ledger(
    universe: Universe,
    canonical_uccs: Iterable[str],
    audited_domains: Iterable[str],
    concordance: Mapping[str, str],
) -> list[OmittedRow]:
    """One diagnostic row per published UCC absent from the canonical ledger.

    Every omitted UCC receives exactly one classification and an observable
    reason. In particular, absence from the CE->CPI concordance is recorded as
    a fact and never used as the reason for omission: Milestone 2 established
    that a UCC missing from the concordance is not thereby out of CPI scope,
    and re-importing that fallacy here would quietly adjudicate 244 UCCs.
    """
    canonical = set(canonical_uccs)
    audited = set(audited_domains)
    rows: list[OmittedRow] = []
    for ucc in sorted(universe.uccs - canonical):
        domain = universe.domain_by_ucc[ucc]
        candidate = CANDIDATE_NODE_BY_DOMAIN.get(domain)
        nonconsumption = domain in NONCONSUMPTION_DOMAINS

        if nonconsumption:
            classification = "NONCONSUMPTION_OR_SCOPE_REVIEW_REQUIRED"
            note = (
                "Inside CE total expenditures and outside household "
                "consumption. Whether a consumption price index should weight "
                "it is a scope question C3 does not answer."
            )
        elif domain not in audited:
            classification = "OUTSIDE_M1_AUDIT_SCOPE"
            note = (
                "Published and 2024-active, in a CE domain the Milestone-1 "
                "audit did not cover. No mapping, scope or provenance work "
                "has been done on it."
            )
        else:
            classification = "NOT_YET_TAXONOMY_RESOLVED"
            note = (
                "In an audited domain yet absent from the canonical ledger. "
                "This should not occur and is reported rather than hidden."
            )

        rows.append(
            OmittedRow(
                ucc=ucc,
                label=universe.labels.get(ucc, ""),
                published_ce_domain=domain,
                candidate_dmi_node=candidate or "",
                node_resolution_status=(
                    "CANDIDATE_FROM_CE_DOMAIN"
                    if candidate
                    else "NO_CANDIDATE_NONCONSUMPTION"
                ),
                ce_source=concordance.get(ucc, ""),
                amounts={
                    p: universe.amount(ucc, p) for p in POPULATIONS
                },
                currently_in_canonical_ledger=False,
                omission_classification=classification,
                concordance_status=(
                    "NAMED_BY_2024_CONCORDANCE"
                    if ucc in concordance
                    else "ABSENT_FROM_2024_CONCORDANCE"
                ),
                requires_scope_adjudication=True,
                requires_pumd=False,
                requires_new_domain_audit=not nonconsumption,
                note=note,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PopulationCoverage:
    population: str
    universe_expenditure: Decimal | None
    consumption_universe_expenditure: Decimal | None
    canonical_source_expenditure: Decimal
    covered_share_of_universe: Decimal | None
    covered_share_of_consumption_universe: Decimal | None
    omitted_expenditure: Decimal | None
    omitted_nonconsumption_expenditure: Decimal | None


def population_coverage(
    universe: Universe,
    canonical_uccs: Iterable[str],
    canonical_source_by_population: Mapping[str, Decimal],
    additivity_ok: bool,
) -> list[PopulationCoverage]:
    """Expenditure coverage by population, or ``None`` if additivity failed.

    When additivity is not established every ratio is ``None``. A fabricated
    percentage is worse than no percentage: it would be quoted.
    """
    canonical = set(canonical_uccs)
    out: list[PopulationCoverage] = []
    for population in POPULATIONS:
        if not additivity_ok:
            out.append(
                PopulationCoverage(
                    population=population,
                    universe_expenditure=None,
                    consumption_universe_expenditure=None,
                    canonical_source_expenditure=canonical_source_by_population[
                        population
                    ],
                    covered_share_of_universe=None,
                    covered_share_of_consumption_universe=None,
                    omitted_expenditure=None,
                    omitted_nonconsumption_expenditure=None,
                )
            )
            continue

        total = Decimal(0)
        consumption = Decimal(0)
        omitted = Decimal(0)
        omitted_nonconsumption = Decimal(0)
        for cell in universe.cells:
            if cell.population != population or cell.aggregate_millions is None:
                continue
            nonconsumption = cell.subcategory_code in NONCONSUMPTION_DOMAINS
            total += cell.aggregate_millions
            if not nonconsumption:
                consumption += cell.aggregate_millions
            if cell.ucc not in canonical:
                omitted += cell.aggregate_millions
                if nonconsumption:
                    omitted_nonconsumption += cell.aggregate_millions

        covered = canonical_source_by_population[population]
        out.append(
            PopulationCoverage(
                population=population,
                universe_expenditure=total,
                consumption_universe_expenditure=consumption,
                canonical_source_expenditure=covered,
                covered_share_of_universe=covered / total if total else None,
                covered_share_of_consumption_universe=(
                    covered / consumption if consumption else None
                ),
                omitted_expenditure=omitted,
                omitted_nonconsumption_expenditure=omitted_nonconsumption,
            )
        )
    return out


NODE_COVERAGE_STATES: tuple[str, ...] = (
    "AUDITED_AND_REPRESENTED",
    "PARTIALLY_REPRESENTED",
    "STRUCTURALLY_REPRESENTED_BUT_UNAUDITED",
    "ABSENT_FROM_CANONICAL_BASIS",
    "BLOCKED",
)


def taxonomy_nodes(path: Path = TAXONOMY_PATH) -> tuple[str, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(node["category_id"] for node in payload["nodes"])


@dataclass(frozen=True)
class NodeCoverage:
    node: str
    coverage_state: str
    canonical_ucc_count: int
    canonical_source_all_cu: Decimal | None
    omitted_candidate_ucc_count: int
    omitted_candidate_all_cu: Decimal | None
    audited_domain_origin: bool
    note: str


def node_coverage(
    nodes: Sequence[str],
    canonical_node_uccs: Mapping[str, set[str]],
    canonical_node_all_cu: Mapping[str, Decimal | None],
    omitted: Sequence[OmittedRow],
    additivity_ok: bool,
) -> list[NodeCoverage]:
    """A coverage state for every taxonomy node, including nodes with none.

    A node is never called covered merely because a UCC maps to it. A node
    whose canonical UCCs came only from the four audited domains, while a
    materially larger omitted candidate pool sits outside, is
    ``PARTIALLY_REPRESENTED`` -- the honest description of Recreation, whose
    single canonical UCC sits beside an entire unaudited CE domain.
    """
    out: list[NodeCoverage] = []
    for node in nodes:
        canonical_uccs = canonical_node_uccs.get(node, set())
        omitted_rows = [r for r in omitted if r.candidate_dmi_node == node]
        omitted_amount: Decimal | None = None
        if additivity_ok:
            omitted_amount = sum(
                (
                    r.amounts["ALL_CU"]
                    for r in omitted_rows
                    if r.amounts["ALL_CU"] is not None
                ),
                Decimal(0),
            )

        if not canonical_uccs and not omitted_rows:
            state = "ABSENT_FROM_CANONICAL_BASIS"
            note = (
                "No canonical UCC and no omitted published UCC carries this "
                "node. The node exists in the taxonomy and nothing in the "
                "2024 published universe has been attributed to it."
            )
        elif not canonical_uccs:
            state = "ABSENT_FROM_CANONICAL_BASIS"
            note = (
                "Entirely absent from the canonical basis. Its candidate "
                "expenditure sits in a CE domain that has never been audited."
            )
        elif omitted_rows:
            state = "PARTIALLY_REPRESENTED"
            note = (
                "Present in the canonical basis and materially incomplete: "
                "published expenditure with this candidate node sits outside "
                "the audited domains."
            )
        else:
            state = "AUDITED_AND_REPRESENTED"
            note = (
                "Every published UCC carrying this node is in the canonical "
                "basis, which was audited by Milestone 1."
            )
        out.append(
            NodeCoverage(
                node=node,
                coverage_state=state,
                canonical_ucc_count=len(canonical_uccs),
                canonical_source_all_cu=canonical_node_all_cu.get(node),
                omitted_candidate_ucc_count=len(omitted_rows),
                omitted_candidate_all_cu=omitted_amount,
                audited_domain_origin=bool(canonical_uccs),
                note=note,
            )
        )
    return out
