"""CI and local-developer-ergonomics guarantees (issue #46).

These tests are the executable contract for the project's continuous-integration
and tooling configuration: they parse the checked-in config files and assert the
properties the issue requires, so a later edit that silently drops macOS from the
matrix, removes coverage, un-pins the model fetch, or lets the local gates drift
from CI fails here instead of surfacing only after a push. The repo already tests
project files this way (see ``test_readme_documents_install_and_coexistence``).
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from editorconfig import get_properties

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


@pytest.mark.embedding
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
    """AC2: coverage tooling is present, configured to see the hook subprocesses,
    and both measured and reported in CI.

    The bare ``--cov`` measurement flag is asserted precisely: ``--cov-report``
    contains the substring ``--cov``, so a regression that dropped ``--cov`` and
    left only ``--cov-report=...`` would silently disable measurement while
    looking unchanged — exactly the drift this contract test must catch.
    ``parallel`` is required because most of Mimer's behaviour runs in the hook
    subprocesses the harness spawns; without it their coverage never combines
    into the report (see the harness's child-process coverage wiring)."""

    pyproject = _load_pyproject()
    dev_dependencies = pyproject["dependency-groups"]["dev"]
    assert any(str(dep).startswith("pytest-cov") for dep in dev_dependencies)

    coverage_run = pyproject.get("tool", {}).get("coverage", {}).get("run", {})
    assert coverage_run.get("source"), "the coverage source packages must be configured"
    assert coverage_run.get("parallel") is True, (
        "parallel mode is required to combine the hook subprocesses' coverage data"
    )

    step_texts = [_step_text(step) for step in _load_ci()["jobs"]["test"]["steps"]]
    measures = any(re.search(r"--cov(?![\w-])", text) for text in step_texts)
    reports = any("--cov-report" in text for text in step_texts)
    assert measures, "CI must enable coverage measurement with the bare --cov flag"
    assert reports, "CI must emit a coverage report (--cov-report)"


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
    agree.

    The settings are resolved with the real EditorConfig core (the same engine
    editors use) rather than a hand-rolled parser, so the verdict cannot drift
    from how an editor would actually read the file."""

    assert EDITORCONFIG.exists()
    settings = get_properties(str(REPO_ROOT / "example.py"))
    ruff_line_length = str(_load_pyproject()["tool"]["ruff"]["line-length"])

    assert settings.get("max_line_length") == ruff_line_length
    assert settings.get("indent_style") == "space"
    assert settings.get("indent_size") == "4"


def test_editorconfig_does_not_reindent_the_projects_toml() -> None:
    """AC4: the editorconfig must not tell an editor to reindent the project's
    own TOML. pyproject.toml is written with 4-space array items, so the resolved
    indent for TOML must be 4 — otherwise an editorconfig-aware editor reflows
    pyproject.toml to 2 spaces on the next edit, churning the very file the
    config lives beside."""

    settings = get_properties(str(PYPROJECT))

    assert settings.get("indent_size") == "4"


def test_harness_forwards_subprocess_coverage_env_when_measuring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2/finding #1: when the parent runs under coverage, the harness hands
    child hook processes the environment that makes coverage measure them —
    ``COVERAGE_PROCESS_START`` (so coverage's startup ``.pth`` activates) pointing
    at the project's coverage config, and ``COVERAGE_FILE`` so each child's data
    lands where pytest-cov combines it."""

    from tests import harness

    class _ActiveCoverage:
        @classmethod
        def current(cls) -> object:
            return object()

    monkeypatch.setattr(harness, "Coverage", _ActiveCoverage)
    monkeypatch.setenv("COVERAGE_FILE", str(Path("/tmp/mimer-cov/.coverage")))
    env = harness.subprocess_coverage_env()

    assert env["COVERAGE_PROCESS_START"] == str(PYPROJECT)
    assert env["COVERAGE_FILE"] == str(Path("/tmp/mimer-cov/.coverage").resolve())


def test_harness_adds_no_coverage_env_when_not_measuring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2/finding #1: outside a coverage run the harness must not set the
    coverage variables, or every hook subprocess would litter stray
    ``.coverage.*`` data files that nothing combines or cleans up."""

    from tests import harness

    class _InactiveCoverage:
        @classmethod
        def current(cls) -> None:
            return None

    monkeypatch.setattr(harness, "Coverage", _InactiveCoverage)

    assert harness.subprocess_coverage_env() == {}


def test_hook_subprocess_code_is_measured_by_coverage(tmp_path: Path) -> None:
    """AC2/finding #1: coverage counts code that runs only inside the hook
    subprocesses the harness spawns — most of Mimer's real behaviour. Without
    child-process coverage the report marks the hook modules as unrun even though
    the suite drives them heavily.

    The hook is driven with the re-entrancy guard set, so it exercises the
    runner's guarded early-return path — executed only in the child, never in
    this test process — without loading the embedding model. ``runner.py``
    appearing in the combined data therefore proves child-process coverage is
    active."""

    import coverage
    from coverage.exceptions import NoDataError

    from tests.harness import run_hook, session_end_payload

    data_file = tmp_path / ".coverage"
    result = run_hook(
        "SessionEnd",
        session_end_payload(),
        store_root=tmp_path / "store",
        cwd=tmp_path,
        guard=True,
        extra_env={
            "COVERAGE_PROCESS_START": str(PYPROJECT),
            "COVERAGE_FILE": str(data_file),
        },
    )
    assert result.returncode == 0

    combiner = coverage.Coverage(data_file=str(data_file))
    try:
        combiner.combine()
    except NoDataError:
        pass
    measured = {Path(path).name for path in combiner.get_data().measured_files()}

    assert "runner.py" in measured, (
        "the hook runner runs only in the child process, so measuring it proves "
        "the harness enables child-process coverage"
    )


def test_prefetch_runs_only_when_an_embedding_test_is_collected() -> None:
    """AC3/finding #2: the session model prefetch is gated on collection, so a
    targeted run of pure unit tests never loads the model. The gate keys off the
    ``embedding`` marker, applied to the tests that embed directly or via a hook
    subprocess."""

    from tests.conftest import needs_embedding_model

    class _Item:
        def __init__(self, *, marked: bool) -> None:
            self._marked = marked

        def get_closest_marker(self, name: str) -> object | None:
            return object() if self._marked and name == "embedding" else None

    assert needs_embedding_model([_Item(marked=True), _Item(marked=False)]) is True
    assert needs_embedding_model([_Item(marked=False)]) is False
    assert needs_embedding_model([]) is False
