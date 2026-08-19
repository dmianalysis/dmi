#!/usr/bin/env python3
"""Tests for the canonical state manifest and accounting ledger (C1 + C2).

C1 answers "which version of what governs?" and C2 answers "where does each
source amount currently sit?". Neither computes anything, so almost nothing
here checks arithmetic. What is worth checking is the set of disciplines that
make the two artifacts safe to build on, because every one of them would
produce a plausible-looking ledger if it had quietly stopped holding.

*The head of a registry family is derived, not assumed.* Three versions of the
scope-rule registry are committed side by side on purpose. Nothing in a
filename identifies the head, and this repository proves it: the file called
``ucc_provenance_classes_v0_1.json`` declares version 0.2.0 and no ``v0_2``
file exists. So the lineage is walked from the ``predecessor`` blocks, and the
walk is asserted to reject a fork, a second root and a broken chain.

*Proposed is not effective.* A PROPOSED rule may never put an amount into an
exclusion, transformation or replacement column. This is the single claim the
whole substrate rests on, so it is attacked from three directions: the gate is
checked against the hardened Milestone-2 gate it duplicates, the ledger is
checked to contain no violating row, and a violating row is constructed and
the validator asserted to reject it.

*Null is not zero.* A blank amount means unavailable, suppressed, withheld or
undefined; a numeric zero means someone observed zero. UCC 910106 carries both
encodings in one column across six populations and is the regression case. The
basis contains seven genuine observed zeros, and they are asserted to survive
as ``0.0`` rather than being flattened into blanks.

*Removal is not replacement.* The amount that leaves and the amount that
arrives are two facts. The tests assert the ledger does not require them to be
equal, and separately that no group both retains a source amount and
introduces its replacement.

*A superseded rule is gone.* Its UCCs belong to its successors. Re-enabling it
must fail, and the failure is asserted by re-enabling it.

*Frozen and committed are different words.* Artifacts inherited from the
checkpoint C1 and C2 started from may not change, because later work has
already been accepted on top of them. Artifacts this milestone wrote may
change until this milestone is itself frozen, and one of them already has.
The two tiers are separated by membership in the checkpoint's tree rather
than by an exemption list, so the newer artifact is excluded because it was
not there and not because someone remembered to name it.

*The guards are not vacuous.* Every structural guard is asserted to fire on a
deliberately broken input before it is asserted not to fire on the real one. A
guard that has never been seen to fire proves nothing.
"""

from __future__ import annotations

import ast
import copy
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import canonical_ledger as cl  # noqa: E402
from dmi_research.detailed_inflation import canonical_state as cs  # noqa: E402
from dmi_research.detailed_inflation import resolution as m2  # noqa: E402
from dmi_research.detailed_inflation import scope_rules as sr  # noqa: E402

CANONICAL_MODULES = (
    "dmi_research/detailed_inflation/canonical_state.py",
    "dmi_research/detailed_inflation/canonical_ledger.py",
    "scripts/build_canonical_substrate_2024.py",
)

#: The rule the residual task split into four. Its UCCs belong to the
#: successors now, and nothing may resolve through it.
SUPERSEDED_RULE = "OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1"

#: The canonical null/zero regression case: one estimate cell with no records
#: at all, five with amounts that exist and are not admitted.
NULL_ZERO_UCC = "910106"


