"""The four canonical version locations must never drift (scripts/check_version.py).

The check itself is exercised through its real CLI — the exact invocation
pre-commit and CI depend on — so a regression in either the check or the wiring
surfaces here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = REPO_ROOT / "scripts" / "check_version.py"


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    """Run the version check against ``root`` and capture its result."""

    return subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def _write_repo(
    root: Path,
    *,
    pyproject: str = "1.2.3",
    init: str = "1.2.3",
    plugin: str = "1.2.3",
    changelog: str = "1.2.3",
) -> None:
    """Lay down a minimal repository with a version in each canonical location."""

    (root / "pyproject.toml").write_text(f'[project]\nname = "mimer"\nversion = "{pyproject}"\n')
    package = root / "src" / "mimer"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(f'"""m."""\n\n__version__ = "{init}"\n')
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "mimer", "version": plugin})
    )
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## [Unreleased]\n\n## [{changelog}] - 2026-01-01\n"
    )


def test_the_repository_itself_is_version_consistent() -> None:
    result = _run(REPO_ROOT)
    assert result.returncode == 0, result.stderr


def test_four_agreeing_locations_pass(tmp_path: Path) -> None:
    _write_repo(tmp_path)
    assert _run(tmp_path).returncode == 0


def test_a_drifted_location_is_reported(tmp_path: Path) -> None:
    # plugin.json left behind on a bump — the exact drift the check exists to catch.
    _write_repo(tmp_path, plugin="9.9.9")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "plugin.json" in result.stderr
    assert "9.9.9" in result.stderr


def test_the_changelog_unreleased_heading_is_not_mistaken_for_a_version(tmp_path: Path) -> None:
    # The [Unreleased] heading must be skipped, not read as the released version.
    _write_repo(tmp_path)
    assert _run(tmp_path).returncode == 0
