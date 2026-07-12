"""CI and local-developer-ergonomics guarantees (issue #46).

These tests are the executable contract for the project's continuous-integration
and tooling configuration: they parse the checked-in config files and assert the
properties the issue requires, so a later edit that silently drops macOS from the
matrix, removes coverage, un-pins the model fetch, or lets the local gates drift
from CI fails here instead of surfacing only after a push. The repo already tests
project files this way (see ``test_readme_documents_install_and_coexistence``).
"""

from __future__ import annotations

import fnmatch
import os
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from mimer.embedding import EMBEDDING_DIMENSIONS, embed

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT = REPO_ROOT / "pyproject.toml"
PRECOMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
EDITORCONFIG = REPO_ROOT / ".editorconfig"


def _load_ci() -> Any:
    """Parse the CI workflow YAML."""

    return yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))


def _load_pyproject() -> dict[str, Any]:
    """Parse ``pyproject.toml``."""

    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _step_text(step: Any) -> str:
    """A lowercased blob of a workflow step's name, ``run`` body and ``uses``."""

    return " ".join(str(step.get(key, "")) for key in ("name", "run", "uses")).lower()


def _first_step_index(steps: Any, predicate: Callable[[Any], bool]) -> int | None:
    """Index of the first step matching ``predicate``, or None."""

    for index, step in enumerate(steps):
        if predicate(step):
            return index
    return None


def _editorconfig_pattern_matches(pattern: str, filename: str) -> bool:
    """Whether an EditorConfig section glob matches ``filename``.

    Handles a single ``{a,b,c}`` brace group by expanding it into alternatives,
    which is enough for the patterns this project uses.
    """

    if "{" in pattern and "}" in pattern:
        prefix, _, rest = pattern.partition("{")
        inner, _, suffix = rest.partition("}")
        return any(
            _editorconfig_pattern_matches(f"{prefix}{option}{suffix}", filename)
            for option in inner.split(",")
        )
    return fnmatch.fnmatch(filename, pattern)


def _editorconfig_settings(path: Path, filename: str) -> dict[str, str]:
    """Resolve the EditorConfig keys that apply to ``filename``.

    Walks the sections top to bottom, merging the keys of every section whose
    glob matches, so later, more specific sections win — as EditorConfig defines.
    """

    settings: dict[str, str] = {}
    section_matches = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section_matches = _editorconfig_pattern_matches(line[1:-1], filename)
            continue
        if "=" in line and section_matches:
            key, _, value = line.partition("=")
            settings[key.strip().lower()] = value.strip()
    return settings


def test_ci_runs_on_both_linux_and_macos() -> None:
    """AC1: the CI matrix covers both target platforms, not Linux alone."""

    matrix = _load_ci()["jobs"]["test"].get("strategy", {}).get("matrix", {})
    operating_systems = " ".join(str(entry) for entry in matrix.get("os", [])).lower()

    assert "ubuntu" in operating_systems
    assert "macos" in operating_systems


def test_ci_prefetches_the_model_before_running_tests() -> None:
    """AC3: an explicit prefetch step precedes pytest, so the model is never
    fetched lazily on a cache miss mid-suite."""

    steps = _load_ci()["jobs"]["test"]["steps"]
    prefetch_index = _first_step_index(steps, lambda step: "prefetch" in _step_text(step))
    pytest_index = _first_step_index(steps, lambda step: "pytest" in _step_text(step))

    assert prefetch_index is not None, "CI must prefetch the embedding model"
    assert pytest_index is not None, "CI must run pytest"
    assert prefetch_index < pytest_index, "the model must be prefetched before tests run"


def test_the_model_is_prefetched_so_the_suite_runs_offline() -> None:
    """AC3: the test session pins Hugging Face to offline mode, which is only
    possible because the model was prefetched deterministically before any test
    body ran — a cache miss becomes a loud failure at a known point, not a flaky
    network dependency inside whichever test hits ``embed`` first."""

    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    vector = embed(["deterministic offline recall"])

    assert len(vector) == 1
    assert len(vector[0]) == EMBEDDING_DIMENSIONS


def test_coverage_is_measured_and_reported() -> None:
    """AC2: coverage tooling is present, configured, and run in CI."""

    pyproject = _load_pyproject()
    dev_dependencies = pyproject["dependency-groups"]["dev"]
    assert any(str(dep).startswith("pytest-cov") for dep in dev_dependencies)

    coverage_run = pyproject.get("tool", {}).get("coverage", {}).get("run", {})
    assert coverage_run.get("source"), "the coverage source packages must be configured"

    steps = _load_ci()["jobs"]["test"]["steps"]
    assert any("--cov" in _step_text(step) for step in steps), "CI must run tests with coverage"


def test_precommit_config_covers_the_ci_gates() -> None:
    """AC4: a pre-commit config exists and mirrors the ruff and mypy CI gates, so
    contributors catch those failures locally before pushing."""

    assert PRECOMMIT_CONFIG.exists()
    config = yaml.safe_load(PRECOMMIT_CONFIG.read_text(encoding="utf-8"))

    descriptors: list[str] = []
    for repo in config["repos"]:
        for hook in repo.get("hooks", []):
            fields = [str(hook.get(key, "")) for key in ("id", "name", "entry")]
            fields.append(str(repo.get("repo", "")))
            descriptors.append(" ".join(fields).lower())

    assert any("ruff" in text and "check" in text for text in descriptors), "ruff check gate"
    assert any("ruff" in text and "format" in text for text in descriptors), "ruff format gate"
    assert any("mypy" in text for text in descriptors), "mypy gate"


def test_editorconfig_matches_the_project_line_length() -> None:
    """AC4: an editorconfig exists and its Python line length matches the single
    source of truth for it — ruff's ``line-length`` — so editors and the gates
    agree."""

    assert EDITORCONFIG.exists()
    settings = _editorconfig_settings(EDITORCONFIG, "example.py")
    ruff_line_length = str(_load_pyproject()["tool"]["ruff"]["line-length"])

    assert settings.get("max_line_length") == ruff_line_length
    assert settings.get("indent_style") == "space"
    assert settings.get("indent_size") == "4"
