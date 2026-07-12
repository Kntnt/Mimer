"""Opt-in packaging smoke test (Stage 8).

The Stage 8 gate exercises install and uninstall in-process (``run_install`` and
friends). It never runs the built wheel's ``mimer-*`` console scripts or a hook
through the packaged entry points, so a broken ``[project.scripts]`` mapping, a
missing package file, or a wheel that omits a module would still pass CI. This
test builds the wheel, installs it into a throwaway virtualenv, and drives the
console scripts and a real hook from that install.

It is skipped by default (set ``MIMER_PACKAGING=1``) because building and
installing a fresh environment is slow. It needs no ``claude`` binary.
"""

from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path

import pytest

# The project under test — the checkout this test file lives in.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Gate the whole module: opt in with MIMER_PACKAGING=1.
pytestmark = [
    pytest.mark.packaging,
    pytest.mark.skipif(
        os.environ.get("MIMER_PACKAGING") != "1",
        reason="opt-in: set MIMER_PACKAGING=1 to build and install the wheel",
    ),
]


def _declared_console_scripts() -> list[str]:
    """The console-script names declared in ``pyproject.toml`` — the contract the
    install must materialise."""

    manifest = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return sorted(manifest["project"]["scripts"].keys())


def _resolved_entry_point_targets(venv_python: Path) -> list[str]:
    """The names of the installed ``mimer`` console scripts whose target resolves.

    Runs inside the fresh venv and, for every ``console_scripts`` entry point the
    installed distribution declares, calls ``EntryPoint.load()`` — which imports
    the ``module`` and binds the ``attr`` of a ``module:attr`` mapping. A renamed
    or typo'd ``[project.scripts]`` target therefore fails here, where a mere
    ``bin/<script>`` existence check waves it through: the wrapper file is created
    regardless and only errors when the script is actually executed.
    """

    probe = (
        "import importlib.metadata as md, json\n"
        "resolved = []\n"
        "for ep in md.distribution('mimer').entry_points:\n"
        "    if ep.group != 'console_scripts':\n"
        "        continue\n"
        "    ep.load()\n"
        "    resolved.append(ep.name)\n"
        "print(json.dumps(sorted(resolved)))\n"
    )
    completed = _run([str(venv_python), "-c", probe], timeout=120)
    return list(json.loads(completed.stdout))


def _run(
    command: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess, capturing text output and raising with its stderr on a
    non-zero exit so a failure names what actually went wrong."""

    completed = subprocess.run(
        command, capture_output=True, text=True, cwd=cwd, env=env, timeout=timeout
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stderr}"
        )
    return completed


def _build_and_install(tmp_path: Path) -> Path:
    """Build the wheel and install it into a fresh virtualenv; return its bin dir."""

    # Build exactly the wheel a release would ship, into an isolated dist dir.
    dist = tmp_path / "dist"
    _run(["uv", "build", "--wheel", "--out-dir", str(dist)], cwd=str(PROJECT_ROOT), timeout=600)
    wheels = list(dist.glob("mimer-*.whl"))
    assert len(wheels) == 1, f"expected one wheel, found {wheels}"

    # Create a throwaway virtualenv and install the built wheel (and its declared
    # runtime dependencies) into it — the packaged artefact, not the source tree.
    venv = tmp_path / "venv"
    _run(["uv", "venv", str(venv)], timeout=120)
    venv_python = venv / "bin" / "python"
    _run(["uv", "pip", "install", "--python", str(venv_python), str(wheels[0])], timeout=600)

    return venv / "bin"


def test_wheel_install_exposes_and_runs_console_scripts_and_a_hook(tmp_path: Path) -> None:
    """The built wheel installs every declared console script, and the packaged
    entry points actually run: ``mimer-uninstall`` and the ``mimer-session-start``
    hook execute from the fresh install."""

    bin_dir = _build_and_install(tmp_path)

    # Every declared console script materialises as a wrapper file in the venv.
    for script in _declared_console_scripts():
        assert (bin_dir / script).exists(), f"missing console script: {script}"

    # And every one of those entry points points at a target that actually
    # resolves — the check the bare ``.exists()`` above cannot make, since a
    # broken ``[project.scripts]`` mapping still ships a wrapper that only fails
    # on execution. This is the regression the ticket names: a renamed target
    # would keep the file check green while breaking the hook it backs.
    assert _resolved_entry_point_targets(bin_dir / "python") == _declared_console_scripts()

    # A store and env isolated from the real ~/.mimer; the guard var must not leak
    # in from the outer pytest run.
    store = tmp_path / "store"
    project = tmp_path / "project"
    project.mkdir()
    env = {**os.environ, "MIMER_HOME": str(store)}
    env.pop("MIMER_GUARD", None)

    # A console script runs end to end: uninstall leaves its pointer in the store.
    _run([str(bin_dir / "mimer-uninstall")], env=env, timeout=120)
    assert (store / "MIMER-UNINSTALLED.md").exists()

    # A real hook runs through the packaged entry point and emits its injection.
    payload = {
        "session_id": "packaging-smoke",
        "transcript_path": str(tmp_path / "transcript.jsonl"),
        "cwd": str(project),
        "hook_event_name": "SessionStart",
        "source": "startup",
    }
    completed = subprocess.run(
        [str(bin_dir / "mimer-session-start")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    output = json.loads(completed.stdout)
    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
