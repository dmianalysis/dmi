"""Canonical current state and rule lineage for the 2024 substrate.

Detailed Inflation Substrate v0.1, task C1.

RESEARCH ONLY. Reads committed research registries and committed research
artifacts. Writes nothing outside ``registry/research`` and
``data/research/detailed_inflation``. Touches no production module, manifest
or output.

The problem this module exists to solve
---------------------------------------
The repository holds several versions of the same registry side by side, on
purpose: a superseded version is preserved byte-for-byte so that what was
believed at a milestone stays readable. That is good configuration control and
a bad default for a consumer. ``ce_cpi_scope_rules_v0_1.json``,
``ce_cpi_scope_rules_v0_2.json`` and ``ce_cpi_scope_rules_v0_3.json`` all
exist, all validate, and disagree about which rule claims UCC 230113. Nothing
in a filename says which one is in force, and sorting filenames is not an
argument -- ``ucc_provenance_classes_v0_1.json`` carries ``version`` 0.2.0 and
there is no ``v0_2`` file at all.

So the head of each family is *derived* here, from the ``predecessor`` block
each successor artifact carries, and the derivation fails loudly if the chain
is not a single line ending in exactly one head. A consumer asks this module
which version governs and never has to guess.

What this module does not do
----------------------------
It does not adjudicate anything. Every state it reports is read from a
registry or derived from a registry by a rule stated here in full. It computes
no weight, no share, no denominator and no index. It reopens no shelter
question. Where a governing registry contradicts itself, the contradiction is
recorded in the manifest and is not repaired: repairing it would be research,
and this task is not authorised to do research.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DIR = REPO_ROOT / "registry/research"

MANIFEST_PATH = REGISTRY_DIR / "canonical_substrate_manifest_2024_v0_1.json"

MANIFEST_ARTIFACT_ID = "CANONICAL_SUBSTRATE_MANIFEST_2024_V0_1"
MANIFEST_VERSION = "0.1"

#: The reference year of every amount and every registry read here.
REFERENCE_YEAR = 2024

#: Canonical population labels and their canonical order. Every downstream
#: artifact sorts on this order rather than on whatever order a source file
#: happened to use, so a rebuild cannot reorder rows.
POPULATIONS: tuple[str, ...] = ("ALL_CU", "Q1", "Q2", "Q3", "Q4", "Q5")

#: The population label used by the LABSTAT-derived accounting basis for the
#: all-consumer-units row. Recorded rather than inlined because the two
#: vocabularies genuinely differ and silently coercing one into the other is
#: how population rows get lost.
BASIS_ALL_CU_LABEL = "All Consumer Units"


class CanonicalStateError(RuntimeError):
    """A canonical-state invariant does not hold.

    Raised rather than warned. Every condition that raises here is one where
    continuing would produce an artifact that looks authoritative and is not.
    """


# ---------------------------------------------------------------------------
# C1.1 -- registry families and their heads
# ---------------------------------------------------------------------------


class ArtifactRole(str, Enum):
    """Whether an artifact version governs the current research state."""

    #: This version is the head of its lineage. Consumers read this one.
    CURRENT_GOVERNING_INPUT = "CURRENT_GOVERNING_INPUT"
    #: A real earlier state, preserved deliberately. It is evidence of what
    #: was believed at a milestone and is never an input to current work.
    HISTORICAL_CHECKPOINT = "HISTORICAL_CHECKPOINT"


@dataclass(frozen=True)
class RegistryVersion:
    """One committed version of one registry family."""

    family: str
    artifact_id: str
    version: str
    relative_path: str
    predecessor_artifact_id: str | None
    role: ArtifactRole

    @property
    def key(self) -> str:
        """Case-folded artifact id.

        The families are not internally consistent about case:
        ``ce_cpi_scope_rules_v0_1`` names itself in lower case and
        ``CE_CPI_SCOPE_RULES_V0_2`` names its predecessor in lower case while
        naming itself in upper. Matching on the fold is the only way to walk
        the chain without hard-coding the exceptions.
        """
        return self.artifact_id.casefold()


#: Registry families whose lineage this module resolves, and every committed
#: file belonging to each. Membership is declared rather than globbed: a glob
#: would silently absorb a file dropped into the directory by a future task,
#: and the whole point of this module is that new versions are noticed.
REGISTRY_FAMILIES: Mapping[str, tuple[str, ...]] = {
    "ce_cpi_scope_rules": (
        "ce_cpi_scope_rules_v0_1.json",
        "ce_cpi_scope_rules_v0_2.json",
        "ce_cpi_scope_rules_v0_3.json",
    ),
    "ucc_provenance_classes": (
        "ucc_provenance_classes_v0_1.json",
        "ucc_provenance_classes_v0_3.json",
        "ucc_provenance_classes_v0_4.json",
    ),
}

#: Single-version registries. They have no lineage to resolve, so they are
#: listed separately rather than being given a degenerate one-element chain.
SINGLE_VERSION_REGISTRIES: tuple[str, ...] = (
    "shelter_residual_evidence_v0_1.json",
    "detailed_inflation_taxonomy_v0_1.json",
    "eli_to_node_map_v0_1.json",
    "pumd_2024_interview_source_v0_1.json",
    "pumd_lb01_benchmark_spec_v0_1.json",
    "pumd_lb01_confirmation_spec_v0_1.json",
    "shelter_estimation_spec_v0_1.json",
)

#: Pinned BLS source extracts, with the provenance sidecar that carries the
#: sha256 of the file BLS published.
PINNED_SOURCE_PROVENANCE: tuple[str, ...] = (
    "ucc_eli_concordance_2024_v0_1.provenance.json",
    "cpi_eli_descriptions_v0_1.provenance.json",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_of(version: "RegistryVersion", registry_dir: Path) -> Path:
    """Resolve a version's file inside ``registry_dir``.

    ``relative_path`` is the repository-relative path recorded in artifacts,
    and is deliberately not used to open the file. Resolving it against
    ``REPO_ROOT`` would make every ``registry_dir`` argument a lie: a caller
    that passed a directory of mutated registries would silently be served the
    real ones, and every mutation test would pass by reading the wrong file.
    """
    return registry_dir / Path(version.relative_path).name


def resolve_family(family: str, registry_dir: Path = REGISTRY_DIR) -> tuple[RegistryVersion, ...]:
    """Return every version of ``family`` in lineage order, oldest first.

    The order is derived from the ``predecessor`` block, not from the file
    names. Exactly one version must have no predecessor and exactly one must
    have no successor, or the chain is not a chain and this raises.
    """
    try:
        filenames = REGISTRY_FAMILIES[family]
    except KeyError:
        raise CanonicalStateError(f"unknown registry family {family!r}") from None

    loaded: dict[str, tuple[str, dict]] = {}
    for filename in filenames:
        payload = _load(registry_dir / filename)
        artifact_id = payload.get("artifact_id")
        if not artifact_id:
            raise CanonicalStateError(f"{filename}: no artifact_id")
        key = artifact_id.casefold()
        if key in loaded:
            raise CanonicalStateError(
                f"{family}: artifact_id {artifact_id!r} appears in two files, "
                f"{loaded[key][0]} and {filename}"
            )
        loaded[key] = (filename, payload)

    predecessor_of: dict[str, str | None] = {}
    for key, (filename, payload) in loaded.items():
        block = payload.get("predecessor")
        if block is None:
            predecessor_of[key] = None
            continue
        pred_id = block.get("artifact_id")
        if not pred_id:
            raise CanonicalStateError(
                f"{filename}: predecessor block carries no artifact_id"
            )
        pred_key = pred_id.casefold()
        if pred_key not in loaded:
            raise CanonicalStateError(
                f"{filename}: names predecessor {pred_id!r}, which is not a "
                f"declared member of family {family!r}"
            )
        declared_path = block.get("path")
        actual_path = f"registry/research/{loaded[pred_key][0]}"
        if declared_path is not None and declared_path != actual_path:
            raise CanonicalStateError(
                f"{filename}: predecessor path {declared_path!r} does not "
                f"resolve to {actual_path!r}"
            )
        predecessor_of[key] = pred_key

    roots = [k for k, p in predecessor_of.items() if p is None]
    if len(roots) != 1:
        raise CanonicalStateError(
            f"{family}: expected exactly one version with no predecessor, "
            f"found {sorted(loaded[k][1]['artifact_id'] for k in roots)}"
        )
    successors: dict[str, list[str]] = {k: [] for k in loaded}
    for key, pred in predecessor_of.items():
        if pred is not None:
            successors[pred].append(key)
    forks = {k: v for k, v in successors.items() if len(v) > 1}
    if forks:
        raise CanonicalStateError(
            f"{family}: lineage forks at "
            f"{sorted(loaded[k][1]['artifact_id'] for k in forks)}; a family "
            f"with two heads has no single governing version"
        )

    ordered: list[str] = []
    cursor: str | None = roots[0]
    while cursor is not None:
        ordered.append(cursor)
        nxt = successors[cursor]
        cursor = nxt[0] if nxt else None
    if len(ordered) != len(loaded):
        orphans = sorted(loaded[k][1]["artifact_id"] for k in set(loaded) - set(ordered))
        raise CanonicalStateError(
            f"{family}: {orphans} are not reachable from the root of the "
            f"lineage; the chain is broken"
        )

    versions: list[RegistryVersion] = []
    for position, key in enumerate(ordered):
        filename, payload = loaded[key]
        is_head = position == len(ordered) - 1
        pred = predecessor_of[key]
        versions.append(
            RegistryVersion(
                family=family,
                artifact_id=payload["artifact_id"],
                version=str(payload.get("version", "")),
                relative_path=f"registry/research/{filename}",
                predecessor_artifact_id=(
                    loaded[pred][1]["artifact_id"] if pred is not None else None
                ),
                role=(
                    ArtifactRole.CURRENT_GOVERNING_INPUT
                    if is_head
                    else ArtifactRole.HISTORICAL_CHECKPOINT
                ),
            )
        )
    return tuple(versions)


def governing_version(family: str, registry_dir: Path = REGISTRY_DIR) -> RegistryVersion:
    """Return the head of ``family``."""
    chain = resolve_family(family, registry_dir=registry_dir)
    return chain[-1]


# ---------------------------------------------------------------------------
# C1.2 -- frozen checkpoints
# ---------------------------------------------------------------------------


class CheckpointRole(str, Enum):
    """What a frozen tag is for."""

    #: The tag records a milestone. Its artifacts are evidence of what was
    #: believed then. It is not an input to current work.
    HISTORICAL_CHECKPOINT = "HISTORICAL_CHECKPOINT"
    #: The tag is the commit the current research state is built from.
    CURRENT_GOVERNING_INPUT = "CURRENT_GOVERNING_INPUT"


@dataclass(frozen=True)
class Checkpoint:
    """One frozen research checkpoint."""

    tag: str
    commit: str
    milestone: str
    role: CheckpointRole


#: The four frozen tags of the Detailed Inflation Substrate v0.1 programme, in
#: chronological order, with the commit each dereferences to.
#:
#: These are recorded as constants rather than read from ``git`` at build
#: time for two reasons. The manifest must rebuild byte-identically, and a
#: subprocess call to ``git`` makes the artifact depend on the checkout rather
#: than on the repository. And a tag that has moved is exactly the condition
#: worth failing on, which a test can only detect if the expected value is
#: written down. ``test_checkpoint_commits_match_the_repository`` compares
#: these against the real tags.
CHECKPOINTS: tuple[Checkpoint, ...] = (
    Checkpoint(
        tag="dmi-detailed-inflation-v0.1-m2-corrected",
        commit="e6402097eacd45c536a30a0ae9c9476fc2bfc76d",
        milestone="Milestone 2, CE->CPI scope resolution, corrected",
        role=CheckpointRole.HISTORICAL_CHECKPOINT,
    ),
    Checkpoint(
        tag="dmi-detailed-inflation-v0.1-pumd-benchmark-2024",
        commit="95111fd675f2d0287e5cc89398411e3322ad65a3",
        milestone="PUMD LB01 benchmark; the frozen estimator commit",
        role=CheckpointRole.HISTORICAL_CHECKPOINT,
    ),
    Checkpoint(
        tag="dmi-detailed-inflation-v0.1-shelter-partial-2024",
        commit="5d1e513ec8fedeebd5d57e5f8770076fa03efe0b",
        milestone="Shelter task, PARTIAL verdict",
        role=CheckpointRole.HISTORICAL_CHECKPOINT,
    ),
    Checkpoint(
        tag="dmi-detailed-inflation-v0.1-shelter-residuals-2024",
        commit="3ee9141e7c186e5cd344de8f87b8a1c3f8cf5326",
        milestone="Residual shelter allocation, PARTIAL verdict",
        role=CheckpointRole.CURRENT_GOVERNING_INPUT,
    ),
)


# ---------------------------------------------------------------------------
# C1.3 -- rule lineage
# ---------------------------------------------------------------------------


class CanonicalRuleState(str, Enum):
    """Where a rule stands in the current research state.

    The three ``CURRENT_`` states are mutually exclusive readings of a rule
    that is present in the governing registry. ``SUPERSEDED`` and
    ``HISTORICAL_ONLY`` are both absences from the governing registry, kept
    apart because they mean opposite things: a superseded rule was replaced
    and its subject matter is still governed, a historical-only rule was
    dropped and its subject matter is not.
    """

    #: In the governing registry, ACCEPTED and applicable. Its disposition is
    #: in force and may populate an effective amount.
    CURRENT_EFFECTIVE = "CURRENT_EFFECTIVE"
    #: In the governing registry with a proposed disposition that is not in
    #: force. It may never populate an effective amount.
    CURRENT_PENDING = "CURRENT_PENDING"
    #: In the governing registry, proposing nothing. The methodology is
    #: undecided, which is not the same as blocked.
    CURRENT_OPEN = "CURRENT_OPEN"
    #: Absent from the governing registry, and one or more successors name it
    #: as their predecessor. Its UCCs are claimed by those successors.
    SUPERSEDED = "SUPERSEDED"
    #: Absent from the governing registry with no successor naming it. It
    #: existed and was dropped.
    HISTORICAL_ONLY = "HISTORICAL_ONLY"
    #: No rule applies. Used for UCCs that no rule claims.
    NOT_APPLICABLE = "NOT_APPLICABLE"


#: The states a UCC may legitimately resolve to. A UCC that resolves to a
#: SUPERSEDED or HISTORICAL_ONLY rule is a defect, not a state: it means a
#: consumer is reading a version that a successor has replaced.
RESOLVABLE_STATES: frozenset[CanonicalRuleState] = frozenset(
    {
        CanonicalRuleState.CURRENT_EFFECTIVE,
        CanonicalRuleState.CURRENT_PENDING,
        CanonicalRuleState.CURRENT_OPEN,
        CanonicalRuleState.NOT_APPLICABLE,
    }
)

#: The one ``final_status`` value that means "no disposition is proposed".
NO_DISPOSITION = "UNRESOLVED"


@dataclass(frozen=True)
class RuleRecord:
    """The fields of a scope rule that the canonical layer reads.

    Deliberately a small subset. The governing registry's rules carry
    heterogeneous field sets -- 51 distinct keys across 16 rules, only 8 of
    which every rule has -- because rules written at different milestones
    answer different questions. Reading only the common core plus explicitly
    optional extras means a rule written by a future task is either readable
    here or rejected here, never half-read.
    """

    rule_id: str
    rule_type: str
    review_status: str
    final_status: str
    track: str
    source_uccs: tuple[str, ...]
    output_uccs: tuple[str, ...]
    withheld_uccs: tuple[str, ...]
    predecessor_rule_id: str | None
    blocker_kind: str | None
    declared_state: str | None
    declared_applicable: bool | None
    replacement_concept: str | None
    materiality_all_cu: float | None


_REQUIRED_RULE_KEYS = (
    "rule_id",
    "rule_type",
    "review_status",
    "final_status",
    "track",
    "source_uccs",
)


def _read_rule(raw: Mapping, *, registry_path: str) -> RuleRecord:
    rule_id = raw.get("rule_id", "<no rule_id>")
    for key in _REQUIRED_RULE_KEYS:
        if key not in raw:
            raise CanonicalStateError(
                f"{registry_path}: rule {rule_id} has no {key!r}"
            )
    declared_state = raw.get("resolution_state")
    effect_state = raw.get("effect_state")
    if declared_state is not None and effect_state is not None:
        raise CanonicalStateError(
            f"{registry_path}: rule {rule_id} declares both resolution_state "
            f"and effect_state; one rule cannot carry two names for the same "
            f"variable"
        )
    return RuleRecord(
        rule_id=raw["rule_id"],
        rule_type=raw["rule_type"],
        review_status=raw["review_status"],
        final_status=raw["final_status"],
        track=raw["track"],
        source_uccs=tuple(raw["source_uccs"]),
        output_uccs=tuple(raw.get("output_uccs") or ()),
        withheld_uccs=tuple(raw.get("withheld_uccs") or ()),
        predecessor_rule_id=raw.get("predecessor_rule_id"),
        blocker_kind=raw.get("blocker_kind"),
        declared_state=declared_state if declared_state is not None else effect_state,
        declared_applicable=raw.get("is_applicable"),
        replacement_concept=raw.get("replacement_concept"),
        materiality_all_cu=raw.get("materiality_all_cu"),
    )


def read_rules(path: Path) -> tuple[RuleRecord, ...]:
    """Read every rule from one scope-rule registry file."""
    payload = _load(path)
    rules = [
        _read_rule(raw, registry_path=f"registry/research/{path.name}")
        for raw in payload["rules"]
    ]
    return tuple(sorted(rules, key=lambda r: r.rule_id))


def canonical_state_of(rule: RuleRecord) -> CanonicalRuleState:
    """Classify a rule that is present in the governing registry.

    This is the only place in the canonical layer where ``review_status``
    becomes a statement about force. The order of the branches is the whole
    content of the function and is not arbitrary:

    1. A rule proposing nothing is OPEN whatever its review status, because
       there is no disposition for a review to put into force.
    2. Otherwise a rule is effective if and only if it is ACCEPTED *and*
       applicable. Both, not either.
    3. Everything else is PENDING: a disposition exists and is not in force.

    Steps 1 and 2 are the same logic as
    :func:`dmi_research.detailed_inflation.resolution.track_a_disposition`,
    which is the hardened Milestone-2 gate. That function cannot be reused
    directly because its ``final_status`` type is ``MappingStatus``, whose
    five members do not include ``INTRODUCED``, and the governing registry has
    two ``INTRODUCE`` rules. ``test_canonical_gate_agrees_with_milestone_2_gate``
    proves the two agree everywhere the older type can express the input, so
    the duplication is checked rather than trusted.
    """
    if rule.final_status == NO_DISPOSITION:
        return CanonicalRuleState.CURRENT_OPEN
    if rule.review_status == "ACCEPTED" and _is_applicable(rule):
        return CanonicalRuleState.CURRENT_EFFECTIVE
    return CanonicalRuleState.CURRENT_PENDING


def _is_applicable(rule: RuleRecord) -> bool:
    """Whether ``rule`` may be applied without a further gate.

    A rule that declares ``is_applicable`` is taken at its word, and the
    declaration is required to agree with the review status. Ten of the
    sixteen governing rules declare it and all ten agree; the check exists so
    that the first one that disagrees stops the build instead of quietly
    picking a winner.
    """
    accepted = rule.review_status == "ACCEPTED"
    if rule.declared_applicable is None:
        return accepted
    if bool(rule.declared_applicable) != accepted:
        raise CanonicalStateError(
            f"rule {rule.rule_id}: is_applicable is "
            f"{rule.declared_applicable!r} but review_status is "
            f"{rule.review_status!r}; a rule cannot be applicable and not "
            f"accepted, or accepted and not applicable"
        )
    return accepted


def effective_track_a_status(rule: RuleRecord) -> str:
    """The Track-A status actually in force for ``rule``.

    A rule that is not effective puts its expenditure nowhere, so its
    effective status is ``UNRESOLVED``. This is the single choke point that
    makes "a PROPOSED rule has no effect" true by construction rather than by
    convention.
    """
    if canonical_state_of(rule) is CanonicalRuleState.CURRENT_EFFECTIVE:
        return rule.final_status
    return NO_DISPOSITION


@dataclass(frozen=True)
class RuleLineage:
    """One rule's position in the lineage of the scope-rule family."""

    rule_id: str
    state: CanonicalRuleState
    predecessor_rule_id: str | None
    successor_rule_ids: tuple[str, ...]
    first_seen_artifact_id: str
    last_seen_artifact_id: str
    #: The UCCs this rule claims in the most recent version that contains it.
    claimed_uccs: tuple[str, ...]


