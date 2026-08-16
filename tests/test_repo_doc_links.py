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
