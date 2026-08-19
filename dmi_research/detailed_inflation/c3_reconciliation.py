"""Internal accounting reconciliation of the frozen canonical ledger.

Detailed Inflation Substrate v0.1, task C3-A. Research only. Reads the frozen
C1+C2 ledger and writes nothing outside ``data/research/detailed_inflation``.
It computes no weight, no share, no denominator and no index.

What this module claims, and what it does not
---------------------------------------------
It claims that every source amount the canonical ledger carries is accounted
for exactly once, and that the amount currently in force in the CPI-compatible
Track-A substrate is what the governing rules say it is. It claims nothing at
all about whether that substrate covers the expenditure universe a detailed
DMI would need. That is a different question with a different answer, and
:mod:`c3_coverage` is where it is asked. Reconciling perfectly and covering
adequately are not the same property, and a module that reported one number
would invite them to be confused.

Two accounting systems, deliberately not merged
-----------------------------------------------
*Source side* answers "what happened to the CE source amounts?" Every row of
the ledger that carries a published CE source amount sits in exactly one
disposition bucket, and the buckets sum to the published basis. This closes by
construction rather than by luck -- C2 moves amounts between buckets and never
rescales them -- so the test worth running is not whether it closes but
whether the construction is intact, which is asserted cell by cell.

*Track-A side* answers "what is currently effective?" That is a strictly
smaller question: PENDING, OPEN and WITHHELD amounts exist, are known, and are
not in force. They are reported beside the effective total rather than folded
into it or dropped, because an amount that is blocked is not an amount that is
zero.

Only ``PUBLISHED_CE_BASIS`` rows enter the source identity. A replacement-side
amount estimated from microdata never was a published CE source amount, and
inserting it would make the source side count a dollar that BLS never
published. It enters the Track-A side, where it belongs, and the gap between
the two sides is reported as ``delta_scope`` rather than closed.

Arithmetic
----------
Amounts are fixed-point decimal strings in the ledger and are read with
:class:`decimal.Decimal`. Sums are therefore exact and residuals are exactly
zero when they close, so no tolerance is needed anywhere in C3-A and none is
offered. A residual is a defect to diagnose, never a bucket to add.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

LEDGER_PATH = (
    REPO_ROOT
    / "data/research/detailed_inflation/canonical_substrate_2024"
    / "ucc_population_accounting_ledger.csv"
)
SCOPE_RULES_PATH = REPO_ROOT / "registry/research/ce_cpi_scope_rules_v0_3.json"

#: Canonical population order. Every artifact sorts on this, never on the
#: order a source file happened to use.
POPULATIONS: tuple[str, ...] = ("ALL_CU", "Q1", "Q2", "Q3", "Q4", "Q5")

#: The only source class whose amounts are published CE source dollars. The
#: other three are addenda held outside the basis, microdata estimates with no
#: published aggregate, and transformation destinations with no amount of
#: their own.
PUBLISHED_BASIS = "PUBLISHED_CE_BASIS"

#: Disposition -> the amount column it populates. Mirrors the frozen schema;
#: a test asserts the two agree, so a schema change cannot silently diverge.
AMOUNT_COLUMN_BY_DISPOSITION: Mapping[str, str | None] = {
    "RETAINED": "retained_amount",
    "EXCLUDED": "excluded_amount",
    "REMOVED_FOR_REPLACEMENT": "removed_for_replacement_amount",
    "REPLACEMENT": "replacement_amount",
    "TRANSFORMED": "transformed_amount",
    "PENDING": "pending_amount",
    "OPEN": "open_amount",
    "WITHHELD": "withheld_amount",
    "NOT_APPLICABLE": None,
}

#: Dispositions whose amounts are in force in the Track-A substrate. The
#: membership test is ``normalization_state == ELIGIBLE`` as well: a RETAINED
#: row whose amount BLS suppressed is retained and contributes nothing.
EFFECTIVE_DISPOSITIONS: tuple[str, ...] = ("RETAINED", "REPLACEMENT", "TRANSFORMED")

ELIGIBLE = "ELIGIBLE"

#: Source-side buckets, in report order.
SOURCE_BUCKETS: tuple[str, ...] = (
    "retained",
    "excluded_effective",
    "removed_for_replacement",
    "transformed",
    "pending",
    "open",
    "withheld",
)

#: Disposition -> source-side bucket name.
SOURCE_BUCKET_BY_DISPOSITION: Mapping[str, str] = {
    "RETAINED": "retained",
    "EXCLUDED": "excluded_effective",
    "REMOVED_FOR_REPLACEMENT": "removed_for_replacement",
    "TRANSFORMED": "transformed",
    "PENDING": "pending",
    "OPEN": "open",
    "WITHHELD": "withheld",
}


class C3ReconciliationError(RuntimeError):
    """A reconciliation invariant does not hold.

    Raised rather than warned, and never repaired by adding a bucket. Every
    condition that raises here means an amount is unaccounted for, and an
    unaccounted amount that is quietly absorbed is worse than one that stops
    the build.
    """


@dataclass(frozen=True)
class LedgerRow:
    """One (ucc, population) row, with its amounts already parsed."""

    ucc: str
    population: str
    dmi_node: str
    source_class: str
    disposition: str
    normalization_state: str
    governing_rule_id: str
    canonical_rule_state: str
    replacement_group_id: str
    replacement_role: str
    source_amount: Decimal | None
    source_amount_status: str
    bucket_amount: Decimal | None
    bucket_column: str | None

    @property
    def is_published_basis(self) -> bool:
        return self.source_class == PUBLISHED_BASIS

    @property
    def is_effective(self) -> bool:
        """In force in the Track-A substrate, with an amount to contribute."""
        return (
            self.disposition in EFFECTIVE_DISPOSITIONS
            and self.normalization_state == ELIGIBLE
            and self.bucket_amount is not None
        )


def _decimal(raw: str) -> Decimal | None:
    return None if raw.strip() == "" else Decimal(raw.strip())


def load_ledger(path: Path = LEDGER_PATH) -> list[LedgerRow]:
    """Parse the frozen ledger, validating the one-amount-column invariant.

    The invariant is checked on read rather than trusted. C3 is downstream of
    a frozen artifact, and a downstream module that assumes its input holds
    cannot tell a good input from a corrupted one.
    """
    text = path.read_text(encoding="utf-8")
    rows: list[LedgerRow] = []
    amount_columns = [c for c in AMOUNT_COLUMN_BY_DISPOSITION.values() if c]
    for record in csv.DictReader(text.splitlines()):
        populated = [c for c in amount_columns if record[c].strip() != ""]
        if len(populated) > 1:
            raise C3ReconciliationError(
                f"{record['ucc']}/{record['population']}: {len(populated)} amount "
                f"columns are populated: {populated}"
            )
        disposition = record["track_a_disposition"]
        expected = AMOUNT_COLUMN_BY_DISPOSITION.get(disposition, "__unknown__")
        if expected == "__unknown__":
            raise C3ReconciliationError(
                f"{record['ucc']}/{record['population']}: unknown disposition "
                f"{disposition!r}"
            )
        if populated and populated[0] != expected:
            raise C3ReconciliationError(
                f"{record['ucc']}/{record['population']}: disposition {disposition} "
                f"populates {populated[0]}, not {expected}"
            )
        source = _decimal(record["source_amount_millions"])
        bucket = _decimal(record[populated[0]]) if populated else None
        if bucket is not None and bucket != source:
            raise C3ReconciliationError(
                f"{record['ucc']}/{record['population']}: bucket amount {bucket} "
                f"is not the source amount {source}. C2 never rescales."
            )
        rows.append(
            LedgerRow(
                ucc=record["ucc"],
                population=record["population"],
                dmi_node=record["dmi_node"],
                source_class=record["source_class"],
                disposition=disposition,
                normalization_state=record["normalization_state"],
                governing_rule_id=record["governing_rule_id"],
                canonical_rule_state=record["canonical_rule_state"],
                replacement_group_id=record["replacement_group_id"],
                replacement_role=record["replacement_role"],
                source_amount=source,
                source_amount_status=record["source_amount_status"],
                bucket_amount=bucket,
                bucket_column=populated[0] if populated else None,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# A2 -- the two accounting systems
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PopulationAccounting:
    """Both accounting systems for one population, plus their residuals.

    Amounts not in force are decomposed by where they came from, because the
    two halves are different kinds of number and summing them without saying
    so invites them to be read as one. ``pending_source_amount`` is published
    CE expenditure under a proposed rule. ``pending_replacement_amount`` is a
    microdata estimate for a replacement concept that is not in force. They
    add to ``pending``, and that identity is asserted rather than assumed.

    ``withheld_replacement_amount`` is separated for the same reason: the only
    withheld amount in the 2024 substrate is a replacement-side estimate that
    failed a quality gate, and it is not part of pending at all.
    """

    population: str
    source_total: Decimal
    source_buckets: Mapping[str, Decimal]
    source_residual: Decimal
    effective_retained: Decimal
    effective_replacement: Decimal
    effective_transformed: Decimal
    effective_total: Decimal
    effective_residual: Decimal
    excluded_effective: Decimal
    pending: Decimal
    pending_source_amount: Decimal
    pending_replacement_amount: Decimal
    open_: Decimal
    withheld: Decimal
    withheld_replacement_amount: Decimal
    delta_scope: Decimal
    cells_without_amount: int
    cells_with_amount: int

    @property
    def closes(self) -> bool:
        return self.source_residual == 0 and self.effective_residual == 0


def _zero_buckets() -> dict[str, Decimal]:
    return {name: Decimal(0) for name in SOURCE_BUCKETS}


def population_accounting(rows: Iterable[LedgerRow]) -> list[PopulationAccounting]:
    """Source-side and Track-A accounting for every population.

    The source side is restricted to ``PUBLISHED_CE_BASIS``. The Track-A side
    is not: an introduced replacement estimated from microdata is genuinely in
    force even though it never was a published CE dollar. That asymmetry is
    the reason ``delta_scope`` is non-zero, and reporting it is the point.
    """
    rows = list(rows)
    out: list[PopulationAccounting] = []
    for population in POPULATIONS:
        scoped = [r for r in rows if r.population == population]

        buckets = _zero_buckets()
        source_total = Decimal(0)
        for row in scoped:
            if not row.is_published_basis or row.source_amount is None:
                continue
            bucket = SOURCE_BUCKET_BY_DISPOSITION.get(row.disposition)
            if bucket is None:
                raise C3ReconciliationError(
                    f"{row.ucc}/{population}: published-basis row has disposition "
                    f"{row.disposition}, which maps to no source bucket"
                )
            buckets[bucket] += row.source_amount
            source_total += row.source_amount

        by_disposition: dict[str, Decimal] = {}
        for row in scoped:
            if row.is_effective:
                by_disposition[row.disposition] = (
                    by_disposition.get(row.disposition, Decimal(0)) + row.bucket_amount
                )
        retained = by_disposition.get("RETAINED", Decimal(0))
        replacement = by_disposition.get("REPLACEMENT", Decimal(0))
        transformed = by_disposition.get("TRANSFORMED", Decimal(0))
        effective_total = retained + replacement + transformed

        def blocked(disposition: str, predicate=None) -> Decimal:
            return sum(
                (
                    r.bucket_amount
                    for r in scoped
                    if r.disposition == disposition
                    and r.bucket_amount is not None
                    and (predicate is None or predicate(r))
                ),
                Decimal(0),
            )

        pending_source = blocked("PENDING", lambda r: r.is_published_basis)
        pending_replacement = blocked(
            "PENDING", lambda r: r.replacement_role == "REPLACEMENT"
        )
        pending_total = blocked("PENDING")
        if pending_source + pending_replacement != pending_total:
            raise C3ReconciliationError(
                f"{population}: pending decomposes to {pending_source} + "
                f"{pending_replacement} = {pending_source + pending_replacement}, "
                f"which is not the pending total {pending_total}. A pending "
                "amount is neither published basis nor a replacement side."
            )

        out.append(
            PopulationAccounting(
                population=population,
                source_total=source_total,
                source_buckets=buckets,
                source_residual=source_total - sum(buckets.values(), Decimal(0)),
                effective_retained=retained,
                effective_replacement=replacement,
                effective_transformed=transformed,
                effective_total=effective_total,
                effective_residual=(
                    effective_total - (retained + replacement + transformed)
                ),
                excluded_effective=blocked("EXCLUDED"),
                pending=pending_total,
                pending_source_amount=pending_source,
                pending_replacement_amount=pending_replacement,
                open_=blocked("OPEN"),
                withheld=blocked("WITHHELD"),
                withheld_replacement_amount=blocked(
                    "WITHHELD", lambda r: r.replacement_role == "REPLACEMENT"
                ),
                delta_scope=effective_total - source_total,
                cells_without_amount=sum(
                    1
                    for r in scoped
                    if r.is_published_basis and r.source_amount is None
                ),
                cells_with_amount=sum(
                    1
                    for r in scoped
                    if r.is_published_basis and r.source_amount is not None
                ),
            )
        )
    return out


# ---------------------------------------------------------------------------
# A5 -- node x population
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NodeAccounting:
    node: str
    population: str
    source_expenditure: Decimal | None
    effective_retained: Decimal | None
    effective_transformed: Decimal | None
    effective_replacement: Decimal | None
    excluded_effective: Decimal | None
    pending: Decimal | None
    open_: Decimal | None
    withheld: Decimal | None
    effective_track_a_basis: Decimal | None
    ucc_count: int
    cells_without_amount: int


UNMAPPED_NODE = "__UNMAPPED__"


def _or_none(total: Decimal, seen: bool) -> Decimal | None:
    """``None`` when no cell contributed, so blank never reads as zero."""
    return total if seen else None


def node_accounting(rows: Iterable[LedgerRow]) -> list[NodeAccounting]:
    """Per-node, per-population accounting over every node the ledger uses.

    Rows whose ``dmi_node`` is blank are reported under ``__UNMAPPED__``
    rather than dropped. They carry real dollars, and a node table that summed
    to less than the population table because some rows had no node would be
    a reconciliation that hides its own gap.
    """
    rows = list(rows)
    nodes = sorted({r.dmi_node or UNMAPPED_NODE for r in rows})
    out: list[NodeAccounting] = []
    for node in nodes:
        for population in POPULATIONS:
            scoped = [
                r
                for r in rows
                if (r.dmi_node or UNMAPPED_NODE) == node and r.population == population
            ]
            if not scoped:
                continue

            def total(predicate) -> tuple[Decimal, bool]:
                seen = False
                acc = Decimal(0)
                for row in scoped:
                    if predicate(row) and row.bucket_amount is not None:
                        acc += row.bucket_amount
                        seen = True
                return acc, seen

            src = Decimal(0)
            src_seen = False
            for row in scoped:
                if row.is_published_basis and row.source_amount is not None:
                    src += row.source_amount
                    src_seen = True

            retained, r_seen = total(
                lambda r: r.disposition == "RETAINED" and r.is_effective
            )
            transformed, t_seen = total(
                lambda r: r.disposition == "TRANSFORMED" and r.is_effective
            )
            replacement, p_seen = total(
                lambda r: r.disposition == "REPLACEMENT" and r.is_effective
            )
            excluded, e_seen = total(lambda r: r.disposition == "EXCLUDED")
            pending, pend_seen = total(lambda r: r.disposition == "PENDING")
            open_, o_seen = total(lambda r: r.disposition == "OPEN")
            withheld, w_seen = total(lambda r: r.disposition == "WITHHELD")

            effective = retained + transformed + replacement
            out.append(
                NodeAccounting(
                    node=node,
                    population=population,
                    source_expenditure=_or_none(src, src_seen),
                    effective_retained=_or_none(retained, r_seen),
                    effective_transformed=_or_none(transformed, t_seen),
                    effective_replacement=_or_none(replacement, p_seen),
                    excluded_effective=_or_none(excluded, e_seen),
                    pending=_or_none(pending, pend_seen),
                    open_=_or_none(open_, o_seen),
                    withheld=_or_none(withheld, w_seen),
                    effective_track_a_basis=_or_none(
                        effective, r_seen or t_seen or p_seen
                    ),
                    ucc_count=len({r.ucc for r in scoped}),
                    cells_without_amount=sum(
                        1
                        for r in scoped
                        if r.is_published_basis and r.source_amount is None
                    ),
                )
            )
    return out


# ---------------------------------------------------------------------------
# A3 -- replacement groups
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplacementGroupRow:
    replacement_group_id: str
    population: str
    source_side_amount: Decimal | None
    replacement_side_amount: Decimal | None
    source_side_state: str
    replacement_side_state: str
    removed_for_replacement_effective: Decimal | None
    replacement_effective: Decimal | None
    delta_replacement: Decimal | None
    delta_is_applicable: bool
    note: str


def replacement_groups(rows: Iterable[LedgerRow]) -> list[ReplacementGroupRow]:
    """Both sides of every replacement group, without forcing them to agree.

    ``Delta_replacement`` is only defined where both sides have an effective
    amount. The primary-residence group declares no removal side at all: the
    registry states that the rule removes nothing and that the outlays it
    displaces leave under their own out-of-scope rules, with no arithmetic
    depending on their amounts. Subtracting those outlays here would invent
    the very linkage the registry declines to make, so the delta is reported
    as not applicable and the reason is carried in the row.
    """
    rows = list(rows)
    groups = sorted(
        {r.replacement_group_id for r in rows if r.replacement_group_id.strip()}
    )
    out: list[ReplacementGroupRow] = []
    for group in groups:
        for population in POPULATIONS:
            scoped = [
                r
                for r in rows
                if r.replacement_group_id == group and r.population == population
            ]
            if not scoped:
                continue
            removal = [r for r in scoped if r.replacement_role == "REMOVAL"]
            replacement = [r for r in scoped if r.replacement_role == "REPLACEMENT"]

            def summed(side: Sequence[LedgerRow], effective_only: bool):
                seen = False
                acc = Decimal(0)
                for row in side:
                    if row.bucket_amount is None:
                        continue
                    if effective_only and not row.is_effective:
                        continue
                    acc += row.bucket_amount
                    seen = True
                return acc if seen else None

            removed_effective = summed(removal, True)
            replacement_effective = summed(replacement, True)
            if removal and removed_effective is not None and replacement_effective is not None:
                delta = replacement_effective - removed_effective
                applicable = True
                note = "both sides effective"
            elif not removal:
                delta = None
                applicable = False
                note = (
                    "no removal side is declared for this group, so no delta is "
                    "defined; the displaced outlays leave under their own rules"
                )
            else:
                delta = None
                applicable = False
                note = "at least one side is not in force, so no delta is defined"

            out.append(
                ReplacementGroupRow(
                    replacement_group_id=group,
                    population=population,
                    source_side_amount=summed(removal, False),
                    replacement_side_amount=summed(replacement, False),
                    source_side_state=(
                        "/".join(sorted({r.canonical_rule_state for r in removal}))
                        or "NO_REMOVAL_SIDE_DECLARED"
                    ),
                    replacement_side_state="/".join(
                        sorted({r.canonical_rule_state for r in replacement})
                    ),
                    removed_for_replacement_effective=removed_effective,
                    replacement_effective=replacement_effective,
                    delta_replacement=delta,
                    delta_is_applicable=applicable,
                    note=note,
                )
            )
    return out


# ---------------------------------------------------------------------------
# A4 -- the shelter deltas, re-derived rather than copied
# ---------------------------------------------------------------------------

SHELTER_TRACK_PATH = (
    REPO_ROOT
    / "data/research/detailed_inflation/shelter_2024/shelter_cpi_track_2024.csv"
)

OWNER_OUTLAY = "OWNER_OUTLAY"
REMOVED_OUT_OF_SCOPE = "REMOVED_OUT_OF_SCOPE"


def owner_outlay_uccs(path: Path = SHELTER_TRACK_PATH) -> dict[str, set[str]]:
    """Owner-outlay UCCs at the shelter checkpoint, split by what they were.

    Both sets are read out of the frozen shelter track artifact rather than
    written down here. ``removed`` is the membership the frozen
    ``owner_outlays_removed`` was computed over -- the owner outlays rental
    equivalence stands in for, which at that checkpoint meant mortgage
    interest and charges and residential property tax. ``pending`` is what was
    proposed and not in force.

    Reading membership from the artifact matters because the two readings of
    ``delta_shelter`` below differ by which of these sets is used, and a
    hand-written UCC list would let that difference be edited rather than
    observed.
    """
    removed: set[str] = set()
    pending: set[str] = set()
    for row in csv.DictReader(path.read_text(encoding="utf-8").splitlines()):
        if row["component"] != OWNER_OUTLAY:
            continue
        if row["disposition"] == REMOVED_OUT_OF_SCOPE:
            removed.add(row["ucc"])
        elif row["disposition"].startswith("PENDING"):
            pending.add(row["ucc"])
    if not removed:
        raise C3ReconciliationError(
            f"{path} declares no removed owner outlays; the shelter checkpoint "
            "cannot have been read correctly"
        )
    return {"removed": removed, "pending": pending}


@dataclass(frozen=True)
class ShelterDelta:
    """``delta_scope`` and ``delta_shelter``, under both readings.

    ``delta_shelter_frozen_membership`` uses the owner outlays the shelter
    checkpoint had already removed. ``delta_shelter_current_state`` uses every
    owner outlay that has since left the basis under an accepted rule. The two
    differ because owner maintenance services moved from PROPOSED to ACCEPTED
    after the shelter checkpoint was frozen.

    Both are reported. Neither is adjusted to reproduce the other.
    """

    population: str
    e_source: Decimal
    e_cpi: Decimal
    delta_scope: Decimal
    rental_equivalence_introduced: Decimal
    owner_outlays_removed_frozen_membership: Decimal
    delta_shelter_frozen_membership: Decimal
    owner_outlays_removed_current_state: Decimal
    delta_shelter_current_state: Decimal
    definition_difference: Decimal


def shelter_deltas(
    rows: Iterable[LedgerRow], owner_outlays: Mapping[str, set[str]]
) -> list[ShelterDelta]:
    """Reproduce both deltas from the ledger, under both removal definitions.

    Nothing here is copied from the shelter checkpoint. ``e_source``,
    ``e_cpi`` and the introduced amount all come from the canonical ledger's
    own rows, so agreement with the frozen figures is a reproduction and not a
    restatement.
    """
    rows = list(rows)
    accounting = {a.population: a for a in population_accounting(rows)}
    frozen_members = owner_outlays["removed"]
    current_members = frozen_members | owner_outlays["pending"]

    out: list[ShelterDelta] = []
    for population in POPULATIONS:
        scoped = [r for r in rows if r.population == population]
        acc = accounting[population]
        introduced = acc.effective_replacement

        def removed(members: set[str]) -> Decimal:
            return sum(
                (
                    r.bucket_amount
                    for r in scoped
                    if r.ucc in members
                    and r.disposition == "EXCLUDED"
                    and r.bucket_amount is not None
                ),
                Decimal(0),
            )

        frozen_removed = removed(frozen_members)
        current_removed = removed(current_members)
        out.append(
            ShelterDelta(
                population=population,
                e_source=acc.source_total,
                e_cpi=acc.effective_total,
                delta_scope=acc.effective_total - acc.source_total,
                rental_equivalence_introduced=introduced,
                owner_outlays_removed_frozen_membership=frozen_removed,
                delta_shelter_frozen_membership=introduced - frozen_removed,
                owner_outlays_removed_current_state=current_removed,
                delta_shelter_current_state=introduced - current_removed,
                definition_difference=current_removed - frozen_removed,
            )
        )
    return out


# ---------------------------------------------------------------------------
# The invariants, as a function so they can be pointed at broken input
# ---------------------------------------------------------------------------

#: Columns a research ledger may not acquire in C3. Normalisation is a later
#: milestone, and a weight column appearing here would mean it had started.
FORBIDDEN_LEDGER_COLUMNS: tuple[str, ...] = (
    "normalized_weight",
    "weight",
    "share",
    "residual",
    "balancing_amount",
    "plug",
)


def audit_reconciliation(
    rows: Sequence[LedgerRow], ledger_columns: Sequence[str] = ()
) -> list[str]:
    """Every way the C3-A accounting can fail, as sorted reason codes.

    Returned rather than raised so a mutation test can assert *which*
    invariant fired. A guard that reports only "something is wrong" cannot
    distinguish a double count from a pending amount leaking into the basis,
    and those two defects want different repairs.
    """
    problems: list[str] = []

    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.ucc, row.population)
        if key in seen:
            problems.append("DUPLICATE_ROW_KEY")
        seen.add(key)

    for column in ledger_columns:
        if column in FORBIDDEN_LEDGER_COLUMNS:
            problems.append("FORBIDDEN_COLUMN")

    # A dollar can only leave the accounting by the bucket and the source
    # amount disagreeing, or by a row carrying an amount with no treatment at
    # all. The bucket totals cannot drift from the source total on their own:
    # both are read from the same cell, which is what makes the source
    # identity closed by construction rather than by arithmetic luck. So these
    # two checks, not the residual, are what actually detect a lost dollar.
    for row in rows:
        if (
            row.bucket_amount is not None
            and row.source_amount is not None
            and row.bucket_amount != row.source_amount
        ):
            problems.append("BUCKET_IS_NOT_THE_SOURCE_AMOUNT")
        if (
            row.is_published_basis
            and row.source_amount is not None
            and row.bucket_column is None
        ):
            problems.append("SOURCE_AMOUNT_WITHOUT_TREATMENT")

    try:
        accounting = population_accounting(rows)
    except C3ReconciliationError:
        # The aggregation refuses to build at all, which is itself the finding.
        # Reported as a code so a mutation test can name it, rather than
        # escaping as an exception a caller might catch and ignore.
        return sorted(set(problems + ["ACCOUNTING_REFUSED_TO_BUILD"]))

    for entry in accounting:
        if entry.source_residual != 0:
            problems.append("SOURCE_DOES_NOT_CLOSE")
        if entry.effective_residual != 0:
            problems.append("EFFECTIVE_DOES_NOT_CLOSE")

    # An amount that is not in force may not appear in the effective basis.
    for row in rows:
        if row.disposition in ("PENDING", "OPEN") and row.is_effective:
            problems.append(f"{row.disposition}_IN_EFFECTIVE")
        if row.disposition == "EXCLUDED" and row.is_effective:
            problems.append("EXCLUDED_IN_EFFECTIVE")
        if (
            row.disposition == "WITHHELD"
            and row.source_amount_status == "WITHHELD"
            and row.bucket_amount == 0
        ):
            problems.append("WITHHELD_ZERO_FILLED")
        if row.source_amount_status in ("SUPPRESSED", "NOT_AVAILABLE", "NOT_APPLICABLE"):
            if row.bucket_amount is not None:
                problems.append("BLANK_FILLED_WITH_A_NUMBER")

    # Node totals must reconstruct population totals exactly.
    for entry in accounting:
        node_source = sum(
            (
                r.source_amount
                for r in rows
                if r.population == entry.population
                and r.is_published_basis
                and r.source_amount is not None
            ),
            Decimal(0),
        )
        if node_source != entry.source_total:
            problems.append("NODE_TOTALS_DISAGREE")

    nodes = node_accounting(rows)
    for entry in accounting:
        summed = sum(
            (
                n.source_expenditure
                for n in nodes
                if n.population == entry.population and n.source_expenditure is not None
            ),
            Decimal(0),
        )
        if summed != entry.source_total:
            problems.append("NODE_TOTALS_DISAGREE")
        effective = sum(
            (
                n.effective_track_a_basis
                for n in nodes
                if n.population == entry.population
                and n.effective_track_a_basis is not None
            ),
            Decimal(0),
        )
        if effective != entry.effective_total:
            problems.append("NODE_EFFECTIVE_TOTALS_DISAGREE")

    return sorted(set(problems))