def build_rule_lineage(registry_dir: Path = REGISTRY_DIR) -> tuple[RuleLineage, ...]:
    """Trace every scope rule across every version of the family.

    Successor edges come from the ``predecessor_rule_id`` a successor carries.
    They are cross-checked against the governing registry's
    ``residual_transitions`` block, which records the same edges independently.
    Self-edges in that block -- a rule whose evidence was revised without its
    identity changing -- are not lineage edges and are excluded.
    """
    chain = resolve_family("ce_cpi_scope_rules", registry_dir=registry_dir)
    head = chain[-1]

    per_version: list[tuple[RegistryVersion, dict[str, RuleRecord]]] = []
    for version in chain:
        rules = read_rules(_file_of(version, registry_dir))
        per_version.append((version, {r.rule_id: r for r in rules}))

    head_rules = per_version[-1][1]

    first_seen: dict[str, str] = {}
    last_seen: dict[str, str] = {}
    last_record: dict[str, RuleRecord] = {}
    for version, rules in per_version:
        for rule_id, record in rules.items():
            first_seen.setdefault(rule_id, version.artifact_id)
            last_seen[rule_id] = version.artifact_id
            last_record[rule_id] = record

    successors: dict[str, list[str]] = {}
    for rule_id, record in sorted(head_rules.items()):
        pred = record.predecessor_rule_id
        if pred is None or pred == rule_id:
            continue
        if pred in head_rules:
            raise CanonicalStateError(
                f"rule {rule_id} names predecessor {pred}, but {pred} is still "
                f"present in the governing registry {head.artifact_id}; a "
                f"predecessor that survives its own replacement leaves two "
                f"live claims on the same subject matter"
            )
        successors.setdefault(pred, []).append(rule_id)

    _cross_check_transitions(_file_of(head, registry_dir), successors)

    lineage: list[RuleLineage] = []
    for rule_id in sorted(last_record):
        if rule_id in head_rules:
            state = canonical_state_of(head_rules[rule_id])
        elif successors.get(rule_id):
            state = CanonicalRuleState.SUPERSEDED
        else:
            state = CanonicalRuleState.HISTORICAL_ONLY
        lineage.append(
            RuleLineage(
                rule_id=rule_id,
                state=state,
                predecessor_rule_id=(
                    last_record[rule_id].predecessor_rule_id
                    if last_record[rule_id].predecessor_rule_id != rule_id
                    else None
                ),
                successor_rule_ids=tuple(sorted(successors.get(rule_id, ()))),
                first_seen_artifact_id=first_seen[rule_id],
                last_seen_artifact_id=last_seen[rule_id],
                claimed_uccs=tuple(sorted(last_record[rule_id].source_uccs)),
            )
        )
    return tuple(lineage)