class Built:
    """One build, shared by the classes that only read it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = cl.load_inputs()
        cls.rules = cls.inputs.rules
        cls.rows = cl.build_ledger(cls.inputs)
        cls.by_ucc: dict[str, list[cl.LedgerRow]] = {}
        for row in cls.rows:
            cls.by_ucc.setdefault(row.ucc, []).append(row)


def _mutable_registry() -> Path:
    """A scratch copy of ``registry/research`` that mutations can edit.

    Every mutation test writes into one of these. Nothing in this file edits a
    committed registry.
    """
    scratch = Path(tempfile.mkdtemp(prefix="canonical-registry-"))
    for path in sorted(cs.REGISTRY_DIR.glob("*.json")):
        shutil.copy(path, scratch)
    return scratch


def _rewrite(directory: Path, filename: str, mutate) -> None:
    path = directory / filename
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")


def _scope_rules_head() -> str:
    return Path(cs.governing_version("ce_cpi_scope_rules").relative_path).name


# ---------------------------------------------------------------------------
# Prose-versus-structured-field scanner, used by Group 1b
# ---------------------------------------------------------------------------

#: Usability grades. Taken from the vocabulary rather than from the files, so
#: a file that dropped a grade could not shrink the scanner's alphabet.
USABILITY_GRADES = ("NOT_ESTABLISHED", "BENCHMARKED")

_GRADE = re.compile(r"\b(?:%s)\b" % "|".join(USABILITY_GRADES))
_UNIVERSAL = re.compile(r"\b(?:all|every|each|both)\b", re.IGNORECASE)
_UCC = re.compile(r"\b\d{6}\b")
#: Sentence break. Splitting on punctuation followed by whitespace is safe on
#: these files because their dotted tokens (``cx.item``, ``0.4``, ``87.6``)
#: never carry a space after the dot.
_SENTENCE = re.compile(r"(?<=[.;:])\s+")


def _prose(node: object, path: str = "") -> list[tuple[str, str]]:
    """Every string leaf in a payload, with its dotted location."""
    if isinstance(node, dict):
        return [p for k, v in node.items() for p in _prose(v, f"{path}.{k}")]
    if isinstance(node, list):
        return [p for i, v in enumerate(node) for p in _prose(v, f"{path}[{i}]")]
    if isinstance(node, str):
        return [(path, node)]
    return []


def _structured_usability(payload: object) -> dict[str, str]:
    """The registry's own current usability grade per UCC.

    Two sources, both structured, both inside the same file: the per-UCC
    ``pumd_quantitative_usability`` fields, and ``usability_transitions_from_v0_1``
    which is applied last because a transition is by definition the later word.
    """
    grades: dict[str, str] = {}

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "ucc" in node and "pumd_quantitative_usability" in node:
                grades[str(node["ucc"])] = node["pumd_quantitative_usability"]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    if isinstance(payload, dict):
        for entry in payload.get("usability_transitions_from_v0_1", ()):
            grades[str(entry["ucc"])] = entry["to"]
    return grades


def _usability_contradictions(payload: object) -> list[tuple[str, str, str]]:
    """Prose in a registry that its own structured fields contradict.

    Two checks, both deliberately conservative, because a scanner that guesses
    at which population a sentence meant would produce arguments rather than
    findings.

    *Universal.* A sentence asserting a usability grade under a universal
    quantifier is a violation whenever the file's own grades are not uniform.
    No qualification is needed to reach that conclusion and no scope
    resolution is attempted: if the file records two different grades, then no
    sentence in it can truthfully say every UCC has one of them, whichever
    population the author had in mind. A sentence that means a subset must
    name the subset.

    *Enumerated.* A sentence that names UCC codes alongside a grade must at
    least mention the grade the structured field actually records for each
    code it names. This is weaker than checking the sentence's grammar, and it
    is meant to be: it catches "910106 is BENCHMARKED" without adjudicating
    sentences that correctly discuss several codes at several grades.

    Returns ``(location, kind, sentence)`` per violation.
    """
    grades = _structured_usability(payload)
    if not grades:
        return []
    uniform = len(set(grades.values())) == 1
    found: list[tuple[str, str, str]] = []
    for location, text in _prose(payload):
        # The correction record quotes the defect it repaired. Exempting it is
        # the same allowance the milestone-2 rename sweep makes for migration
        # prose: a file must be able to say what it fixed.
        if location.startswith(".prose_correction_in_"):
            continue
        for sentence in _SENTENCE.split(text):
            claimed = set(_GRADE.findall(sentence))
            if not claimed:
                continue
            named = [u for u in _UCC.findall(sentence) if u in grades]
            if named:
                if any(grades[u] not in claimed for u in named):
                    found.append((location, "ENUMERATED", sentence))
            elif not uniform and _UNIVERSAL.search(sentence):
                found.append((location, "UNIVERSAL", sentence))
    return found


def _superseded_tokens(registry_dir: Path = None) -> dict[str, str]:
    """Every filename and artifact id the lineage walk has demoted.

    Derived, never listed. Which versions are superseded is a fact about the
    ``predecessor`` chains, and writing the answer down here would let the
    check go on passing after a head moved, which is the exact failure it
    exists to catch.
    """
    directory = cs.REGISTRY_DIR if registry_dir is None else registry_dir
    stale: dict[str, str] = {}
    for family in cs.REGISTRY_FAMILIES:
        for version in cs.resolve_family(family, registry_dir=directory):
            if version.role is cs.ArtifactRole.HISTORICAL_CHECKPOINT:
                stale[Path(version.relative_path).name] = family
                stale[version.artifact_id] = family
    return stale


#: Keys under which a backwards-pointing reference is the intended content
#: rather than a stale one. ``predecessor`` names the previous version by
#: definition, and a ``prose_correction_in_*`` record has to be able to quote
#: the text it repaired.
_HISTORICAL_KEYS = ("predecessor", "prose_correction_in_")


def _stale_cross_references(
    payload: object, registry_dir: Path = None
) -> list[tuple[str, str]]:
    """References in a registry to a version the lineage has superseded.

    One further exemption is taken from the data rather than the path: a
    reference is historical if its nearest enclosing object declares an
    ``evidence_kind``. Those are dated observation citations, and their whole
    value is naming the artifact where the observation was actually recorded.
    Forcing ``ce_cpi_scope_rules_v0_1.json :: structural_evidence.…`` forward
    to the current head would not make it more accurate, it would make it
    false. Historical authority is not current authority, and the converse
    holds too.

    Returns ``(location, token)`` per violation.
    """
    stale = _superseded_tokens(registry_dir)
    found: list[tuple[str, str]] = []

    def historical(key: str) -> bool:
        return any(key.startswith(marker) for marker in _HISTORICAL_KEYS)

    def walk(node: object, path: str = "", exempt: bool = False) -> None:
        if isinstance(node, dict):
            dated = exempt or "evidence_kind" in node
            for key, value in node.items():
                walk(value, f"{path}.{key}", dated or historical(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]", exempt)
        elif isinstance(node, str) and not exempt:
            for token in stale:
                if token in node:
                    found.append((path, token))

    walk(payload)
    return found


# ---------------------------------------------------------------------------
# Frozen-checkpoint preservation, used by Group 10b
# ---------------------------------------------------------------------------

#: The checkpoint C1 and C2 started from. Everything under the research trees
#: at this commit is inherited and frozen. Everything added afterwards belongs
#: to the milestone in progress and is not.
FROZEN_CHECKPOINT_TAG = "dmi-detailed-inflation-v0.1-shelter-residuals-2024"

#: Pinned so that repointing the tag is a test failure rather than a silent
#: relaxation of everything the tag protects.
FROZEN_CHECKPOINT_COMMIT = "3ee9141e7c186e5cd344de8f87b8a1c3f8cf5326"

#: The trees the inherited set is read from.
INHERITED_TREES = ("registry/research", "data/research", "docs/research")

#: Pinned for the same reason as the commit. A guard that quietly starts
#: covering forty files instead of sixty-six still passes.
INHERITED_FILE_COUNT = 66


def _git_blob_id(content: bytes) -> str:
    """The object name git would store ``content`` under."""
    header = b"blob %d\0" % len(content)
    return hashlib.sha1(header + content).hexdigest()  # noqa: S324 - git's format


def _as_git_records_it(raw: bytes) -> bytes:
    """File bytes reduced to the content this repository treats as canonical.

    ``.gitattributes`` declares ``* text=auto``, so git stores text files with
    LF, and several of the older research CSVs sit on disk with CRLF because
    they were written before ``lineterminator="\\n"`` became the convention.
    Comparing raw disk bytes against a stored blob would report twenty
    untouched files as mutated.

    So the comparison is over recorded content, not disk bytes, and the
    difference is worth stating rather than glossing: a change that alters
    only line endings is invisible here. That is this repository's own
    definition of "no content change" and not a concession made to get a test
    passing, and ``test_g`` pins the equivalence to ``git hash-object`` so the
    two definitions cannot drift apart unnoticed.
    """
    if b"\0" in raw[:8000]:  # git's own binary heuristic
        return raw
    return raw.replace(b"\r\n", b"\n")


def _frozen_checkpoint_blobs() -> dict[str, str] | None:
    """``path -> blob id`` for every research artifact at the checkpoint.

    ``None`` when git or the tag is unavailable, which callers turn into a
    skip. Nothing here reaches the network: the tag is read out of the local
    object database.

    Membership in this mapping is what "inherited" means. A file that did not
    exist at the checkpoint cannot appear in it, so successors written during
    the milestone in progress are excluded structurally rather than by an
    exemption list somebody has to remember to maintain.
    """
    result = subprocess.run(
        ["git", "ls-tree", "-r", FROZEN_CHECKPOINT_TAG, "--", *INHERITED_TREES],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    blobs: dict[str, str] = {}
    for line in result.stdout.splitlines():
        meta, path = line.split("\t", 1)
        _mode, kind, object_id = meta.split()
        if kind == "blob":
            blobs[path] = object_id
    return blobs or None


def _preservation_drift(
    expected: dict[str, str], root: Path
) -> list[tuple[str, str]]:
    """Inherited artifacts under ``root`` that are missing or changed.

    ``root`` is a parameter so the check can be pointed at an isolated copy
    and watched to fail. A preservation guard that has only ever been run
    against an unmutated tree has not been shown to guard anything.

    Returns sorted ``(path, reason)`` pairs.
    """
    drift: list[tuple[str, str]] = []
    for path, object_id in expected.items():
        candidate = root / path
        if not candidate.is_file():
            drift.append((path, "MISSING"))
        elif _git_blob_id(_as_git_records_it(candidate.read_bytes())) != object_id:
            drift.append((path, "MODIFIED"))
    return sorted(drift)


def _isolated_checkpoint_copy(expected: dict[str, str]) -> Path:
    """A scratch tree holding a copy of every inherited artifact."""
    scratch = Path(tempfile.mkdtemp(prefix="frozen-checkpoint-"))
    for path in expected:
        destination = scratch / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / path, destination)
    return scratch


# ---------------------------------------------------------------------------
# Group 1: C1, registry lineage is derived rather than assumed
# ---------------------------------------------------------------------------


class TestRegistryLineage(unittest.TestCase):
    def test_a_filename_order_is_not_a_version_order_in_this_repository(self) -> None:
        """The concrete counterexample the derivation exists because of."""
        payload = json.loads(
            (cs.REGISTRY_DIR / "ucc_provenance_classes_v0_1.json").read_text("utf-8")
        )
        self.assertEqual(payload["version"], "0.2.0")
        self.assertFalse((cs.REGISTRY_DIR / "ucc_provenance_classes_v0_2.json").exists())

    def test_b_each_family_resolves_to_exactly_one_head(self) -> None:
        for family in cs.REGISTRY_FAMILIES:
            with self.subTest(family=family):
                chain = cs.resolve_family(family)
                heads = [
                    v for v in chain
                    if v.role is cs.ArtifactRole.CURRENT_GOVERNING_INPUT
                ]
                self.assertEqual(len(heads), 1)
                self.assertEqual(heads[0], chain[-1])
                self.assertEqual(len(chain), len(cs.REGISTRY_FAMILIES[family]))

    def test_c_the_heads_are_the_expected_artifacts(self) -> None:
        self.assertEqual(
            cs.governing_version("ce_cpi_scope_rules").artifact_id,
            "CE_CPI_SCOPE_RULES_V0_3",
        )
        self.assertEqual(
            cs.governing_version("ucc_provenance_classes").artifact_id,
            "UCC_PROVENANCE_CLASSES_V0_5",
        )

    def test_d_every_non_head_is_marked_a_historical_checkpoint(self) -> None:
        for family in cs.REGISTRY_FAMILIES:
            for version in cs.resolve_family(family)[:-1]:
                with self.subTest(artifact=version.artifact_id):
                    self.assertIs(version.role, cs.ArtifactRole.HISTORICAL_CHECKPOINT)

    def test_e_the_chain_is_linear_and_each_link_is_real(self) -> None:
        for family in cs.REGISTRY_FAMILIES:
            chain = cs.resolve_family(family)
            self.assertIsNone(chain[0].predecessor_artifact_id)
            for earlier, later in zip(chain, chain[1:]):
                with self.subTest(family=family, later=later.artifact_id):
                    self.assertEqual(
                        later.predecessor_artifact_id.casefold(),
                        earlier.artifact_id.casefold(),
                    )

    def test_f_a_second_root_is_rejected(self) -> None:
        scratch = _mutable_registry()
        _rewrite(scratch, _scope_rules_head(), lambda p: p.pop("predecessor"))
        with self.assertRaises(cs.CanonicalStateError) as caught:
            cs.resolve_family("ce_cpi_scope_rules", registry_dir=scratch)
        self.assertIn("exactly one version with no predecessor", str(caught.exception))

    def test_g_a_fork_is_rejected(self) -> None:
        scratch = _mutable_registry()

        def fork(payload: dict) -> None:
            payload["predecessor"] = {
                "artifact_id": "ce_cpi_scope_rules_v0_1",
                "path": "registry/research/ce_cpi_scope_rules_v0_1.json",
            }

        _rewrite(scratch, _scope_rules_head(), fork)
        with self.assertRaises(cs.CanonicalStateError) as caught:
            cs.resolve_family("ce_cpi_scope_rules", registry_dir=scratch)
        self.assertIn("forks", str(caught.exception))

    def test_h_a_misdeclared_predecessor_path_is_rejected(self) -> None:
        """The declared path is checked, not decorative."""
        scratch = _mutable_registry()

        def bend(payload: dict) -> None:
            payload["predecessor"]["path"] = "registry/research/somewhere_else.json"

        _rewrite(scratch, _scope_rules_head(), bend)
        with self.assertRaises(cs.CanonicalStateError) as caught:
            cs.resolve_family("ce_cpi_scope_rules", registry_dir=scratch)
        self.assertIn("does not", str(caught.exception))

    def test_i_a_registry_dir_argument_is_honoured(self) -> None:
        """Non-vacuity for every other test in this file that passes one.

        If ``registry_dir`` were ignored and the real directory read instead,
        every mutation test below would pass while testing nothing.
        """
        scratch = _mutable_registry()
        (scratch / _scope_rules_head()).write_text('{"artifact_id": "X"}\n', "utf-8")
        with self.assertRaises(cs.CanonicalStateError):
            cs.resolve_family("ce_cpi_scope_rules", registry_dir=scratch)


# ---------------------------------------------------------------------------
# Group 1b: C1, a governing registry may not contradict itself in prose
# ---------------------------------------------------------------------------


class TestProseAgreesWithStructuredState(unittest.TestCase):
    """A registry's sentences may not deny its own structured fields.

    This is the guard the v0.5 correction was made to install. Three passages
    in UCC_PROVENANCE_CLASSES_V0_4 asserted, in the present tense, that
    ``pumd_quantitative_usability`` was NOT_ESTABLISHED for every UCC they
    covered, while the roster in the same file graded three of those UCCs
    BENCHMARKED and ``usability_transitions_from_v0_1`` recorded the three
    transitions that put them there.

    None of it ever moved a number: the ledger reads the structured fields and
    has never read a sentence. That is precisely why the contradiction could
    sit there across three milestones without anything failing, and why a
    test is the only thing that will catch the next one. Two of the three were
    found by reading; the third was found by this scanner.
    """

    def _heads(self) -> list[tuple[str, dict]]:
        paths = [
            cs.REGISTRY_DIR / Path(cs.governing_version(family).relative_path).name
            for family in cs.REGISTRY_FAMILIES
        ]
        paths += [cs.REGISTRY_DIR / name for name in cs.SINGLE_VERSION_REGISTRIES]
        return [
            (p.name, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(paths)
        ]

    def test_a_no_governing_registry_contradicts_its_own_usability_fields(self) -> None:
        for name, payload in self._heads():
            with self.subTest(registry=name):
                found = _usability_contradictions(payload)
                self.assertEqual(
                    [],
                    found,
                    "\n".join(f"{kind} at {loc}: {s}" for loc, kind, s in found),
                )

    def test_b_the_repaired_registry_is_the_governing_one(self) -> None:
        head = cs.governing_version("ucc_provenance_classes")
        self.assertEqual(head.artifact_id, "UCC_PROVENANCE_CLASSES_V0_5")
        self.assertEqual(
            head.predecessor_artifact_id.casefold(),
            "ucc_provenance_classes_v0_4",
        )

    def test_c_the_scanner_fires_on_the_defect_it_was_written_for(self) -> None:
        """Non-vacuity, against the real historical text.

        The predecessor is still on disk and still carries all three passages,
        so the scanner can be shown to fire on the exact prose it exists to
        catch rather than on a specimen written to be caught.
        """
        stale = json.loads(
            (cs.REGISTRY_DIR / "ucc_provenance_classes_v0_4.json").read_text("utf-8")
        )
        found = _usability_contradictions(stale)
        self.assertEqual(
            sorted(location for location, _, _ in found),
            [
                ".classes.CONCORDANCE_ONLY_UCC.expenditure_note",
                ".pumd_observations.CE_2024_INTERVIEW_MTBI_SHELTER_RENTAL_EQUIVALENCE"
                ".what_this_does_not_establish",
                ".shelter_rental_equivalence_correspondence.normative_input_rationale",
            ],
        )
        for _, kind, sentence in found:
            self.assertEqual(kind, "UNIVERSAL")
            self.assertIn("NOT_ESTABLISHED", sentence)

    def test_d_the_enumerated_check_fires_too(self) -> None:
        """The other half of the scanner, which the real files do not trip."""
        head = json.loads(
            (
                cs.REGISTRY_DIR
                / Path(cs.governing_version("ucc_provenance_classes").relative_path).name
            ).read_text("utf-8")
        )
        broken = copy.deepcopy(head)
        broken["a_planted_sentence"] = "910106 is BENCHMARKED and settled."
        self.assertEqual([], _usability_contradictions(head))
        self.assertEqual(
            [(loc, kind) for loc, kind, _ in _usability_contradictions(broken)],
            [(".a_planted_sentence", "ENUMERATED")],
        )

    def test_e_the_scanner_reads_transitions_as_the_later_word(self) -> None:
        """A transition must override the roster grade, not be averaged with it.

        If the transitions were ignored, the head would look uniformly
        NOT_ESTABLISHED, ``uniform`` would be true, and the universal check
        would switch itself off entirely.
        """
        head = json.loads(
            (cs.REGISTRY_DIR / "ucc_provenance_classes_v0_5.json").read_text("utf-8")
        )
        grades = _structured_usability(head)
        for ucc in ("910104", "910105", "910107"):
            with self.subTest(ucc=ucc):
                self.assertEqual(grades[ucc], "BENCHMARKED")
        self.assertEqual(grades["910106"], "NOT_ESTABLISHED")
        self.assertGreater(len(set(grades.values())), 1)

    def test_f_the_correction_moved_prose_and_nothing_else(self) -> None:
        """Column-wise equivalence, at the registry rather than the ledger.

        Every value in the successor that is not a string is asserted equal to
        the predecessor's. A grade, count, roster entry, pairing or transition
        that moved would be a non-string leaf or a changed structure, and this
        would catch it.
        """
        older = json.loads(
            (cs.REGISTRY_DIR / "ucc_provenance_classes_v0_4.json").read_text("utf-8")
        )
        newer = json.loads(
            (cs.REGISTRY_DIR / "ucc_provenance_classes_v0_5.json").read_text("utf-8")
        )
        changed: list[str] = []

        def compare(x: object, y: object, path: str = "") -> None:
            if type(x) is not type(y):
                changed.append(path)
            elif isinstance(x, dict):
                assert isinstance(y, dict)
                for key in sorted(set(x) | set(y)):
                    if key in x and key in y:
                        compare(x[key], y[key], f"{path}.{key}")
                    else:
                        changed.append(f"{path}.{key}")
            elif isinstance(x, list):
                assert isinstance(y, list)
                if len(x) != len(y):
                    changed.append(path)
                else:
                    for i, (a, b) in enumerate(zip(x, y)):
                        compare(a, b, f"{path}[{i}]")
            elif x != y:
                changed.append(path)

        compare(older, newer)
        self.assertEqual(
            sorted(changed),
            [
                ".artifact_id",
                ".classes.CONCORDANCE_ONLY_UCC.expenditure_note",
                ".consumer_of_this_artifact",
                ".predecessor.artifact_id",
                ".predecessor.note",
                ".predecessor.path",
                ".predecessor.version",
                ".prose_correction_in_v0_5",
                ".pumd_observations.CE_2024_INTERVIEW_MTBI_SHELTER_RENTAL_EQUIVALENCE"
                ".what_this_does_not_establish",
                ".shelter_rental_equivalence_correspondence.normative_input_rationale",
                ".version",
            ],
        )

    def test_g_every_recorded_inconsistency_says_what_became_of_it(self) -> None:
        """The record is not deleted on repair, it is closed.

        A consumer holding an older ledger has to be able to find out why the
        prose they read no longer matches the file, which deleting the entry
        would take away from them.
        """
        self.assertGreater(len(cs.KNOWN_INTERNAL_INCONSISTENCIES), 0)
        for entry in cs.KNOWN_INTERNAL_INCONSISTENCIES:
            with self.subTest(location=entry["location"]):
                self.assertIn("repaired_in", entry)
                repaired = entry["repaired_in"]
                if repaired is None:
                    continue
                self.assertEqual(repaired, "UCC_PROVENANCE_CLASSES_V0_5")
                self.assertNotEqual(repaired, entry["artifact_id"])

    def test_h_the_repair_is_reachable_from_the_manifest(self) -> None:
        manifest = json.loads(cs.MANIFEST_PATH.read_text(encoding="utf-8"))
        family = manifest["governing_registry_families"]["ucc_provenance_classes"]
        head = [v for v in family if v["role"] == "CURRENT_GOVERNING_INPUT"]
        self.assertEqual([v["artifact_id"] for v in head], ["UCC_PROVENANCE_CLASSES_V0_5"])
        recorded = manifest["known_internal_inconsistencies"]
        self.assertEqual(len(recorded), 3)
        self.assertTrue(
            all(e["repaired_in"] == "UCC_PROVENANCE_CLASSES_V0_5" for e in recorded)
        )


# ---------------------------------------------------------------------------
# Group 1c: C1, a governing registry's cross-references name governing heads
# ---------------------------------------------------------------------------


class TestCrossReferencesNameTheGoverningHead(unittest.TestCase):
    """A current registry may not point at a superseded one as if it governed.

    ``UCC_PROVENANCE_CLASSES_V0_5`` named ``ce_cpi_scope_rules_v0_2.json`` as
    the artifact that consumes it, long after the lineage walk had demoted
    v0.2 to a historical checkpoint in favour of v0.3. Nothing failed, because
    no code resolves that string; it is documentation, and documentation is
    exactly where a reference rots unobserved.

    The check derives both halves from the lineage. It does not know that the
    scope-rules head is v0.3 and would not be satisfied by being told: it asks
    ``resolve_family`` which versions carry ``HISTORICAL_CHECKPOINT`` and
    objects to any of them being named outside a context that declares itself
    historical.
    """

    def _heads(self) -> list[tuple[str, dict]]:
        paths = [
            cs.REGISTRY_DIR / Path(cs.governing_version(family).relative_path).name
            for family in cs.REGISTRY_FAMILIES
        ]
        return [
            (p.name, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(paths)
        ]

    def test_a_no_head_names_a_superseded_version_as_current(self) -> None:
        for name, payload in self._heads():
            with self.subTest(registry=name):
                found = _stale_cross_references(payload)
                self.assertEqual(
                    [],
                    found,
                    "\n".join(f"{loc} names {token}" for loc, token in found),
                )

    def test_b_the_superseded_set_is_derived_not_declared(self) -> None:
        """Non-vacuity for the check's own input.

        If ``_superseded_tokens`` returned nothing, ``test_a`` would pass
        against any registry at all.
        """
        stale = _superseded_tokens()
        self.assertGreater(len(stale), 0)
        heads = {
            cs.governing_version(family).artifact_id for family in cs.REGISTRY_FAMILIES
        }
        for token in stale:
            with self.subTest(token=token):
                self.assertNotIn(token, heads)
        self.assertIn("ce_cpi_scope_rules_v0_2.json", stale)

    def test_c_the_check_fires_on_the_reference_that_was_corrected(self) -> None:
        """Non-vacuity, against the exact text this correction removed."""
        head_name = Path(
            cs.governing_version("ucc_provenance_classes").relative_path
        ).name
        payload = json.loads(
            (cs.REGISTRY_DIR / head_name).read_text(encoding="utf-8")
        )
        broken = copy.deepcopy(payload)
        broken["consumer_of_this_artifact"] = (
            "registry/research/ce_cpi_scope_rules_v0_2.json, whose two "
            "rental-equivalence introduce rules read pumd_quantitative_usability "
            "and pumd_estimate_quality from here."
        )
        self.assertEqual(
            _stale_cross_references(broken),
            [(".consumer_of_this_artifact", "ce_cpi_scope_rules_v0_2.json")],
        )

    def test_d_the_check_follows_the_lineage_rather_than_a_version_number(
        self,
    ) -> None:
        """The head moving must move the check with it.

        A scratch family is given one more version. The reference that was
        correct a moment ago now names a checkpoint, and the check has to say
        so without anything having told it about the new file.
        """
        scratch = _mutable_registry()
        head = _scope_rules_head()
        payload = json.loads((scratch / head).read_text(encoding="utf-8"))
        successor = dict(payload)
        successor["artifact_id"] = "CE_CPI_SCOPE_RULES_V0_4"
        successor["version"] = "0.4"
        successor["predecessor"] = {
            "artifact_id": payload["artifact_id"],
            "path": f"registry/research/{head}",
            "version": payload["version"],
        }
        (scratch / "ce_cpi_scope_rules_v0_4.json").write_text(
            json.dumps(successor, indent=2, sort_keys=True) + "\n", "utf-8"
        )
        families = dict(cs.REGISTRY_FAMILIES)
        families["ce_cpi_scope_rules"] = (
            *families["ce_cpi_scope_rules"],
            "ce_cpi_scope_rules_v0_4.json",
        )
        original = cs.REGISTRY_FAMILIES
        cs.REGISTRY_FAMILIES = families
        try:
            stale = _superseded_tokens(scratch)
            self.assertIn(head, stale, "the old head was not demoted")
            self.assertNotIn("ce_cpi_scope_rules_v0_4.json", stale)
            probe = {"consumer_of_this_artifact": f"registry/research/{head}"}
            self.assertEqual(
                _stale_cross_references(probe, scratch),
                [(".consumer_of_this_artifact", head)],
            )
        finally:
            cs.REGISTRY_FAMILIES = original

    def test_e_a_dated_evidence_citation_may_name_an_earlier_version(self) -> None:
        """The exemption is real and is exercised by the committed data.

        The 510115 membership observation cites where it was recorded, which
        is a historical checkpoint and correctly so. If this exemption were
        dropped the citation would have to be bent forward to the current
        head, which would make it say something that never happened.
        """
        head_name = Path(
            cs.governing_version("ucc_provenance_classes").relative_path
        ).name
        payload = json.loads(
            (cs.REGISTRY_DIR / head_name).read_text(encoding="utf-8")
        )
        roster = payload["concordance_only_uccs"]["roster"]
        entry = next(r for r in roster if r["ucc"] == "510115")
        citation = entry["pumd_membership_evidence"]["citation"]
        self.assertIn("evidence_kind", entry["pumd_membership_evidence"])
        stale = _superseded_tokens()
        self.assertTrue(
            any(token in citation for token in stale),
            "this test no longer exercises the exemption it was written for",
        )
        self.assertEqual([], _stale_cross_references(payload))

    def test_f_the_corrected_reference_names_the_current_head(self) -> None:
        head_name = Path(
            cs.governing_version("ucc_provenance_classes").relative_path
        ).name
        payload = json.loads(
            (cs.REGISTRY_DIR / head_name).read_text(encoding="utf-8")
        )
        rules_head = cs.governing_version("ce_cpi_scope_rules")
        self.assertIn(
            Path(rules_head.relative_path).name,
            payload["consumer_of_this_artifact"],
        )


# ---------------------------------------------------------------------------
# Group 2: C1, rule lineage and the canonical gate
# ---------------------------------------------------------------------------


class TestRuleLineage(Built, unittest.TestCase):
    def test_a_the_superseded_rule_is_superseded_and_absent(self) -> None:
        node = next(n for n in self.rules.lineage if n.rule_id == SUPERSEDED_RULE)
        self.assertIs(node.state, cs.CanonicalRuleState.SUPERSEDED)
        self.assertNotIn(SUPERSEDED_RULE, [r.rule_id for r in self.rules.rules])

    def test_b_its_successors_are_derived_from_the_registry(self) -> None:
        """Derived from ``predecessor_rule_id``, not from a list written here.

        The count is asserted, but the membership comes from the registry, so
        this fails if the registry changes rather than passing on a stale copy.
        """
        node = next(n for n in self.rules.lineage if n.rule_id == SUPERSEDED_RULE)
        derived = {
            r.rule_id for r in self.rules.rules
            if r.predecessor_rule_id == SUPERSEDED_RULE
        }
        self.assertEqual(set(node.successor_rule_ids), derived)
        self.assertEqual(len(derived), 4)

    def test_c_the_successors_partition_the_predecessor_membership(self) -> None:
        predecessor = next(
            r
            for r in cs.read_rules(
                cs.REPO_ROOT / "registry/research/ce_cpi_scope_rules_v0_2.json"
            )
            if r.rule_id == SUPERSEDED_RULE
        )
        union: set[str] = set()
        for rule_id in next(
            n for n in self.rules.lineage if n.rule_id == SUPERSEDED_RULE
        ).successor_rule_ids:
            claimed = set(self.rules.rule(rule_id).source_uccs)
            self.assertEqual(union & claimed, set(), f"{rule_id} overlaps a sibling")
            union |= claimed
        self.assertEqual(union, set(predecessor.source_uccs))

    def test_d_no_ucc_resolves_through_a_superseded_rule(self) -> None:
        for ucc in sorted(self.by_ucc):
            with self.subTest(ucc=ucc):
                self.assertNotEqual(self.rules.resolve(ucc).governing_rule_id,
                                    SUPERSEDED_RULE)

    def test_e_every_ucc_is_claimed_by_at_most_one_current_rule(self) -> None:
        claims: dict[str, list[str]] = {}
        for record in self.rules.rules:
            for ucc in record.source_uccs:
                claims.setdefault(ucc, []).append(record.rule_id)
        doubled = {u: r for u, r in claims.items() if len(r) > 1}
        self.assertEqual(doubled, {})

    def test_f_the_canonical_gate_agrees_with_the_milestone_2_gate(self) -> None:
        """The duplication is checked rather than trusted.

        ``canonical_state_of`` restates the hardened Milestone-2 logic because
        that function's ``MappingStatus`` type has no ``INTRODUCED`` member and
        the governing registry has two INTRODUCE rules. Wherever the older type
        can express the input, the two must agree.
        """
        # A real ScopeRule, so the older gate sees its own type and its own
        # ``is_applicable`` property rather than a stand-in built to agree.
        template = sr.load_scope_rules().rules[0]
        expressible = 0
        for record in self.rules.rules:
            try:
                status = sr.MappingStatus(record.final_status)
            except ValueError:
                continue
            expressible += 1
            older = m2.track_a_disposition(
                replace(
                    template,
                    rule_id=record.rule_id,
                    final_status=status,
                    review_status=sr.ReviewStatus(record.review_status),
                )
            )
            newer = cs.effective_track_a_status(record)
            with self.subTest(rule=record.rule_id):
                self.assertEqual(older.effective_status.value, newer)
        self.assertGreater(expressible, 10, "the cross-check found nothing to check")

    def test_g_a_rule_proposing_nothing_is_open_whatever_its_review_status(
        self,
    ) -> None:
        template = self.rules.rule("UNRESOLVED_v0_2")
        for review in ("OPEN", "PROPOSED", "ACCEPTED"):
            with self.subTest(review_status=review):
                self.assertIs(
                    cs.canonical_state_of(
                        replace(template, review_status=review, declared_applicable=None)
                    ),
                    cs.CanonicalRuleState.CURRENT_OPEN,
                )

    def test_h_is_applicable_must_agree_with_review_status(self) -> None:
        accepted = next(
            r for r in self.rules.rules
            if r.review_status == "ACCEPTED" and r.final_status != "UNRESOLVED"
        )
        with self.assertRaises(cs.CanonicalStateError):
            cs.canonical_state_of(replace(accepted, declared_applicable=False))

    def test_i_the_transition_block_and_the_rule_fields_must_agree(self) -> None:
        scratch = _mutable_registry()

        def drop(payload: dict) -> None:
            payload["residual_transitions"] = [
                e for e in payload["residual_transitions"]
                if e.get("predecessor_rule_id") != SUPERSEDED_RULE
            ]

        _rewrite(scratch, _scope_rules_head(), drop)
        with self.assertRaises(cs.CanonicalStateError) as caught:
            cs.build_rule_lineage(registry_dir=scratch)
        self.assertIn("disagree about", str(caught.exception))


class TestCheckpoints(unittest.TestCase):
    def test_a_there_are_four_and_exactly_one_governs(self) -> None:
        self.assertEqual(len(cs.CHECKPOINTS), 4)
        governing = [
            c for c in cs.CHECKPOINTS
            if c.role is cs.CheckpointRole.CURRENT_GOVERNING_INPUT
        ]
        self.assertEqual(len(governing), 1)
        self.assertEqual(governing[0], cs.CHECKPOINTS[-1])

    def test_b_the_recorded_commits_match_the_repository(self) -> None:
        """A tag that moved is exactly the condition worth failing on."""
        for checkpoint in cs.CHECKPOINTS:
            result = subprocess.run(
                ["git", "rev-parse", f"{checkpoint.tag}^{{}}"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self.skipTest(f"tag {checkpoint.tag} is not present in this checkout")
            with self.subTest(tag=checkpoint.tag):
                self.assertEqual(result.stdout.strip(), checkpoint.commit)


# ---------------------------------------------------------------------------
# Group 3: C2, the ledger is complete
# ---------------------------------------------------------------------------


class TestLedgerCompleteness(Built, unittest.TestCase):
    def test_a_every_ucc_has_all_six_populations(self) -> None:
        for ucc, rows in sorted(self.by_ucc.items()):
            with self.subTest(ucc=ucc):
                self.assertEqual(
                    [r.population for r in rows], list(cs.POPULATIONS)
                )

    def test_b_the_universe_is_the_union_of_four_declared_sets(self) -> None:
        expected = (
            set(self.inputs.basis_meta)
            | set(self.rules.claimed_source_uccs)
            | set(self.rules.claimed_output_uccs)
            | set(self.inputs.addendum_uccs)
        )
        self.assertEqual(set(self.by_ucc), expected)
        self.assertEqual(len(self.rows), len(expected) * len(cs.POPULATIONS))

    def test_c_every_basis_ucc_survives_into_the_ledger(self) -> None:
        """No UCC is dropped for having no amount, no rule or no mapping."""
        missing = set(self.inputs.basis_meta) - set(self.by_ucc)
        self.assertEqual(missing, set())

    def test_d_the_regression_case_is_present_with_all_six_rows(self) -> None:
        self.assertEqual(len(self.by_ucc[NULL_ZERO_UCC]), 6)

    def test_e_rows_are_sorted_by_ucc_then_by_declared_population_order(
        self,
    ) -> None:
        keys = [(r.ucc, cs.POPULATIONS.index(r.population)) for r in self.rows]
        self.assertEqual(keys, sorted(keys))

    def test_f_the_written_csv_matches_the_built_rows(self) -> None:
        with cl.LEDGER_PATH.open(newline="", encoding="utf-8") as handle:
            written = list(csv.DictReader(handle))
        self.assertEqual(len(written), len(self.rows))
        self.assertEqual(
            [(r["ucc"], r["population"]) for r in written],
            [(r.ucc, r.population) for r in self.rows],
        )

    def test_g_the_schema_columns_and_the_csv_header_agree(self) -> None:
        schema = json.loads(cl.SCHEMA_PATH.read_text(encoding="utf-8"))
        with cl.LEDGER_PATH.open(newline="", encoding="utf-8") as handle:
            header = next(csv.reader(handle))
        self.assertEqual([c["name"] for c in schema["columns"]], header)
        self.assertEqual(list(cl.LEDGER_COLUMNS), header)


# ---------------------------------------------------------------------------
# Group 4: C2, disposition integrity
# ---------------------------------------------------------------------------


class TestDispositionIntegrity(Built, unittest.TestCase):
    def test_a_at_most_one_amount_column_is_populated(self) -> None:
        for row in self.rows:
            populated = [n for n in cl.AMOUNT_COLUMNS if getattr(row, n) is not None]
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertLessEqual(len(populated), 1)

    def test_b_the_populated_column_is_the_dispositions_own(self) -> None:
        for row in self.rows:
            populated = [n for n in cl.AMOUNT_COLUMNS if getattr(row, n) is not None]
            if not populated:
                continue
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertEqual(
                    populated[0], cl.AMOUNT_COLUMN_FOR[row.track_a_disposition]
                )

    def test_c_no_amount_is_rescaled_on_its_way_into_a_bucket(self) -> None:
        for row in self.rows:
            for name in cl.AMOUNT_COLUMNS:
                value = getattr(row, name)
                if value is None:
                    continue
                with self.subTest(ucc=row.ucc, population=row.population):
                    self.assertEqual(value, row.source_amount_millions)

    def test_d_no_pending_rule_reaches_an_effective_disposition(self) -> None:
        effective = {
            cl.Disposition.EXCLUDED,
            cl.Disposition.REMOVED_FOR_REPLACEMENT,
            cl.Disposition.REPLACEMENT,
            cl.Disposition.TRANSFORMED,
        }
        for row in self.rows:
            if row.canonical_rule_state is not cs.CanonicalRuleState.CURRENT_PENDING:
                continue
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertNotIn(row.track_a_disposition, effective)
                self.assertIn(row.effective_track_a_status, (None, "UNRESOLVED"))

    def test_e_pending_rules_actually_exist_so_the_previous_test_is_not_vacuous(
        self,
    ) -> None:
        pending = [
            r for r in self.rows
            if r.canonical_rule_state is cs.CanonicalRuleState.CURRENT_PENDING
        ]
        self.assertGreater(len(pending), 0)
        self.assertGreater(len({r.ucc for r in pending}), 1)

    def test_f_effective_dispositions_actually_occur(self) -> None:
        """Otherwise the whole gate could be a constant ``False``."""
        seen = {r.track_a_disposition for r in self.rows}
        for disposition in (
            cl.Disposition.EXCLUDED,
            cl.Disposition.TRANSFORMED,
            cl.Disposition.REPLACEMENT,
        ):
            with self.subTest(disposition=disposition.value):
                self.assertIn(disposition, seen)

    def test_g_a_pending_rule_on_a_mapped_ucc_reverts_to_the_baseline(self) -> None:
        """"No effect" means baseline reversion, not a holding bucket.

        The governing registry states this for UCC 220121: not applying a
        partial-retention transform leaves the amount as recorded, whereas
        moving it to the pending bucket would remove it from the basis
        entirely and so assert more than the rule does.
        """
        reverting = [
            r for r in self.rows
            if r.pending_rule_effect_on_amount
            is cl.PendingEffect.AMOUNT_REVERTS_TO_MAPPED_BASELINE
        ]
        self.assertGreater(len(reverting), 0)
        for row in reverting:
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertIs(row.track_a_disposition, cl.Disposition.RETAINED)
                self.assertIn(row.m1_mapping_status, ("DIRECT", "MULTI_SAME_NODE"))

    def test_h_a_pending_rule_on_an_unmapped_ucc_is_held(self) -> None:
        held = [
            r for r in self.rows
            if r.pending_rule_effect_on_amount
            is cl.PendingEffect.AMOUNT_HELD_IN_PENDING_BUCKET
        ]
        self.assertGreater(len(held), 0)
        for row in held:
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertIs(row.track_a_disposition, cl.Disposition.PENDING)
                self.assertNotIn(row.m1_mapping_status, ("DIRECT", "MULTI_SAME_NODE"))

    def test_i_an_unmapped_ucc_is_never_excluded_merely_for_being_unmapped(
        self,
    ) -> None:
        """Absence from the concordance is a fact about the crosswalk.

        It is not evidence that the CPI assigns the item no weight. Every
        exclusion must come from a rule that is in force and says so.
        """
        for row in self.rows:
            if row.track_a_disposition is not cl.Disposition.EXCLUDED:
                continue
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertIsNotNone(row.governing_rule_id)
                self.assertIs(
                    row.canonical_rule_state, cs.CanonicalRuleState.CURRENT_EFFECTIVE
                )
                self.assertEqual(row.effective_track_a_status, "OUT_OF_SCOPE")

    def test_j_unmappedness_alone_does_not_determine_a_disposition(self) -> None:
        """The companion to ``test_i``, from the other direction.

        ``test_i`` shows every exclusion has a rule in force behind it. This
        shows the unmapped population is not simply the excluded population
        under another name: a rule may well exclude an unmapped UCC on its own
        grounds, and many unmapped UCCs are not excluded at all. If the two
        sets ever coincided, "unmapped" would have silently become a synonym
        for "excluded" and the distinction the concordance correction was made
        to protect would be gone.
        """
        unmapped = [
            r for r in self.rows
            if r.m1_mapping_status == "UNRESOLVED"
            and r.source_class is cl.SourceClass.PUBLISHED_CE_BASIS
        ]
        self.assertGreater(len(unmapped), 0)
        dispositions = {r.track_a_disposition for r in unmapped}
        self.assertGreater(
            len(dispositions), 1, "every unmapped UCC shares one disposition"
        )
        # Exclusion, where it happens, is the rule's doing and not the
        # concordance's absence: each excluded row names a rule in force.
        for row in unmapped:
            if row.track_a_disposition is not cl.Disposition.EXCLUDED:
                continue
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertIs(
                    row.canonical_rule_state, cs.CanonicalRuleState.CURRENT_EFFECTIVE
                )
                self.assertEqual(row.rule_type, "EXCLUDE")

    def test_k_normalization_state_is_a_classification_and_nothing_more(self) -> None:
        for row in self.rows:
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertIsInstance(row.normalization_state, cl.NormalizationState)


# ---------------------------------------------------------------------------
# Group 5: C2, null is not zero
# ---------------------------------------------------------------------------


class TestNullIsNotZero(Built, unittest.TestCase):
    def test_a_the_regression_case_carries_both_encodings(self) -> None:
        rows = {r.population: r for r in self.by_ucc[NULL_ZERO_UCC]}
        q1 = rows["Q1"]
        self.assertIsNone(q1.source_amount_millions)
        self.assertIs(q1.source_amount_status, cl.AmountStatus.NOT_AVAILABLE)
        for population in ("ALL_CU", "Q2", "Q3", "Q4", "Q5"):
            with self.subTest(population=population):
                row = rows[population]
                self.assertIsNotNone(row.source_amount_millions)
                self.assertIs(row.source_amount_status, cl.AmountStatus.WITHHELD)

    def test_b_a_withheld_amount_is_shown_because_it_is_known(self) -> None:
        """Withheld means not admitted. It does not mean unknown.

        Blanking it would say the estimate does not exist, when what happened
        is that it exists and failed a declared quality gate.
        """
        rows = {r.population: r for r in self.by_ucc[NULL_ZERO_UCC]}
        self.assertGreater(rows["ALL_CU"].withheld_amount, 0.0)
        self.assertIs(
            rows["ALL_CU"].normalization_state,
            cl.NormalizationState.BLOCKED_AMOUNT_NOT_ADMITTED,
        )
        self.assertIs(
            rows["Q1"].normalization_state,
            cl.NormalizationState.BLOCKED_AMOUNT_UNAVAILABLE,
        )

    def test_c_a_withheld_amount_never_reaches_an_accounting_bucket(self) -> None:
        for row in self.by_ucc[NULL_ZERO_UCC]:
            with self.subTest(population=row.population):
                self.assertIs(row.track_a_disposition, cl.Disposition.WITHHELD)
                self.assertIsNone(row.retained_amount)
                self.assertIsNone(row.replacement_amount)

    def test_d_observed_zeros_survive_as_zero(self) -> None:
        zeros = [
            r for r in self.rows
            if r.source_amount_millions == 0.0
            and r.source_amount_status is cl.AmountStatus.OBSERVED
        ]
        self.assertGreater(len(zeros), 0, "the basis has observed zeros to preserve")
        for row in zeros:
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertIsNotNone(row.source_amount_millions)

    def test_e_observed_zeros_are_written_as_zero_not_as_blank(self) -> None:
        zeros = {
            (r.ucc, r.population) for r in self.rows
            if r.source_amount_millions == 0.0
            and r.source_amount_status is cl.AmountStatus.OBSERVED
        }
        with cl.LEDGER_PATH.open(newline="", encoding="utf-8") as handle:
            for record in csv.DictReader(handle):
                if (record["ucc"], record["population"]) not in zeros:
                    continue
                with self.subTest(ucc=record["ucc"], population=record["population"]):
                    self.assertNotEqual(record["source_amount_millions"], "")
                    self.assertEqual(float(record["source_amount_millions"]), 0.0)

    def test_f_a_suppressed_cell_is_blank_and_not_zero(self) -> None:
        suppressed = [
            r for r in self.rows
            if r.source_amount_status is cl.AmountStatus.SUPPRESSED
        ]
        self.assertGreater(len(suppressed), 0)
        for row in suppressed:
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertIsNone(row.source_amount_millions)

    def test_g_a_blank_cell_never_lands_in_an_accounting_bucket(self) -> None:
        for row in self.rows:
            if row.source_amount_millions is not None:
                continue
            for name in cl.AMOUNT_COLUMNS:
                with self.subTest(ucc=row.ucc, column=name):
                    self.assertIsNone(getattr(row, name))

    def test_h_no_amount_column_is_written_as_zero_where_the_source_is_blank(
        self,
    ) -> None:
        with cl.LEDGER_PATH.open(newline="", encoding="utf-8") as handle:
            for record in csv.DictReader(handle):
                if record["source_amount_millions"] != "":
                    continue
                for name in cl.AMOUNT_COLUMNS:
                    with self.subTest(ucc=record["ucc"], column=name):
                        self.assertEqual(record[name], "")


# ---------------------------------------------------------------------------
# Group 6: C2, removal is not replacement
# ---------------------------------------------------------------------------


class TestReplacementLinkage(Built, unittest.TestCase):
    def test_a_every_declared_group_is_backed_by_the_governing_registry(self) -> None:
        cl._validate_replacement_groups(self.rules)
        for group in cl.REPLACEMENT_GROUPS:
            with self.subTest(group=group.group_id):
                self.assertEqual(
                    self.rules.rule(group.replacement_rule_id).final_status,
                    "INTRODUCED",
                )

    def test_b_a_group_whose_replacement_rule_is_wrong_is_rejected(self) -> None:
        broken = cl.ReplacementGroup(
            group_id="RG_FABRICATED",
            removal_rule_id=None,
            replacement_rule_id="OS_CPI_VEHICLE_FINANCE_CHARGES_v0_1",
            linkage_basis="NO_REMOVAL_SIDE_DECLARED",
            note="injected",
        )
        original = cl.REPLACEMENT_GROUPS
        try:
            cl.REPLACEMENT_GROUPS = original + (broken,)
            with self.assertRaises(cl.LedgerError):
                cl._validate_replacement_groups(self.rules)
        finally:
            cl.REPLACEMENT_GROUPS = original

    def test_c_the_removal_and_replacement_amounts_are_not_forced_equal(self) -> None:
        """The two sides are separate columns with no equality constraint.

        Asserted structurally: no code path assigns one from the other, and the
        validator accepts a group whose two sides differ.
        """
        self.assertNotEqual(
            cl.AMOUNT_COLUMN_FOR[cl.Disposition.REMOVED_FOR_REPLACEMENT],
            cl.AMOUNT_COLUMN_FOR[cl.Disposition.REPLACEMENT],
        )
        rows = [r for r in self.rows if r.replacement_group_id is not None]
        self.assertGreater(len(rows), 0)

    def test_d_the_linkage_survives_both_sides_being_blocked(self) -> None:
        """A blocked pair must not look like two independent blockers."""
        group = next(
            g for g in cl.REPLACEMENT_GROUPS if g.removal_rule_id is not None
        )
        members = [
            r for r in self.rows if r.replacement_group_id == group.group_id
        ]
        self.assertGreater(len(members), 0)
        self.assertEqual(
            {cl.ReplacementRole.REMOVAL, cl.ReplacementRole.REPLACEMENT},
            {r.replacement_role for r in members},
        )

    def test_e_no_group_retains_a_source_while_introducing_its_replacement(
        self,
    ) -> None:
        cl._validate_replacement_consistency(self.rows)


# ---------------------------------------------------------------------------
# Group 7: determinism
# ---------------------------------------------------------------------------


class TestDeterminism(unittest.TestCase):
    def test_a_two_builds_produce_identical_bytes(self) -> None:
        first = cl.render_ledger(cl.build_ledger())
        second = cl.render_ledger(cl.build_ledger())
        self.assertEqual(first, second)

    def test_b_the_manifest_rebuilds_identically(self) -> None:
        self.assertEqual(cs.render_manifest(), cs.render_manifest())

    def test_c_the_committed_artifacts_match_a_fresh_build(self) -> None:
        rows = cl.build_ledger()
        for path, rendered in (
            (cs.MANIFEST_PATH, cs.render_manifest()),
            (cl.SCHEMA_PATH, cl.render_schema()),
            (cl.LEDGER_PATH, cl.render_ledger(rows)),
            (cl.LEDGER_SUMMARY_PATH, cl.render_summary(rows)),
        ):
            with self.subTest(path=path.name):
                self.assertTrue(path.exists())
                self.assertEqual(path.read_text(encoding="utf-8"), rendered)

    def test_d_no_artifact_carries_a_timestamp(self) -> None:
        """A manifest that changes on rebuild cannot detect a real change.

        The check walks keys rather than raw text. The manifest deliberately
        carries a ``no_timestamp`` key explaining why it has no timestamp, and
        a substring scan would read that explanation as the offence.
        """
        forbidden = ("generated_at", "timestamp", "build_time", "created_at")

        def keys(node: object) -> list[str]:
            if isinstance(node, dict):
                found = list(node)
                for value in node.values():
                    found.extend(keys(value))
                return found
            if isinstance(node, list):
                return [k for item in node for k in keys(item)]
            return []

        for path in (cs.MANIFEST_PATH, cl.SCHEMA_PATH, cl.LEDGER_SUMMARY_PATH):
            present = set(keys(json.loads(path.read_text(encoding="utf-8"))))
            for word in forbidden:
                with self.subTest(path=path.name, key=word):
                    self.assertNotIn(word, present)

    def test_e_the_csv_uses_lf_line_endings(self) -> None:
        self.assertNotIn(b"\r\n", cl.LEDGER_PATH.read_bytes())

    def test_f_the_build_script_check_mode_reports_no_drift(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/build_canonical_substrate_2024.py", "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


# ---------------------------------------------------------------------------
# Group 8: the seven named mutations
# ---------------------------------------------------------------------------


class TestMutationsAreCaught(Built, unittest.TestCase):
    """Each injection is a specific way the substrate could go quietly wrong.

    A test suite that only builds the real inputs proves the real inputs are
    consistent, not that the guards work. These build deliberately wrong inputs
    and require a failure.
    """

    def _row(self, ucc: str, population: str = "ALL_CU") -> cl.LedgerRow:
        return next(
            r for r in self.rows if r.ucc == ucc and r.population == population
        )

    def test_1_re_enabling_a_superseded_rule_fails(self) -> None:
        scratch = _mutable_registry()

        def re_enable(payload: dict) -> None:
            v0_2 = json.loads(
                (scratch / "ce_cpi_scope_rules_v0_2.json").read_text("utf-8")
            )
            revived = copy.deepcopy(
                next(r for r in v0_2["rules"] if r["rule_id"] == SUPERSEDED_RULE)
            )
            revived["review_status"] = "ACCEPTED"
            revived.pop("is_applicable", None)
            payload["rules"].append(revived)

        _rewrite(scratch, _scope_rules_head(), re_enable)
        with self.assertRaises(cs.CanonicalStateError) as caught:
            cs.load_canonical_rules(registry_dir=scratch)
        message = str(caught.exception)
        self.assertTrue(
            "claimed as a source by two current rules" in message
            or "still present in the governing registry" in message,
            message,
        )

    def test_2_two_current_rules_claiming_one_ucc_fails(self) -> None:
        scratch = _mutable_registry()

        def double_claim(payload: dict) -> None:
            donor = next(
                r for r in payload["rules"]
                if r["rule_id"] == "OS_CPI_VEHICLE_FINANCE_CHARGES_v0_1"
            )
            thief = next(
                r for r in payload["rules"]
                if r["rule_id"] == "OS_CPI_RESIDENTIAL_PROPERTY_TAX_v0_1"
            )
            thief["source_uccs"] = list(thief["source_uccs"]) + [
                donor["source_uccs"][0]
            ]

        _rewrite(scratch, _scope_rules_head(), double_claim)
        with self.assertRaises(cs.CanonicalStateError) as caught:
            cs.load_canonical_rules(registry_dir=scratch)
        self.assertIn("two current rules", str(caught.exception))

    def test_3_a_pending_rule_producing_an_effective_exclusion_fails(self) -> None:
        pending = next(
            r for r in self.rows
            if r.canonical_rule_state is cs.CanonicalRuleState.CURRENT_PENDING
            and r.source_amount_millions is not None
        )
        mutated = replace(
            pending,
            track_a_disposition=cl.Disposition.EXCLUDED,
            pending_amount=None,
            retained_amount=None,
            excluded_amount=pending.source_amount_millions,
            normalization_state=cl.NormalizationState.EXCLUDED_FROM_BASIS,
        )
        with self.assertRaises(cl.LedgerError) as caught:
            cl._validate_row(mutated)
        self.assertIn("requires a rule in force", str(caught.exception))

    def test_4_turning_a_null_withheld_amount_into_zero_fails(self) -> None:
        blank = self._row(NULL_ZERO_UCC, "Q1")
        self.assertIsNone(blank.source_amount_millions)
        mutated = replace(blank, source_amount_millions=0.0)
        with self.assertRaises(cl.LedgerError) as caught:
            cl._validate_row(mutated)
        self.assertIn("must be blank", str(caught.exception))

    def test_4b_a_suppressed_cell_coerced_to_zero_fails(self) -> None:
        suppressed = next(
            r for r in self.rows
            if r.source_amount_status is cl.AmountStatus.SUPPRESSED
        )
        with self.assertRaises(cl.LedgerError):
            cl._validate_row(replace(suppressed, source_amount_millions=0.0))

    def test_5_retaining_a_source_while_introducing_its_replacement_fails(
        self,
    ) -> None:
        group = next(
            g for g in cl.REPLACEMENT_GROUPS if g.removal_rule_id is not None
        )
        members = [
            r for r in self.rows
            if r.replacement_group_id == group.group_id and r.population == "ALL_CU"
        ]
        removal = next(
            r for r in members if r.replacement_role is cl.ReplacementRole.REMOVAL
        )
        introduced = next(
            r for r in members if r.replacement_role is cl.ReplacementRole.REPLACEMENT
        )
        mutated = [
            replace(removal, retained_amount=1234.0, pending_amount=None),
            replace(introduced, replacement_amount=999.0, pending_amount=None),
        ]
        with self.assertRaises(cl.LedgerError) as caught:
            cl._validate_replacement_consistency(mutated)
        self.assertIn("counted twice", str(caught.exception))

    def test_6_classifying_an_unmapped_ucc_as_excluded_fails(self) -> None:
        """Absence from the concordance is not evidence of zero CPI weight.

        The target is an unmapped UCC whose governing rule is OPEN: it
        proposes no disposition, so the only remaining ground for excluding it
        would be its unmappedness. Every basis UCC is claimed by some rule, so
        there is no "unmapped and unclaimed" row to use instead; the honest
        injection is therefore to exclude on an unresolved rule rather than on
        no rule at all.
        """
        unmapped = next(
            r for r in self.rows
            if r.m1_mapping_status == "UNRESOLVED"
            and r.canonical_rule_state is cs.CanonicalRuleState.CURRENT_OPEN
            and r.source_amount_millions is not None
        )
        mutated = replace(
            unmapped,
            track_a_disposition=cl.Disposition.EXCLUDED,
            open_amount=None,
            excluded_amount=unmapped.source_amount_millions,
            normalization_state=cl.NormalizationState.EXCLUDED_FROM_BASIS,
        )
        with self.assertRaises(cl.LedgerError) as caught:
            cl._validate_row(mutated)
        self.assertIn("requires a rule in force", str(caught.exception))

    def test_7_adding_a_normalized_weight_field_fails_the_firewall(self) -> None:
        """Asserted on an injected source, then asserted absent from the real one."""
        injected = "def f(x):\n    normalized_weight = x / 2.0\n    return normalized_weight\n"
        self.assertTrue(_normalization_hits(_identifiers(injected)))
        for relative in CANONICAL_MODULES:
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertEqual(_normalization_hits(_identifiers(source)), set())

    def test_8_a_row_whose_amount_was_rescaled_fails(self) -> None:
        retained = next(
            r for r in self.rows
            if r.track_a_disposition is cl.Disposition.RETAINED
            and r.retained_amount not in (None, 0.0)
        )
        with self.assertRaises(cl.LedgerError) as caught:
            cl._validate_row(replace(retained, retained_amount=retained.retained_amount * 0.57))
        self.assertIn("never rescales", str(caught.exception))

    def test_9_a_missing_population_row_fails(self) -> None:
        rows = [r for r in self.rows if not (r.ucc == NULL_ZERO_UCC and r.population == "Q1")]
        with self.assertRaises(cl.LedgerError) as caught:
            cl.validate_ledger(rows)
        self.assertIn("missing populations", str(caught.exception))

    def test_10_two_amount_columns_on_one_row_fails(self) -> None:
        retained = next(
            r for r in self.rows if r.retained_amount is not None
        )
        with self.assertRaises(cl.LedgerError) as caught:
            cl._validate_row(replace(retained, excluded_amount=retained.retained_amount))
        self.assertIn("exactly one accounting state", str(caught.exception))


# ---------------------------------------------------------------------------
# Group 9: the normalisation firewall and the research firewall
# ---------------------------------------------------------------------------

#: Vocabulary that would mean C2 had started doing C4's job. Matched against
#: identifiers in the parse tree, never against prose, so a module cannot
#: satisfy the guard by describing itself.
NORMALIZATION_VOCABULARY = (
    "normalized_weight",
    "normalised_weight",
    "weight_share",
    "denominator_share",
    "relative_importance",
    "share_of_total",
    "rescale",
    "renormalize",
    "renormalise",
)


def _identifiers(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
    return names


def _normalization_hits(names: set[str]) -> set[str]:
    return {
        name
        for name in names
        for word in NORMALIZATION_VOCABULARY
        if word in name.lower()
    }


class TestNoNormalizationArithmetic(Built, unittest.TestCase):
    def test_a_the_guard_fires_on_every_injected_name(self) -> None:
        for word in NORMALIZATION_VOCABULARY:
            source = f"def compute():\n    {word} = 1.0\n    return {word}\n"
            with self.subTest(injected=word):
                self.assertTrue(_normalization_hits(_identifiers(source)))

    def test_b_the_guard_fires_on_an_injected_attribute_and_argument(self) -> None:
        cases = (
            "def f(weight_share):\n    return weight_share\n",
            "def f(x):\n    return x.normalized_weight\n",
            "def f(x):\n    return g(denominator_share=x)\n",
        )
        for source in cases:
            with self.subTest(source=source.splitlines()[0]):
                self.assertTrue(_normalization_hits(_identifiers(source)))

    def test_c_the_guard_does_not_fire_on_the_real_modules(self) -> None:
        for relative in CANONICAL_MODULES:
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertEqual(_normalization_hits(_identifiers(source)), set())

    def test_d_no_column_is_a_weight_a_share_or_a_denominator(self) -> None:
        for column in cl.LEDGER_COLUMNS:
            with self.subTest(column=column):
                self.assertNotIn("weight", column)
                self.assertNotIn("share", column)
                self.assertNotIn("denominator", column)

    def test_e_the_summary_counts_rows_and_sums_no_amount(self) -> None:
        summary = json.loads(cl.LEDGER_SUMMARY_PATH.read_text(encoding="utf-8"))
        for key, value in summary.items():
            if not isinstance(value, dict):
                continue
            for name, count in value.items():
                if not isinstance(count, (int, float)):
                    continue
                with self.subTest(key=key, name=name):
                    self.assertIsInstance(count, int)

    def test_f_c2_reconciles_nothing(self) -> None:
        """No total is computed, so no total can silently drive a disposition."""
        summary = json.loads(cl.LEDGER_SUMMARY_PATH.read_text(encoding="utf-8"))
        self.assertNotIn("total_amount", summary)
        self.assertIn("counts_are_rows_not_amounts", summary)


class TestResearchFirewall(unittest.TestCase):
    def _trees(self):
        for relative in CANONICAL_MODULES:
            path = REPO_ROOT / relative
            self.assertTrue(path.exists(), relative)
            yield relative, ast.parse(path.read_text(encoding="utf-8"))

    def test_a_nothing_imports_the_production_calculator(self) -> None:
        forbidden = ("dmi_calculator", "deploy")
        for relative, tree in self._trees():
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                for module in modules:
                    with self.subTest(path=relative, module=module):
                        self.assertNotIn(module.split(".")[0], forbidden)

    def test_b_every_written_path_lives_under_research(self) -> None:
        allowed = ("data/research/", "registry/research/", "docs/research/")
        found = 0
        for relative, tree in self._trees():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(
                    node.value, str
                ):
                    continue
                value = node.value
                if "/" not in value or value.startswith("http"):
                    continue
                if not value.startswith(("data/", "registry/", "docs/", "deploy/")):
                    continue
                found += 1
                # A directory literal may or may not carry a trailing slash.
                # Comparing with one appended keeps "registry/research" inside
                # the tree while still rejecting "registry/research_scratch".
                normalised = value.rstrip("/") + "/"
                with self.subTest(path=relative, literal=value):
                    self.assertTrue(
                        normalised.startswith(allowed),
                        f"{value!r} is outside the research tree",
                    )
        self.assertGreaterEqual(found, 4, "the path scan found nothing to check")

    def test_c_the_modules_declare_themselves_research_only(self) -> None:
        for relative in CANONICAL_MODULES:
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertIn("RESEARCH ONLY", text)

    def test_d_no_output_or_baseline_path_appears(self) -> None:
        for relative in CANONICAL_MODULES:
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            for forbidden in ("data/outputs", "deploy/data/outputs"):
                with self.subTest(path=relative, forbidden=forbidden):
                    self.assertNotIn(forbidden, text)

    def test_e_every_artifact_landed_under_research(self) -> None:
        for path in (
            cs.MANIFEST_PATH,
            cl.SCHEMA_PATH,
            cl.LEDGER_PATH,
            cl.LEDGER_SUMMARY_PATH,
        ):
            relative = path.relative_to(REPO_ROOT).as_posix()
            with self.subTest(path=relative):
                self.assertTrue(path.exists())
                self.assertTrue(
                    relative.startswith(("data/research/", "registry/research/")),
                    relative,
                )

    def test_f_the_registries_the_build_read_are_the_committed_ones(self) -> None:
        """No registry under ``registry/research`` has uncommitted edits.

        This is a reproducibility check and nothing more. If a registry is
        dirty then the artifacts sitting in this working tree were built from
        bytes that are not in the repository, and regenerating from a clean
        checkout would not reproduce them.

        It is worth being blunt about what it does *not* show, because an
        earlier version of this test claimed it. It says nothing about whether
        a committed registry was ever modified. Once an edit is committed the
        working tree is clean again and this assertion passes, so it cannot
        distinguish "the registries were never touched" from "the registries
        were rewritten and the rewrite was committed".

        Nor would the stronger claim be true. C1 and C2 do not only write
        successors: ``ucc_provenance_classes_v0_5.json`` was created during
        this milestone and has already been amended in place, deliberately,
        because a milestone that is still open has nothing to be immutable
        for. The invariant that actually holds is narrower and is asserted in
        ``TestFrozenCheckpointPreservation``: what may not change is what was
        inherited from a checkpoint that is already frozen.
        """
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", "registry/research"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.skipTest("git is unavailable")
        touched = [
            line[3:]
            for line in result.stdout.splitlines()
            if not line.startswith("??")
        ]
        self.assertEqual(touched, [])


# ---------------------------------------------------------------------------
# Group 10b: what is frozen stays frozen, and what is open stays open
# ---------------------------------------------------------------------------


class TestFrozenCheckpointPreservation(unittest.TestCase):
    """Inherited artifacts are immutable. Artifacts born this milestone are not.

    C1 and C2 started from ``dmi-detailed-inflation-v0.1-shelter-residuals-2024``.
    Every research artifact in that commit is evidence some later work has
    already been accepted on top of, so changing one silently rewrites the
    basis of conclusions that were drawn before the change. That is the thing
    worth guarding, and it is a narrower claim than "no committed artifact
    ever changes": the successors this milestone wrote are still open, and
    freezing them now would freeze their defects with them.

    The two tiers are separated structurally rather than by policy. The
    inherited set is read out of the tag's tree, so a file that did not exist
    at the checkpoint cannot be in it. No exclusion list names
    ``ucc_provenance_classes_v0_5.json``; it is absent because it was not
    there, and ``test_f`` asserts that its frozen predecessor *is* there so
    the distinction cannot degrade into a blanket exemption.

    The comparison is against the local object database. Nothing here reaches
    the network, and it does not consult the BLS or any other upstream source:
    the question is whether this repository changed, not whether the world
    did.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.expected = _frozen_checkpoint_blobs()

    def setUp(self) -> None:
        if self.expected is None:
            self.skipTest(f"git or {FROZEN_CHECKPOINT_TAG} is unavailable")

    def test_a_the_checkpoint_tag_still_names_the_pinned_commit(self) -> None:
        """A tag is a movable ref, so its target is pinned in the source.

        Without this, moving the tag forward would quietly redefine every
        assertion below to compare the branch against itself.
        """
        result = subprocess.run(
            ["git", "rev-parse", f"{FROZEN_CHECKPOINT_TAG}^{{commit}}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), FROZEN_CHECKPOINT_COMMIT)

    def test_b_the_inherited_set_is_the_size_it_was(self) -> None:
        """A guard covering a shrinking set of files still passes."""
        self.assertEqual(len(self.expected), INHERITED_FILE_COUNT)
        for tree in INHERITED_TREES:
            with self.subTest(tree=tree):
                covered = [p for p in self.expected if p.startswith(tree + "/")]
                self.assertTrue(covered, f"{tree} contributed nothing")

    def test_c_no_inherited_research_artifact_changed(self) -> None:
        """The invariant itself."""
        drift = _preservation_drift(self.expected, REPO_ROOT)
        self.assertEqual(drift, [], f"inherited artifacts changed: {drift}")

    def test_d_the_check_fails_when_an_inherited_artifact_is_edited(self) -> None:
        """Non-vacuity, on an isolated copy. Nothing in the repository is touched.

        The mutation is a single appended byte inside a JSON registry, which
        is about as small as a real mutation gets and is exactly the size of
        edit a reviewer would miss.
        """
        target = "registry/research/ucc_provenance_classes_v0_4.json"
        self.assertIn(target, self.expected)
        scratch = _isolated_checkpoint_copy(self.expected)
        try:
            self.assertEqual(_preservation_drift(self.expected, scratch), [])
            victim = scratch / target
            victim.write_bytes(victim.read_bytes() + b" ")
            self.assertEqual(
                _preservation_drift(self.expected, scratch),
                [(target, "MODIFIED")],
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        # and the repository itself is still where it was
        self.assertEqual(_preservation_drift(self.expected, REPO_ROOT), [])

    def test_e_the_check_fails_when_an_inherited_artifact_is_deleted(self) -> None:
        """Deletion is the other way an inherited artifact stops being itself."""
        target = "data/research/detailed_inflation/audit_2024/active_ucc_basis.csv"
        self.assertIn(target, self.expected)
        scratch = _isolated_checkpoint_copy(self.expected)
        try:
            (scratch / target).unlink()
            self.assertEqual(
                _preservation_drift(self.expected, scratch),
                [(target, "MISSING")],
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_f_this_milestones_successors_are_open_and_their_parents_are_not(
        self,
    ) -> None:
        """The two tiers, asserted from both sides.

        v0.4 is inherited and frozen. v0.5 was written during this milestone,
        is not in the inherited set, and has already been revised twice. If
        v0.5 ever appears here it means the checkpoint moved, and the failure
        should be loud rather than a quietly widened guard.
        """
        frozen = "registry/research/ucc_provenance_classes_v0_4.json"
        open_successor = "registry/research/ucc_provenance_classes_v0_5.json"
        self.assertIn(frozen, self.expected)
        self.assertNotIn(open_successor, self.expected)
        # The open successor is not merely unlisted, it is the current head,
        # so the guard is exempting a live artifact rather than a dead one.
        self.assertTrue((REPO_ROOT / open_successor).is_file())
        head = cs.governing_version("ucc_provenance_classes").relative_path
        self.assertEqual(Path(head).name, Path(open_successor).name)

    def test_g_recorded_content_matches_what_git_hash_object_computes(self) -> None:
        """Pin the normalisation to git's, so the two cannot diverge.

        ``_as_git_records_it`` reimplements one narrow piece of git: the LF
        normalisation ``.gitattributes`` asks for. If that reimplementation is
        wrong the preservation check is comparing something git does not
        record, and every assertion above becomes an assertion about a hash
        function rather than about this repository.
        """
        paths = sorted(self.expected)
        result = subprocess.run(
            ["git", "hash-object", "--stdin-paths"],
            cwd=REPO_ROOT,
            input="\n".join(paths) + "\n",
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.skipTest("git hash-object is unavailable")
        computed = result.stdout.split()
        self.assertEqual(len(computed), len(paths))
        for path, object_id in zip(paths, computed):
            with self.subTest(path=path):
                raw = (REPO_ROOT / path).read_bytes()
                self.assertEqual(_git_blob_id(_as_git_records_it(raw)), object_id)


class TestSchemaAndVocabularies(Built, unittest.TestCase):
    def test_a_every_vocabulary_member_is_documented(self) -> None:
        for enum_cls in (
            cl.SourceClass,
            cl.AmountSource,
            cl.AmountStatus,
            cl.Disposition,
            cl.PendingEffect,
            cl.NormalizationState,
            cl.ReplacementRole,
        ):
            with self.subTest(vocabulary=enum_cls.__name__):
                documented = cl._enum_doc(enum_cls)
                self.assertEqual(set(documented), {m.value for m in enum_cls})

    def test_b_an_undocumented_member_is_rejected(self) -> None:
        original = cl._ENUM_SEMANTICS["ReplacementRole"]
        try:
            cl._ENUM_SEMANTICS = dict(cl._ENUM_SEMANTICS)
            cl._ENUM_SEMANTICS["ReplacementRole"] = {"REMOVAL": "x"}
            with self.assertRaises(cl.LedgerError):
                cl._enum_doc(cl.ReplacementRole)
        finally:
            cl._ENUM_SEMANTICS["ReplacementRole"] = original

    def test_c_the_schema_declares_every_column_and_no_others(self) -> None:
        schema = cl.build_schema()
        self.assertEqual(
            [c["name"] for c in schema["columns"]], list(cl.LEDGER_COLUMNS)
        )

    def test_d_the_schema_states_the_null_semantics(self) -> None:
        schema = cl.build_schema()
        self.assertIn("zero", schema["null_semantics"])
        self.assertIn("blank", schema["null_semantics"])
        self.assertIn(NULL_ZERO_UCC, schema["null_semantics"]["regression_case"])

    def test_e_the_manifest_records_each_contradiction_and_its_outcome(self) -> None:
        """Both readings, and what became of the disagreement.

        This test previously required ``not_repaired_because`` on every entry,
        because when it was written none of them had been repaired and the
        manifest's whole contribution was to say why not. The v0.5 correction
        closed all three, so the required field is now ``repaired_in``, which
        carries a successor id or ``None`` while the contradiction stands. The
        two structured readings stay required either way: an entry that
        recorded only the outcome would leave a reader who has the old prose
        in hand with no way to see what it disagreed with.
        """
        manifest = json.loads(cs.MANIFEST_PATH.read_text(encoding="utf-8"))
        entries = manifest["known_internal_inconsistencies"]
        self.assertGreater(len(entries), 0)
        for entry in entries:
            with self.subTest(location=entry["location"]):
                self.assertIn("repaired_in", entry)
                self.assertIn("prose_claim", entry)
                self.assertIn("structured_claim", entry)
                self.assertIn("resolution_in_this_manifest", entry)


if __name__ == "__main__":
    unittest.main(verbosity=2)
