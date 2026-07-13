#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Check that Mimer's version agrees across every place it is declared.

The version lives in four canonical spots that must never drift apart:
``pyproject.toml``, ``src/mimer/__init__.py``, ``.claude-plugin/plugin.json``,
and the latest released heading in ``CHANGELOG.md``. This runs as a pre-commit
hook and as an early CI step, so a half-applied bump fails fast — before a
release ever ships a mismatched version.

Exit codes:
    0   All four locations agree.
    1   They disagree, or a location could not be read.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

# The default repository root: this script lives in ``<root>/scripts/``.
REPO_ROOT = Path(__file__).resolve().parent.parent

# The first ``## [x.y.z]`` changelog heading that is not ``[Unreleased]`` — the
# most recently released version.
_RELEASED_HEADING_RE = re.compile(r"^## \[(?!Unreleased\])([^\]]+)\]", re.MULTILINE)

# ``__version__ = "x.y.z"`` in the package's ``__init__``.
_DUNDER_VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)


def read_versions(root: Path) -> dict[str, str]:
    """Read the declared version from each canonical location.

    Args:
        root: The repository root to read from.

    Returns:
        A mapping of a human-readable location label to the version it declares.

    Raises:
        ValueError: A location is missing or its version cannot be parsed; the
            message names the offending location.
    """

    versions: dict[str, str] = {}

    # pyproject.toml — the project's own [project] version.
    pyproject = root / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project")
    if not isinstance(project, dict) or "version" not in project:
        raise ValueError(f"no [project].version in {pyproject}")
    versions["pyproject.toml"] = str(project["version"])

    # The package's __version__ dunder.
    init = root / "src" / "mimer" / "__init__.py"
    dunder = _DUNDER_VERSION_RE.search(init.read_text(encoding="utf-8"))
    if dunder is None:
        raise ValueError(f"no __version__ in {init}")
    versions["src/mimer/__init__.py"] = dunder.group(1)

    # The plugin manifest's version.
    plugin = root / ".claude-plugin" / "plugin.json"
    manifest = json.loads(plugin.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or "version" not in manifest:
        raise ValueError(f"no version in {plugin}")
    versions[".claude-plugin/plugin.json"] = str(manifest["version"])

    # The latest released changelog heading.
    changelog = root / "CHANGELOG.md"
    heading = _RELEASED_HEADING_RE.search(changelog.read_text(encoding="utf-8"))
    if heading is None:
        raise ValueError(f"no released '## [x.y.z]' heading in {changelog}")
    versions["CHANGELOG.md"] = heading.group(1).strip()

    return versions


def check(root: Path) -> list[str]:
    """Return the version-consistency problems for a repository.

    Args:
        root: The repository root to check.

    Returns:
        Human-readable problem lines; an empty list means every location agrees.
    """

    try:
        versions = read_versions(root)
    except ValueError as exc:
        return [str(exc)]

    # A single distinct value across all locations is the only healthy state.
    if len(set(versions.values())) <= 1:
        return []

    return [f"  {label}: {version}" for label, version in versions.items()]


def main() -> int:
    """Check the repository and report, exiting non-zero on any mismatch."""

    parser = argparse.ArgumentParser(description="Check Mimer's version is consistent everywhere.")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="Repository root to check.")
    args = parser.parse_args()
    root: Path = args.root

    problems = check(root)
    if problems:
        print("Version mismatch across declared locations:", *problems, sep="\n", file=sys.stderr)
        return 1

    agreed = next(iter(read_versions(root).values()))
    print(f"Version consistent: {agreed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