def _cross_check_transitions(head_path: Path, successors: Mapping[str, Sequence[str]]) -> None:
    """Fail if the declared transition block disagrees with the rule fields."""
    payload = _load(head_path)
    declared: dict[str, set[str]] = {}
    for entry in payload.get("residual_transitions", ()):
        pred = entry.get("predecessor_rule_id")
        rule_id = entry.get("rule_id")
        if pred is None or pred == rule_id:
            # Evidence was revised without the rule's identity changing. That
            # is a transition in the sense the residual task meant, and not an
            # edge in a lineage graph.
            continue
        declared.setdefault(pred, set()).add(rule_id)
    derived = {k: set(v) for k, v in successors.items()}
    if declared != derived:
        raise CanonicalStateError(
            f"residual_transitions and predecessor_rule_id disagree about "
            f"rule lineage: transitions say "
            f"{ {k: sorted(v) for k, v in sorted(declared.items())} }, rule "
            f"fields say { {k: sorted(v) for k, v in sorted(derived.items())} }"
        )


# ---------------------------------------------------------------------------
# C1.4 -- the canonical UCC resolver
# ---------------------------------------------------------------------------


class UccRuleRole(str, Enum):
    """How a UCC relates to the rule that mentions it."""

    #: The rule claims the UCC's source expenditure.
    SOURCE = "SOURCE"
    #: The rule names the UCC only as a destination for an amount that comes
    #: from other UCCs. The UCC carries no source amount of its own.
    OUTPUT_ONLY = "OUTPUT_ONLY"
    #: No rule mentions the UCC.
    UNCLAIMED = "UNCLAIMED"


