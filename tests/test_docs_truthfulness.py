"""Documentation-truthfulness sweep (issue #45).

Every checkable claim in the shipped docs must match the code, and the internal
invariants (no present-tense Cowork claim; one coherent version story) must
hold. These tests read the doc files directly, in the spirit of
``test_memory_skill.py`` — the docs are part of the product, so their factual
claims are constrained like any other behaviour.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

README = ROOT / "README.md"
NOTICE = ROOT / "NOTICE"
CHANGELOG = ROOT / "CHANGELOG.md"
OKF_PROFILE = ROOT / "docs" / "okf-profile.md"
SKILL = ROOT / "skills" / "memory" / "SKILL.md"
PYPROJECT = ROOT / "pyproject.toml"
PLUGIN_MANIFEST = ROOT / ".claude-plugin" / "plugin.json"
INIT = ROOT / "src" / "mimer" / "__init__.py"


def _user_facing_commands() -> set[str]:
    """The ``mimer-*`` console scripts a user invokes, derived from
    ``pyproject.toml``.

    The three hook targets (``mimer.hooks.*``) are entry points Claude Code
    calls on lifecycle events, not commands a user runs, so they are excluded.
    """

    scripts = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["scripts"]
    return {name for name, target in scripts.items() if not target.startswith("mimer.hooks.")}


def _manifest_versions() -> dict[str, str]:
    """The version string as declared in each of the three places it lives."""

    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    plugin = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))["version"]
    init_match = re.search(r'__version__\s*=\s*"([^"]+)"', INIT.read_text(encoding="utf-8"))
    assert init_match is not None, "src/mimer/__init__.py declares no __version__"
    return {"pyproject.toml": pyproject, "plugin.json": plugin, "__init__.py": init_match.group(1)}


def _changelog_sections() -> dict[str, str]:
    """Map each ``## [name]`` changelog heading to the body text beneath it."""

    text = CHANGELOG.read_text(encoding="utf-8")
    headings = list(re.finditer(r"^## \[([^\]]+)\]", text, re.MULTILINE))
    sections: dict[str, str] = {}
    for index, heading in enumerate(headings):
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        sections[heading.group(1)] = text[start:end]
    return sections


def _comparison_row_mimer_cell(feature: str) -> str:
    """Return Mimer's cell for a named row of the agent-memory comparison table.

    The table's first data column is Mimer, so the cell sits at split index 2
    (``['', label, mimer, ...]``).
    """

    for line in README.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"| {feature} "):
            return [cell.strip() for cell in line.split("|")][2]
    raise AssertionError(f"No comparison row found for {feature!r}")


def test_readme_does_not_claim_mimer_is_unbuilt() -> None:
    """The README must not say the plugin is unbuilt or unshippable (issue #45)."""

    text = README.read_text(encoding="utf-8")
    assert "not built yet" not in text
    assert "They ship today" not in text


def test_readme_comparison_marks_mimer_installable() -> None:
    """The 'Installable today' row must show Mimer as available (✓), not ✗."""

    assert _comparison_row_mimer_cell("Installable today") == "✓"


def test_readme_has_no_deferred_placeholder_sections() -> None:
    """The usage and development sections document what exists, not 'will be
    added later' placeholders for a toolchain that already ships."""

    text = README.read_text(encoding="utf-8")
    assert "Detailed usage will be documented as the interface settles" not in text
    assert "Build and test instructions will be added as the toolchain takes shape" not in text


def test_readme_documents_every_user_facing_command() -> None:
    """The README must document all user-facing ``mimer-*`` commands, including
    the previously omitted mimer-memory, mimer-recall and mimer-reindex."""

    text = README.read_text(encoding="utf-8")
    missing = {command for command in _user_facing_commands() if command not in text}
    assert missing == set(), f"README omits user-facing commands: {sorted(missing)}"


def test_notice_makes_no_present_tense_cowork_claim() -> None:
    """NOTICE must not call Mimer a Cowork plugin — ADR 0010's invariant is that
    no document claims Cowork support in the present tense."""

    assert "Cowork" not in NOTICE.read_text(encoding="utf-8")


def test_no_document_calls_mimer_a_cowork_plugin() -> None:
    """The present-tense 'Claude Code and Claude Cowork plugin' construction must
    not survive anywhere in the tracked docs (ADR 0010)."""

    offenders = []
    for path in [README, NOTICE, CHANGELOG, OKF_PROFILE, ROOT / "docs" / "vision.md"]:
        if "Claude Code and Claude Cowork plugin" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert offenders == [], f"Present-tense Cowork claim in: {offenders}"


def test_manifest_versions_agree() -> None:
    """The version must be identical across pyproject, the plugin manifest and
    the package's __version__."""

    versions = _manifest_versions()
    assert len(set(versions.values())) == 1, f"Version disagreement: {versions}"


def test_changelog_places_features_under_the_manifest_version() -> None:
    """The changelog's story for the manifest version must be the actual feature
    set (Stages 0–8), not a bare 'Initial release' stub with the features
    stranded under Unreleased."""

    version = next(iter(_manifest_versions().values()))
    sections = _changelog_sections()
    assert version in sections, f"CHANGELOG has no section for {version}"
    released = sections[version]
    assert "Foundations (Stage 0)" in released
    assert "Packaging and first run (Stage 8)" in released
    assert "- Initial release." not in CHANGELOG.read_text(encoding="utf-8")


def test_changelog_does_not_strand_features_under_unreleased() -> None:
    """Unreleased must not still hold the shipped Stage 0–8 feature set."""

    unreleased = _changelog_sections().get("Unreleased", "")
    assert "Foundations (Stage 0)" not in unreleased
    assert "Packaging and first run (Stage 8)" not in unreleased


def test_okf_profile_describes_vendored_spec_in_present_tense() -> None:
    """okf-profile.md must state the spec is vendored (it already is under
    docs/okf/), not that it will be when Stage 5a is built."""

    text = OKF_PROFILE.read_text(encoding="utf-8")
    assert (ROOT / "docs" / "okf" / "SPEC.md").is_file()
    assert "When Stage 5a is built" not in text
    assert "docs/okf/" in text


def test_changelog_claim_about_readme_command_coverage_is_true() -> None:
    """If the changelog claims the README documents the mimer-* commands, that
    must be verifiably true of the README."""

    changelog = CHANGELOG.read_text(encoding="utf-8")
    if "the README documents" in changelog and "`mimer-*` commands" in changelog:
        readme = README.read_text(encoding="utf-8")
        missing = {command for command in _user_facing_commands() if command not in readme}
        assert missing == set(), f"CHANGELOG claim is false; README omits: {sorted(missing)}"


def test_skill_documents_the_claude_plugin_root_dependency() -> None:
    """The skill relies on ${CLAUDE_PLUGIN_ROOT} in skill-run Bash, which the
    platform documents only for hooks; the skill must record that guarantee so a
    future platform change does not silently break it (issue #45)."""

    text = SKILL.read_text(encoding="utf-8")
    assert "${CLAUDE_PLUGIN_ROOT}" in text
    assert "resolves in skill-run Bash" in text
