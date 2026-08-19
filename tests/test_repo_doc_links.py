#!/usr/bin/env python3
"""Repository documentation link checker (Round-3 §11).

Purpose
-------
This test freezes the invariant that Markdown navigational links
(``[label](path)``) in tracked documentation resolve to a file or
directory inside the repository. It was added after Round-3 §11,
where ``docs/repair/CORE_WITHDRAWAL.md`` was found to be referenced
by 30+ files across the repository (README, CHANGELOG, CITATION.cff,
workflows, plugin code, docs, tests) without the target existing on
disk.

Scope
-----
- Markdown files (``*.md``) under the repository root, excluding
  frozen archives (``dmi-v0.1.10-deployment/``) and vendored trees.
- Only ``[label](target)`` link syntax is checked. Backtick-quoted
  paths in prose are not checked, because evidence records
  (``CORE_OUTPUT_WITHDRAWAL.md``, ``V0.1.12_ALIGNMENT_AUDIT.md``)
  legitimately enumerate paths that have been withdrawn or that live
  outside the repository by design (e.g. the concept-note file per
  controlling decision 6).
- External links (``http(s)://``, ``mailto:``, ``file://``, ``//``),
  absolute filesystem paths, and pure anchors (``#foo``) are
  ignored.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories not owned by the current repair — frozen archives, git
# metadata, virtualenvs, caches, and node_modules. Documentation links
# inside these trees are not our concern.
EXCLUDED_DIR_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dmi-v0.1.10-deployment",  # frozen archive per controlling decision
}

# Markdown link: [label](target)   — captures target
# We only match when target does not contain whitespace (real links).
MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")

# Anchors are permitted inside link targets (path#section). We strip
# them before existence-checking the path.
def _strip_anchor(target: str) -> str:
    idx = target.find("#")
    return target if idx < 0 else target[:idx]


def _is_external(target: str) -> bool:
    lowered = target.lower()
    if lowered.startswith(
        (
            "http://",
            "https://",
            "mailto:",
            "ftp://",
            "ftps://",
            "file://",
            "//",
        )
    ):
        return True
    # Absolute filesystem paths and anchor-only targets are not
    # repo-internal file references we can check.
    if target.startswith("/") or target.startswith("#"):
        return True
    return False


def _iter_markdown_files():
    for path in ROOT.rglob("*.md"):
        rel_parts = path.relative_to(ROOT).parts
        if any(part in EXCLUDED_DIR_PARTS for part in rel_parts):
            continue
        yield path


def _resolve_relative(source: Path, target: str) -> Path:
    """Resolve a link target against the source file's directory."""
    return (source.parent / target).resolve()


class TestMarkdownLinkTargetsExist(unittest.TestCase):
    """Every ``[label](path)`` link in a tracked Markdown file whose
    target is a repo-relative path must resolve to a file or directory
    that exists inside the repository."""

    def test_markdown_link_targets_resolve(self):
        broken: list[tuple[str, str]] = []

        for md_path in _iter_markdown_files():
            text = md_path.read_text(errors="replace")
            for match in MD_LINK_RE.finditer(text):
                raw_target = match.group(1)
                if _is_external(raw_target):
                    continue
                target = _strip_anchor(raw_target)
                if not target:
                    # Pure anchor like [foo](#bar) — skipped by
                    # _is_external, but guard against empty after
                    # strip.
                    continue
                resolved = _resolve_relative(md_path, target)
                # Reject links that escape the repository root.
                try:
                    resolved.relative_to(ROOT)
                except ValueError:
                    broken.append(
                        (
                            str(md_path.relative_to(ROOT)),
                            f"{raw_target} (escapes repository root)",
                        )
                    )
                    continue
                if not resolved.exists():
                    broken.append(
                        (
                            str(md_path.relative_to(ROOT)),
                            raw_target,
                        )
                    )

        self.assertEqual(
            broken,
            [],
            "§11: Markdown link targets missing from repository:\n"
            + "\n".join(f"  {src} -> {tgt}" for src, tgt in broken),
        )


class TestCoreWithdrawalDocsResolveEverywhere(unittest.TestCase):
    """Concrete spot-check for the §11 rationale: the two Core-
    withdrawal documents that other files link to must exist."""

    def test_repair_core_withdrawal_present(self):
        self.assertTrue(
            (ROOT / "docs/repair/CORE_WITHDRAWAL.md").is_file(),
            "§11: docs/repair/CORE_WITHDRAWAL.md must exist "
            "(referenced by README, CHANGELOG, workflows, plugin, docs).",
        )

    def test_known_issues_core_output_withdrawal_present(self):
        self.assertTrue(
            (ROOT / "docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md").is_file(),
            "§11: docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md must "
            "exist (deep evidence record).",
        )


if __name__ == "__main__":
    unittest.main()


# Schemes and path shapes that only resolve on one machine. Kept as
# fragments assembled at runtime rather than as literals, so this list
# never matches itself: the scan below reads Markdown link targets, and
# this module is itself a tracked file that talks about the thing it
# forbids.
_LOCAL_SCHEME = "file" + "://"
_LOCAL_PATH_PREFIXES = ("/Users/", "/home/", "/private/tmp", "/var/folders",
                        "C:\\", "/tmp/")