@dataclass(frozen=True)
class UccResolution:
    """The single current governing rule for one UCC, and its state."""

    ucc: str
    governing_rule_id: str | None
    governing_registry_artifact_id: str | None
    canonical_rule_state: CanonicalRuleState
    role: UccRuleRole
    rule_type: str | None
    review_status: str | None
    proposed_track_a_status: str | None
    effective_track_a_status: str | None
    blocker_kind: str | None
    is_withheld_by_rule: bool


@dataclass(frozen=True)
class CanonicalRules:
    """The governing scope-rule registry, resolved."""

    artifact_id: str
    version: str
    relative_path: str
    rules: tuple[RuleRecord, ...]
    lineage: tuple[RuleLineage, ...]
    _source_claim: Mapping[str, str]
    _output_claim: Mapping[str, str]

    def rule(self, rule_id: str) -> RuleRecord:
        for record in self.rules:
            if record.rule_id == rule_id:
                return record
        raise CanonicalStateError(f"no rule {rule_id!r} in {self.artifact_id}")

    @property
    def claimed_source_uccs(self) -> frozenset[str]:
        return frozenset(self._source_claim)

    @property
    def claimed_output_uccs(self) -> frozenset[str]:
        return frozenset(self._output_claim)

    def resolve(self, ucc: str) -> UccResolution:
        """Return the one current governing rule for ``ucc``.

        A UCC named as a source by one rule and as an output by another is a
        source: the source claim is the one that decides what happens to an
        amount. A UCC named as both by the *same* rule is the identity case
        that ``REASSIGN`` and ``INTRODUCE`` produce, and is also a source.
        """
        rule_id = self._source_claim.get(ucc)
        role = UccRuleRole.SOURCE
        if rule_id is None:
            rule_id = self._output_claim.get(ucc)
            role = UccRuleRole.OUTPUT_ONLY
        if rule_id is None:
            return UccResolution(
                ucc=ucc,
                governing_rule_id=None,
                governing_registry_artifact_id=None,
                canonical_rule_state=CanonicalRuleState.NOT_APPLICABLE,
                role=UccRuleRole.UNCLAIMED,
                rule_type=None,
                review_status=None,
                proposed_track_a_status=None,
                effective_track_a_status=None,
                blocker_kind=None,
                is_withheld_by_rule=False,
            )
        record = self.rule(rule_id)
        state = canonical_state_of(record)
        if state not in RESOLVABLE_STATES:
            raise CanonicalStateError(
                f"UCC {ucc} resolves to rule {rule_id} in state {state.value}; "
                f"only {sorted(s.value for s in RESOLVABLE_STATES)} may govern "
                f"a UCC"
            )
        return UccResolution(
            ucc=ucc,
            governing_rule_id=rule_id,
            governing_registry_artifact_id=self.artifact_id,
            canonical_rule_state=state,
            role=role,
            rule_type=record.rule_type,
            review_status=record.review_status,
            proposed_track_a_status=record.final_status,
            effective_track_a_status=effective_track_a_status(record),
            blocker_kind=record.blocker_kind,
            is_withheld_by_rule=ucc in record.withheld_uccs,
        )


