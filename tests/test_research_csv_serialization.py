#!/usr/bin/env python3
"""Line endings, digests, and the boundary between them.

The 2024 out-of-sample confirmation froze a candidate universe and pinned its
sha256. The pinned value describes bytes that were never committed. Python's
:mod:`csv` writes CRLF unless told otherwise, ``.gitattributes`` declares
``* text=auto``, and git therefore stored LF. The digest was taken between
those two events, so it is a true statement about a file that existed for the
length of one function call and a false statement about anything in the
repository.

Nothing about the research was wrong. The universe, the roster, the
thresholds and the PASS all reproduce. What was wrong was an unstated
assumption that bytes handed to ``open()`` are the bytes git keeps.

Two obligations follow, and this module carries both.

*The historical defect stays legible.* The frozen artifact is not rewritten
and the frozen spec is not edited, so the only way to keep the record honest
is to state the boundary and assert it. Every hash is checked against at
least two independent sources, so the suite cannot be made green by editing
one number in one file.

*The defect does not recur.* The writer now names its line terminator, and
that is asserted the only way worth asserting it: by committing a generated
file into a throwaway repository, checking it back out, and comparing the
bytes that come back.

Each guard is then run against a deliberately broken input and asserted to
fire. A serialisation guard that has never been seen to fail is indis-
tinguishable from one that ignores its arguments.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import research_csv  # noqa: E402
from dmi_research.detailed_inflation import pumd_confirmation as confirm  # noqa: E402

CONFIRM_SPEC_PATH = REPO_ROOT / "registry/research/pumd_lb01_confirmation_spec_v0_1.json"
CORRECTION_PATH = (
    REPO_ROOT
    / "registry/research/pumd_lb01_confirmation_serialization_correction_v0_1.json"
)
UNIVERSE_PATH = (
    REPO_ROOT
    / "data/research/detailed_inflation/pumd_confirmation_2024/candidate_universe.csv"
)

#: The commit that wrote both frozen artifacts, and its direct child that
#: produced the results. Pinned here so that a rewritten history is a test
#: failure rather than a silently re-derived chronology.
FREEZE_COMMIT = "d334eb8b6567a1cbaaa9b67c74f4cebf6719a2f1"
RESULTS_COMMIT = "edd14d458cf6ac160f2237c73b43e750f28821e5"

RESULTS_ARTIFACT = (
    "data/research/detailed_inflation/pumd_confirmation_2024/confirmation_results.csv"
)


# ---------------------------------------------------------------------------
# The boundary, expressed as a function so it can be pointed at broken input
# ---------------------------------------------------------------------------


def _rows(raw: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(raw.decode("utf-8").splitlines()))


def _semantic_hash(rows: list[dict[str, str]]) -> str:
    """The frozen semantic hash, computed through the frozen function.

    ``universe_hash`` reads three attributes and sorts, so parsed CSV rows can
    be fed to it directly. Reimplementing it here instead would test this
    module's copy of the rule rather than the rule.
    """
    return confirm.universe_hash(
        [
            SimpleNamespace(
                ucc=row["ucc"],
                status=row["status"],
                exclusion_reason=row["exclusion_reason"],
            )
            for row in rows
        ]
    )


def _reserialize(rows: list[dict[str, str]], terminator: str) -> bytes:
    """The committed rows written back out with a chosen line terminator.

    Reconstruction goes through :mod:`csv` from the parsed rows rather than
    replacing bytes in the committed file. A byte replacement would prove only
    that ``\\n`` can be turned into ``\\r\\n``; this proves that the rows
    themselves, serialised the way the frozen writer serialised them, are the
    rows the frozen digest was taken over.
    """
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer, fieldnames=list(confirm.UNIVERSE_COLUMNS), lineterminator=terminator
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def boundary_problems(raw: bytes, spec: dict, correction: dict) -> list[str]:
    """Every way the documented serialisation boundary can fail to hold.

    Returned as sorted reason codes rather than raised, so a mutation test can
    assert *which* guard fired. A mutation that alters a UCC must be reported
    as a content failure and not excused as a line-ending one, and the only
    way to assert that is to look at the reason.
    """
    problems: list[str] = []
    digests = correction.get("digests", {})
    rows = _rows(raw)
    pinned = spec["candidate_universe"]["ledger_sha256"]

    if correction.get("correction_type") != "BYTE_REPRESENTATION_DEFECT":
        problems.append("CLASSIFICATION")

    # 1. the committed file is LF and hashes to the documented LF digest
    if b"\r\n" in raw:
        problems.append("COMMITTED_SERIALIZATION")
    if hashlib.sha256(raw).hexdigest() != digests.get("committed_git_normalized_sha256"):
        problems.append("COMMITTED_LF_DIGEST")

    # 2. the semantic hash agrees with the frozen spec and with the record
    semantic = _semantic_hash(rows)
    if semantic != spec["candidate_universe"]["ledger_content_hash"]:
        problems.append("SEMANTIC_CONTENT_HASH")
    if semantic != digests.get("semantic_content_hash"):
        problems.append("SEMANTIC_CONTENT_HASH_RECORD")

    # 3. the roster hash agrees with the frozen spec
    if digests.get("roster_hash") != spec["confirmation_roster"]["roster_hash"]:
        problems.append("ROSTER_HASH")

    # 4. re-serialising the committed rows as CRLF reproduces the pinned value
    historical = hashlib.sha256(_reserialize(rows, "\r\n")).hexdigest()
    if historical != pinned:
        problems.append("HISTORICAL_CRLF_RECONSTRUCTION")
    if historical != digests.get("historical_pre_git_sha256"):
        problems.append("HISTORICAL_CRLF_DIGEST")

    # 5. the record is about this artifact and this spec
    if correction.get("applies_to_artifact") != str(
        UNIVERSE_PATH.relative_to(REPO_ROOT)
    ):
        problems.append("TARGET_ARTIFACT")
    if correction.get("applies_to_spec") != str(CONFIRM_SPEC_PATH.relative_to(REPO_ROOT)):
        problems.append("TARGET_SPEC")

    return sorted(set(problems))


def _git(*args: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )


# ---------------------------------------------------------------------------
# Group 1: the frozen confirmation v0.1, read through the correction record
# ---------------------------------------------------------------------------


class TestFrozenConfirmationSerializationBoundary(unittest.TestCase):
    """The legacy defect, asserted rather than papered over.

    The temptation was to replace the pinned digest with the committed one and
    move on. That would have destroyed the only surviving evidence that the
    freeze and the repository disagree about what a file is, and it would have
    edited a frozen artifact to do it.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = json.loads(CONFIRM_SPEC_PATH.read_text(encoding="utf-8"))
        cls.correction = json.loads(CORRECTION_PATH.read_text(encoding="utf-8"))
        cls.raw = UNIVERSE_PATH.read_bytes()

    def test_a_the_correction_record_exists_and_is_research_only(self) -> None:
        self.assertEqual(self.correction["status"], "RESEARCH_ONLY")
        self.assertEqual(self.correction["correction_type"], "BYTE_REPRESENTATION_DEFECT")
        self.assertEqual(
            self.correction["artifact_id"],
            "PUMD_LB01_CONFIRMATION_SERIALIZATION_CORRECTION_V0_1",
        )

    def test_b_the_whole_boundary_holds(self) -> None:
        self.assertEqual(
            boundary_problems(self.raw, self.spec, self.correction),
            [],
        )

    def test_c_the_record_points_at_the_frozen_spec_and_artifact(self) -> None:
        """Item 5: the record is reachable from, and about, the frozen pair."""
        self.assertEqual(
            self.correction["applies_to_spec"],
            str(CONFIRM_SPEC_PATH.relative_to(REPO_ROOT)),
        )
        self.assertEqual(
            self.correction["applies_to_artifact"],
            str(UNIVERSE_PATH.relative_to(REPO_ROOT)),
        )
        self.assertEqual(
            self.correction["applies_to_spec_field"], "candidate_universe.ledger_sha256"
        )
        self.assertEqual(self.correction["frozen_commit"], FREEZE_COMMIT)
        self.assertEqual(self.correction["results_commit"], RESULTS_COMMIT)

    def test_d_the_record_claims_nothing_changed(self) -> None:
        checked = self.correction["invariants_checked"]
        for key in (
            "candidate_universe_content_changed",
            "roster_changed",
            "thresholds_changed",
            "confirmation_results_changed",
            "precommitment_compromised",
        ):
            with self.subTest(invariant=key):
                self.assertIs(checked[key], False)

    def test_e_the_manifest_reaches_the_correction_record(self) -> None:
        """C1's manifest records the discrepancy and names its resolution."""
        from dmi_research.detailed_inflation import canonical_state as cs

        manifest = json.loads(cs.MANIFEST_PATH.read_text(encoding="utf-8"))
        entries = [
            e
            for e in manifest["known_internal_inconsistencies"]
            if e["repaired_in"] == self.correction["artifact_id"]
        ]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["location"], "candidate_universe.ledger_sha256")
        self.assertEqual(
            entry["repaired_in_path"], str(CORRECTION_PATH.relative_to(REPO_ROOT))
        )
        self.assertTrue((REPO_ROOT / entry["repaired_in_path"]).is_file())

    def test_f_chronology_still_puts_the_freeze_before_the_results(self) -> None:
        """Item 6. The correction changes no part of this and must not.

        Read from the local object database. If git is unavailable the claim
        cannot be checked and the test says so rather than passing quietly.
        """
        if _git("rev-parse", "--git-dir").returncode != 0:
            self.skipTest("not a git checkout")
        for commit in (FREEZE_COMMIT, RESULTS_COMMIT):
            if _git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
                self.skipTest(f"{commit[:8]} is not present in this clone")

        self.assertEqual(
            _git("merge-base", "--is-ancestor", FREEZE_COMMIT, RESULTS_COMMIT).returncode,
            0,
            "the freeze must be an ancestor of the results",
        )
        # and nothing sits between them
        between = _git(
            "rev-list", "--count", f"{FREEZE_COMMIT}..{RESULTS_COMMIT}"
        ).stdout.strip()
        self.assertEqual(between, "1", "the results commit is the freeze's direct child")

        # the frozen pair existed at the freeze, the results did not
        for path in (
            str(UNIVERSE_PATH.relative_to(REPO_ROOT)),
            str(CONFIRM_SPEC_PATH.relative_to(REPO_ROOT)),
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    _git("cat-file", "-e", f"{FREEZE_COMMIT}:{path}").returncode, 0
                )
        self.assertNotEqual(
            _git("cat-file", "-e", f"{FREEZE_COMMIT}:{RESULTS_ARTIFACT}").returncode,
            0,
            "results must not exist at the moment the universe was frozen",
        )
        self.assertEqual(
            _git("cat-file", "-e", f"{RESULTS_COMMIT}:{RESULTS_ARTIFACT}").returncode, 0
        )

    def test_g_the_frozen_pair_is_unchanged_since_the_freeze(self) -> None:
        """Neither frozen file has moved, which is what makes the rest true."""
        if _git("rev-parse", "--git-dir").returncode != 0:
            self.skipTest("not a git checkout")
        if _git("cat-file", "-e", f"{FREEZE_COMMIT}^{{commit}}").returncode != 0:
            self.skipTest("freeze commit absent")
        for path in (
            str(UNIVERSE_PATH.relative_to(REPO_ROOT)),
            str(CONFIRM_SPEC_PATH.relative_to(REPO_ROOT)),
        ):
            with self.subTest(path=path):
                frozen = _git("rev-parse", f"{FREEZE_COMMIT}:{path}").stdout.strip()
                now = _git("rev-parse", f"HEAD:{path}").stdout.strip()
                self.assertEqual(frozen, now)


