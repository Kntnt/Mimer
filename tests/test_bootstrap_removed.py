"""Guards that bootstrap — the import of pre-existing Claude Code history — is
excised from the product (ADR 0026, issue #60).

Mimer starts from zero and fills forward through capture and distillation, so
the ``mimer-bootstrap`` command, the ``mimer.bootstrap`` module, the per-project
import state the registry carried, and the transcript enumeration only bootstrap
used must all be gone. These are structural assertions over the packaged surface
and the public module API, complementing the doc-truthfulness sweep that checks
the README and changelog agree with the shipped command surface.
"""

from __future__ import annotations

import importlib.util
import tomllib
from dataclasses import fields
from pathlib import Path

from mimer import transcript
from mimer.registry import ProjectRecord, Registry

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_mimer_bootstrap_is_not_a_packaged_command() -> None:
    """No ``mimer-bootstrap`` console script survives in the packaged surface."""

    scripts = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["scripts"]
    assert "mimer-bootstrap" not in scripts


def test_bootstrap_module_is_removed() -> None:
    """The ``mimer.bootstrap`` module no longer exists to be imported."""

    assert importlib.util.find_spec("mimer.bootstrap") is None


def test_registry_carries_no_per_project_import_state() -> None:
    """The registry's per-project import state — the field and its accessors —
    is gone, so a merge can no longer carry it (issue #60)."""

    assert "import_state" not in {field.name for field in fields(ProjectRecord)}
    assert not hasattr(Registry, "import_state")
    assert not hasattr(Registry, "set_import_state")


def test_transcript_exposes_no_bulk_enumeration() -> None:
    """The whole-transcript enumeration only bootstrap used (``all_exchanges``) is
    removed; per-exchange capture and the digest keep their own readers."""

    assert not hasattr(transcript, "all_exchanges")