def load_canonical_rules(registry_dir: Path = REGISTRY_DIR) -> CanonicalRules:
    """Load the governing scope-rule registry and index it by UCC.

    Two current rules claiming the same UCC as a source is the failure this
    function exists to catch. It raises rather than choosing, because there is
    no defensible way to choose: the amount would be excluded under one rule
    and retained under the other, and picking either silently would produce a
    number with no basis.
    """
    head = governing_version("ce_cpi_scope_rules", registry_dir=registry_dir)
    rules = read_rules(_file_of(head, registry_dir))
    lineage = build_rule_lineage(registry_dir=registry_dir)

    source_claim: dict[str, str] = {}
    output_claim: dict[str, str] = {}
    for record in rules:
        for ucc in record.source_uccs:
            if ucc in source_claim:
                raise CanonicalStateError(
                    f"UCC {ucc} is claimed as a source by two current rules, "
                    f"{source_claim[ucc]} and {record.rule_id}; the governing "
                    f"registry {head.artifact_id} does not determine one "
                    f"treatment for it"
                )
            source_claim[ucc] = record.rule_id
        for ucc in record.output_uccs:
            prior = output_claim.get(ucc)
            if prior is not None and prior != record.rule_id:
                raise CanonicalStateError(
                    f"UCC {ucc} is named as an output by two current rules, "
                    f"{prior} and {record.rule_id}"
                )
            output_claim[ucc] = record.rule_id
        for ucc in record.withheld_uccs:
            if ucc not in record.source_uccs:
                raise CanonicalStateError(
                    f"rule {record.rule_id} withholds {ucc}, which it does not "
                    f"claim"
                )

    return CanonicalRules(
        artifact_id=head.artifact_id,
        version=head.version,
        relative_path=head.relative_path,
        rules=rules,
        lineage=lineage,
        _source_claim=source_claim,
        _output_claim=output_claim,
    )