def _tracked_markdown_files():
    """Tracked ``*.md`` only.

    ``rglob`` would also sweep up untracked scratch files in a working
    tree, which would fail this suite for something the repository does
    not contain.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.md"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    for rel in filter(None, out.split("\0")):
        path = ROOT / rel
        if any(part in EXCLUDED_DIR_PARTS for part in Path(rel).parts):
            continue
        if path.is_file():
            yield path


def _local_link_offenders(text: str):
    """Link targets in ``text`` that only resolve on the author's machine.

    Only regex-extracted ``[label](target)`` targets are examined --
    never raw file text. Prose and comments in this repository must be
    free to name ``file://`` when explaining why it is banned, and an
    earlier generation of these tests repeatedly broke by forbidding a
    string that appeared in the sentence explaining the prohibition.
    """
    offenders = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for target in MD_LINK_RE.findall(line):
            lowered = target.lower()
            if lowered.startswith(_LOCAL_SCHEME):
                offenders.append((lineno, target, "local file:// scheme"))
            elif target.startswith(_LOCAL_PATH_PREFIXES):
                offenders.append((lineno, target, "absolute local path"))
    return offenders


class TestNoLocalFilesystemLinksInMarkdown(unittest.TestCase):
    """Tracked Markdown must not cite evidence by machine-local path.

    ``docs/v0.1.10_CLOSURE.md`` once cited all seven of its evidence
    files as ``file:///Users/<someone>/dev/dmi/...``. Those links
    resolved on exactly one laptop and were dead for every other reader,
    including anyone browsing the repository on GitHub -- a closure
    record whose evidence cannot be followed does not establish what it
    claims to establish.

    ``TestMarkdownLinkTargetsExist`` did not catch them: ``_is_external``
    treats ``file://`` and leading ``/`` as external and skips both, so
    the checker walked past seven dead links in a file it was already
    scanning. This class closes that gap. ``_is_external`` is left alone
    deliberately -- removing the scheme there would make the existence
    checker report a confusing "does not exist" instead of naming the
    real problem.

    A target that genuinely lives outside the repository should be an
    ``https://`` URL, and a file that no longer exists should be a commit
    permalink pinning the full 40-character SHA.
    """

    def test_no_tracked_markdown_uses_a_local_filesystem_link(self):
        found = []
        for path in _tracked_markdown_files():
            rel = path.relative_to(ROOT)
            for lineno, target, why in _local_link_offenders(path.read_text()):
                found.append(f"{rel}:{lineno} -> {target}  ({why})")
        self.assertEqual(
            found, [],
            "Markdown link targets must resolve for every reader, not "
            "only on the author's machine. Use a repository-relative "
            "path, or an https:// permalink for content outside the "
            f"tree. Offenders:\n  " + "\n  ".join(found),
        )

    def test_the_v0_1_10_closure_record_is_clean(self):
        """The specific document this control was written for."""
        doc = ROOT / "docs" / "v0.1.10_CLOSURE.md"
        self.assertTrue(doc.is_file(), "closure record is missing")
        self.assertEqual(_local_link_offenders(doc.read_text()), [])

    def test_withdrawn_evidence_is_pinned_to_a_full_sha_permalink(self):
        """``prepare_deployment.sh`` was deleted in 46c9f05.

        It cannot be a relative link, so it must be a commit permalink --
        and pinned by full SHA, since GitHub resolves short SHAs but they
        are not collision-stable.
        """
        text = (ROOT / "docs" / "v0.1.10_CLOSURE.md").read_text()
        targets = [t for t in MD_LINK_RE.findall(text)
                   if t.endswith("/prepare_deployment.sh")]
        self.assertEqual(len(targets), 1, "expected exactly one reference")
        target = targets[0]
        self.assertTrue(target.startswith("https://github.com/dmianalysis/dmi/blob/"))
        sha = target.split("/blob/", 1)[1].split("/", 1)[0]
        self.assertEqual(len(sha), 40, f"pin must be a full 40-char SHA, got {sha!r}")
        self.assertEqual(sha, "12b3126ace07da893dfdc6b1d752311ee331d5dc")

    def test_detector_is_not_vacuous(self):
        """Guard against passing because the link regex stopped matching.

        Without this, every assertion above would still pass if
        ``MD_LINK_RE`` were broken -- finding nothing looks identical to
        there being nothing to find.
        """
        sample = (
            "ok [a](../rel/path.md) and [b](https://example.com/x)\n"
            "bad [c](file:///Users/someone/dev/dmi/x.sh)\n"
            "bad [d](/home/someone/y.json)\n"
        )
        offenders = _local_link_offenders(sample)
        self.assertEqual(len(offenders), 2, f"detector missed cases: {offenders}")
        self.assertEqual([o[0] for o in offenders], [2, 3])
        self.assertEqual([o[2] for o in offenders],
                         ["local file:// scheme", "absolute local path"])

    def test_scan_reads_link_targets_not_raw_text(self):
        """Prose must stay free to name the thing it forbids.

        This module's own docstrings contain the banned scheme. If the
        scan ever regresses to substring-matching raw text, this test
        fails -- which is the correct outcome, because the fix is to
        scope the scan, never to exempt a file.
        """
        prose = (
            "Do not write " + _LOCAL_SCHEME + "/Users/me/x.md in docs.\n"
            "See /home/me/notes.txt for context.\n"
        )
        self.assertEqual(_local_link_offenders(prose), [])