# ---------------------------------------------------------------------------
# Group 2: the boundary guards fire
# ---------------------------------------------------------------------------


class TestBoundaryGuardsAreNotVacuous(unittest.TestCase):
    """Each mutation must fail, and must fail for the right reason."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = json.loads(CONFIRM_SPEC_PATH.read_text(encoding="utf-8"))
        cls.correction = json.loads(CORRECTION_PATH.read_text(encoding="utf-8"))
        cls.raw = UNIVERSE_PATH.read_bytes()

    def test_a_the_unmutated_inputs_pass(self) -> None:
        self.assertEqual(boundary_problems(self.raw, self.spec, self.correction), [])

    def test_b_a_missing_correction_record_is_caught(self) -> None:
        """Deleting the record must not silently restore the old green suite."""
        problems = boundary_problems(self.raw, self.spec, {})
        self.assertIn("CLASSIFICATION", problems)
        self.assertIn("COMMITTED_LF_DIGEST", problems)
        self.assertIn("HISTORICAL_CRLF_DIGEST", problems)

    def test_c_a_wrong_committed_lf_digest_is_caught(self) -> None:
        broken = json.loads(json.dumps(self.correction))
        broken["digests"]["committed_git_normalized_sha256"] = "0" * 64
        self.assertEqual(
            boundary_problems(self.raw, self.spec, broken), ["COMMITTED_LF_DIGEST"]
        )

    def test_d_a_wrong_historical_crlf_digest_is_caught(self) -> None:
        broken = json.loads(json.dumps(self.correction))
        broken["digests"]["historical_pre_git_sha256"] = "0" * 64
        self.assertEqual(
            boundary_problems(self.raw, self.spec, broken), ["HISTORICAL_CRLF_DIGEST"]
        )

    def test_e_a_wrong_roster_hash_is_caught(self) -> None:
        broken = json.loads(json.dumps(self.correction))
        broken["digests"]["roster_hash"] = "0" * 64
        self.assertEqual(boundary_problems(self.raw, self.spec, broken), ["ROSTER_HASH"])

    def test_f_calling_the_defect_metadata_only_is_caught(self) -> None:
        """The classification is load-bearing and is asserted, not decorative."""
        broken = json.loads(json.dumps(self.correction))
        broken["correction_type"] = "METADATA_ONLY_DIGEST_DEFECT"
        self.assertEqual(boundary_problems(self.raw, self.spec, broken), ["CLASSIFICATION"])

    def test_g_a_semantic_cell_change_is_not_excused_as_line_endings(self) -> None:
        """The mutation that matters most.

        One UCC's exclusion reason is changed and the line endings are left
        alone. If the boundary check reported only a digest difference, a real
        change to the universe could be waved through as a serialisation
        artifact, which is precisely the failure this whole module exists to
        prevent.
        """
        rows = _rows(self.raw)
        victim = next(r for r in rows if r["exclusion_reason"] == "IN_DEVELOPMENT_ROSTER")
        victim["exclusion_reason"] = "BLANK_PUBLISHED_MEAN"
        mutated = _reserialize(rows, "\n")
        self.assertNotIn(b"\r\n", mutated, "the mutation must not touch line endings")

        problems = boundary_problems(mutated, self.spec, self.correction)
        self.assertIn("SEMANTIC_CONTENT_HASH", problems)
        self.assertIn("SEMANTIC_CONTENT_HASH_RECORD", problems)
        self.assertNotIn("COMMITTED_SERIALIZATION", problems)

    def test_h_a_pointer_at_the_wrong_artifact_is_caught(self) -> None:
        broken = json.loads(json.dumps(self.correction))
        broken["applies_to_artifact"] = "data/research/detailed_inflation/nowhere.csv"
        self.assertEqual(boundary_problems(self.raw, self.spec, broken), ["TARGET_ARTIFACT"])


# ---------------------------------------------------------------------------
# Group 3: prospectively, the writer and git agree
# ---------------------------------------------------------------------------

SAMPLE_COLUMNS = ("ucc", "status", "note")
SAMPLE_ROWS = [
    {"ucc": "010110", "status": "INCLUDED_IN_CONFIRMATION", "note": "plain"},
    {"ucc": "020310", "status": "EXCLUDED", "note": "has, a comma"},
    {"ucc": "030410", "status": "EXCLUDED", "note": 'has "quotes"'},
]


class _IsolatedRepo:
    """A throwaway git repository carrying this repository's .gitattributes.

    Local only. Nothing here reaches the network, and the real repository is
    never written to: the question is what git does to bytes under
    ``* text=auto``, and any repository with that rule answers it.
    """

    def __enter__(self) -> Path:
        self.root = Path(tempfile.mkdtemp(prefix="csv-serialization-"))
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        for key, value in (("user.email", "t@example.invalid"), ("user.name", "t")):
            subprocess.run(["git", "config", key, value], cwd=self.root, check=True)
        shutil.copyfile(REPO_ROOT / ".gitattributes", self.root / ".gitattributes")
        return self.root

    def __exit__(self, *exc: object) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def materialized_after_commit(repo: Path, name: str, data: bytes) -> bytes:
    """The bytes that come back after add, commit, delete and checkout.

    This is the whole question stated as an experiment. A test that only
    hashed the writer's output would have passed before the defect too.
    """
    target = repo / name
    target.write_bytes(data)
    subprocess.run(["git", "add", name], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "t"], cwd=repo, check=True)
    target.unlink()
    subprocess.run(["git", "checkout", "--", name], cwd=repo, check=True)
    return target.read_bytes()


class TestGeneratedResearchCsvSurvivesGit(unittest.TestCase):
    """Writer output, the stored blob and the checked-out file are one thing."""

    def _generate(self) -> bytes:
        scratch = Path(tempfile.mkdtemp(prefix="csv-writer-"))
        try:
            out = scratch / "sample.csv"
            research_csv.write_csv(out, SAMPLE_COLUMNS, SAMPLE_ROWS)
            return out.read_bytes()
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_a_the_writer_emits_lf_only(self) -> None:
        data = self._generate()
        self.assertNotIn(b"\r\n", data)
        self.assertNotIn(b"\r", data)
        self.assertTrue(data.endswith(b"\n"))
        self.assertEqual(research_csv.LINE_TERMINATOR, "\n")

    def test_b_the_bytes_git_stores_are_the_bytes_written(self) -> None:
        data = self._generate()
        with _IsolatedRepo() as repo:
            (repo / "sample.csv").write_bytes(data)
            stored = subprocess.run(
                ["git", "hash-object", "-w", "--path", "sample.csv", "sample.csv"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            blob = subprocess.run(
                ["git", "cat-file", "blob", stored], cwd=repo, capture_output=True
            ).stdout
        self.assertEqual(blob, data)

    def test_c_a_raw_digest_survives_the_round_trip(self) -> None:
        data = self._generate()
        before = hashlib.sha256(data).hexdigest()
        with _IsolatedRepo() as repo:
            back = materialized_after_commit(repo, "sample.csv", data)
        self.assertEqual(back, data)
        self.assertEqual(hashlib.sha256(back).hexdigest(), before)

    def test_d_the_defect_reproduces_if_the_default_terminator_returns(self) -> None:
        """Non-vacuity for the whole group.

        The same experiment run against a CRLF writer must fail, or the three
        tests above are asserting a property of git rather than a property of
        this writer.
        """
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=list(SAMPLE_COLUMNS))
        writer.writeheader()
        for row in SAMPLE_ROWS:
            writer.writerow(row)
        crlf = buffer.getvalue().encode("utf-8")
        self.assertIn(b"\r\n", crlf, "csv's default is still CRLF")

        before = hashlib.sha256(crlf).hexdigest()
        with _IsolatedRepo() as repo:
            back = materialized_after_commit(repo, "sample.csv", crlf)
        self.assertNotEqual(back, crlf)
        self.assertNotEqual(hashlib.sha256(back).hexdigest(), before)
        self.assertEqual(back, crlf.replace(b"\r\n", b"\n"))

    def test_e_the_frozen_universe_is_still_the_counterexample(self) -> None:
        """The legacy artifact is recognised as defective, not retro-fitted.

        Regenerating it under the new writer would produce the committed LF
        bytes, which is the fix working. It would not produce the pinned
        digest, and pretending otherwise is what the correction record exists
        to prevent.
        """
        raw = UNIVERSE_PATH.read_bytes()
        rows = _rows(raw)
        under_new_writer = _reserialize(rows, research_csv.LINE_TERMINATOR)
        self.assertEqual(under_new_writer, raw)
        spec = json.loads(CONFIRM_SPEC_PATH.read_text(encoding="utf-8"))
        self.assertNotEqual(
            hashlib.sha256(under_new_writer).hexdigest(),
            spec["candidate_universe"]["ledger_sha256"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