# ---------------------------------------------------------------------------
# C1.5 -- current PUMD quantitative usability
# ---------------------------------------------------------------------------


def current_pumd_usability(registry_dir: Path = REGISTRY_DIR) -> dict[str, str]:
    """Return the governing ``pumd_quantitative_usability`` by UCC.

    The per-UCC roster on disk
    (``data/research/detailed_inflation/milestone_2/ucc_provenance_classes_2024.csv``)
    is the v0.1-vintage baseline and says ``NOT_ESTABLISHED`` for all 1,015
    UCCs. The governing v0.4 registry does not restate the roster; it records
    the differences, in ``usability_transitions_from_v0_1``. Current usability
    is therefore the baseline with the transitions applied, and reading either
    half alone gives the wrong answer for three UCCs.

    Only the transitions are returned. A caller that wants the full roster
    applies these over the baseline it already has.
    """
    head = governing_version("ucc_provenance_classes", registry_dir=registry_dir)
    payload = _load(_file_of(head, registry_dir))
    transitions: dict[str, str] = {}
    for entry in payload.get("usability_transitions_from_v0_1", ()):
        ucc = entry["ucc"]
        if ucc in transitions:
            raise CanonicalStateError(
                f"{head.artifact_id}: two usability transitions for {ucc}"
            )
        transitions[ucc] = entry["to"]
    return transitions


#: Contradictions found inside a governing registry and deliberately not
#: repaired here. Repairing one would be an adjudication, and this task has no
#: authority to adjudicate. Recording it means a consumer reads the structured
#: field knowing the prose beside it disagrees, rather than reading the prose
#: and being wrong.
KNOWN_INTERNAL_INCONSISTENCIES: tuple[Mapping[str, str], ...] = (
    {
        "artifact_id": "UCC_PROVENANCE_CLASSES_V0_4",
        "location": "classes.CONCORDANCE_ONLY_UCC.expenditure_note",
        "prose_claim": (
            "pumd_quantitative_usability is NOT_ESTABLISHED for all 17 "
            "concordance-only UCCs."
        ),
        "structured_claim": (
            "usability_transitions_from_v0_1 in the same file records 910104, "
            "910105 and 910107 moving from NOT_ESTABLISHED to BENCHMARKED."
        ),
        "resolution_in_this_manifest": (
            "The structured field governs. The prose is carried forward "
            "verbatim from v0.1 and was not updated when the transitions were "
            "added in v0.3. Both readings are recorded so that a consumer "
            "who read the prose can see why the number differs."
        ),
        "not_repaired_because": (
            "Changing a governing registry's text is an adjudication. This "
            "task is authorised to describe the current state, not to revise "
            "it. The correction belongs to whoever next opens that registry."
        ),
    },
    {
        "artifact_id": "UCC_PROVENANCE_CLASSES_V0_4",
        "location": (
            "shelter_rental_equivalence_correspondence.normative_input_rationale"
        ),
        "prose_claim": (
            "pumd_quantitative_usability is NOT_ESTABLISHED for all four "
            "rental-equivalence UCCs and the Track-A shelter rule remains "
            "PENDING."
        ),
        "structured_claim": (
            "Three of the four are BENCHMARKED per "
            "usability_transitions_from_v0_1. The second half of the sentence "
            "is still correct for the secondary rule and no longer correct "
            "for the primary one, which is ACCEPTED and EFFECTIVE in "
            "CE_CPI_SCOPE_RULES_V0_3."
        ),
        "resolution_in_this_manifest": (
            "The structured fields govern, in both registries."
        ),
        "not_repaired_because": (
            "Same reason. The two halves of the sentence went stale at "
            "different milestones, which is worth someone's attention and is "
            "not this task's to give."
        ),
    },
)


# ---------------------------------------------------------------------------
# C1.6 -- the manifest
# ---------------------------------------------------------------------------


def _version_payload(version: RegistryVersion) -> dict:
    return {
        "artifact_id": version.artifact_id,
        "path": version.relative_path,
        "predecessor_artifact_id": version.predecessor_artifact_id,
        "role": version.role.value,
        "version": version.version,
    }


def _source_payload(filename: str, registry_dir: Path = REGISTRY_DIR) -> dict:
    payload = _load(registry_dir / filename)
    return {
        "artifact_id": payload["artifact_id"],
        "path": f"registry/research/{filename}",
        "publisher": payload.get("publisher"),
        "source_file_name": payload.get("source_file_name"),
        "source_sha256": payload.get("source_sha256"),
        "version": payload.get("version"),
    }


def build_manifest(registry_dir: Path = REGISTRY_DIR) -> dict:
    """Assemble the canonical substrate manifest.

    Carries no timestamp and no host detail. A manifest that changes when it
    is rebuilt cannot be used to detect that something else changed.
    """
    families = {
        family: [
            _version_payload(v) for v in resolve_family(family, registry_dir=registry_dir)
        ]
        for family in sorted(REGISTRY_FAMILIES)
    }
    rules = load_canonical_rules(registry_dir=registry_dir)

    state_counts: dict[str, int] = {s.value: 0 for s in CanonicalRuleState}
    for node in rules.lineage:
        state_counts[node.state.value] += 1

    lineage_payload = [
        {
            "claimed_uccs": list(node.claimed_uccs),
            "first_seen_artifact_id": node.first_seen_artifact_id,
            "last_seen_artifact_id": node.last_seen_artifact_id,
            "predecessor_rule_id": node.predecessor_rule_id,
            "rule_id": node.rule_id,
            "state": node.state.value,
            "successor_rule_ids": list(node.successor_rule_ids),
        }
        for node in rules.lineage
    ]

    return {
        "artifact_id": MANIFEST_ARTIFACT_ID,
        "checkpoints": [
            {
                "commit": cp.commit,
                "milestone": cp.milestone,
                "role": cp.role.value,
                "tag": cp.tag,
            }
            for cp in CHECKPOINTS
        ],
        "checkpoint_semantics": {
            "CURRENT_GOVERNING_INPUT": (
                "The commit the current research state is built from. Exactly "
                "one checkpoint holds this role."
            ),
            "HISTORICAL_CHECKPOINT": (
                "A frozen milestone. Its artifacts are evidence of what was "
                "believed then and are never inputs to current work. They are "
                "preserved byte-for-byte and must not be edited."
            ),
        },
        "determinism": {
            "no_timestamp": (
                "This manifest carries no generation time, host, user or "
                "absolute path. Rebuilding it from the same commit produces "
                "the same bytes, so a diff means an input moved."
            ),
            "population_order": list(POPULATIONS),
            "sort_rule": (
                "Every list is sorted explicitly. Nothing here depends on "
                "dictionary insertion order or on filesystem iteration order."
            ),
        },
        "governing_registry_families": families,
        "known_internal_inconsistencies": [
            dict(entry) for entry in KNOWN_INTERNAL_INCONSISTENCIES
        ],
        "milestone": "Detailed Inflation Substrate v0.1, task C1",
        "pinned_bls_sources": [
            _source_payload(name, registry_dir)
            for name in sorted(PINNED_SOURCE_PROVENANCE)
        ],
        "pumd_usability_transitions_from_v0_1": dict(
            sorted(current_pumd_usability(registry_dir=registry_dir).items())
        ),
        "reference_year": REFERENCE_YEAR,
        "rule_lineage": lineage_payload,
        "rule_lineage_state_counts": dict(sorted(state_counts.items())),
        "rule_state_semantics": {
            "CURRENT_EFFECTIVE": (
                "Present in the governing registry, ACCEPTED and applicable. "
                "Its disposition is in force and may populate an effective "
                "amount."
            ),
            "CURRENT_OPEN": (
                "Present in the governing registry and proposing nothing. "
                "Undecided, which is not the same as blocked."
            ),
            "CURRENT_PENDING": (
                "Present in the governing registry with a proposed "
                "disposition that is not in force. It may never populate an "
                "effective exclusion or transformation amount."
            ),
            "HISTORICAL_ONLY": (
                "Absent from the governing registry with no successor naming "
                "it. It existed and was dropped. The count is currently zero, "
                "which is stated rather than left to be inferred from the "
                "absence of entries."
            ),
            "NOT_APPLICABLE": "No rule applies.",
            "SUPERSEDED": (
                "Absent from the governing registry, with one or more "
                "successors naming it as their predecessor. Its UCCs are "
                "claimed by those successors and must never be resolved "
                "through it."
            ),
        },
        "scope": (
            "Research only. This manifest records which vintages, registry "
            "versions and rules govern the 2024 Detailed Inflation Substrate. "
            "It authorises no figure, computes no weight and adjudicates "
            "nothing."
        ),
        "single_version_registries": [
            {
                "artifact_id": _load(registry_dir / name).get(
                    "artifact_id", _load(registry_dir / name).get("artifact", name)
                ),
                "path": f"registry/research/{name}",
                "role": ArtifactRole.CURRENT_GOVERNING_INPUT.value,
            }
            for name in sorted(SINGLE_VERSION_REGISTRIES)
        ],
        "status": "RESEARCH_ONLY",
        "ucc_claims": {
            "claimed_as_output_only": sorted(
                rules.claimed_output_uccs - rules.claimed_source_uccs
            ),
            "claimed_as_source": sorted(rules.claimed_source_uccs),
            "note": (
                "Every UCC below is claimed by exactly one current rule. A "
                "second claim is a build failure, not a warning: the amount "
                "would have two treatments and no way to choose."
            ),
        },
        "version": MANIFEST_VERSION,
        "why_lineage_is_derived": (
            "Three versions of the scope-rule registry and three of the "
            "provenance registry are committed side by side, on purpose. "
            "Filename order does not identify the head: "
            "ucc_provenance_classes_v0_1.json carries version 0.2.0 and no "
            "v0_2 file exists. The head of each family is derived from the "
            "predecessor block each successor carries, and the derivation "
            "fails if the chain forks, breaks or has two roots."
        ),
    }


def render_manifest(registry_dir: Path = REGISTRY_DIR) -> str:
    """The exact bytes of the manifest.

    Separate from :func:`write_manifest` so that a determinism check and a
    real build render through the same code. A check that renders differently
    from the build it verifies can pass while the build is broken.
    """
    return (
        json.dumps(build_manifest(registry_dir=registry_dir), indent=2, sort_keys=True)
        + "\n"
    )


def write_manifest(path: Path = MANIFEST_PATH, registry_dir: Path = REGISTRY_DIR) -> Path:
    """Write the manifest to ``path`` and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_manifest(registry_dir=registry_dir), encoding="utf-8")
    return path


__all__ = [
    "ArtifactRole",
    "CHECKPOINTS",
    "CanonicalRuleState",
    "CanonicalRules",
    "CanonicalStateError",
    "Checkpoint",
    "CheckpointRole",
    "KNOWN_INTERNAL_INCONSISTENCIES",
    "MANIFEST_PATH",
    "POPULATIONS",
    "RESOLVABLE_STATES",
    "RegistryVersion",
    "RuleLineage",
    "RuleRecord",
    "UccResolution",
    "UccRuleRole",
    "build_manifest",
    "build_rule_lineage",
    "canonical_state_of",
    "current_pumd_usability",
    "effective_track_a_status",
    "governing_version",
    "load_canonical_rules",
    "read_rules",
    "render_manifest",
    "resolve_family",
    "write_manifest",
]
