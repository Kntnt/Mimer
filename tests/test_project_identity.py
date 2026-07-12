"""Integration tests for project-id resolution against real git repositories,
covering ADR 0008's fixtures: multiple remotes, SSH/HTTPS equivalence,
worktrees, a monorepo marker, no-git, a moved project, confirmed binding and
reconciliation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mimer.manage import main
from mimer.project import ResolutionStatus, confirm_hint, confirm_link, resolve
from mimer.registry import Registry
from mimer.store import ensure_store
from tests.gitutil import add_worktree, init_repo


def test_git_project_created_then_recognised(store_root: Path, tmp_path: Path) -> None:
    """A git project is created once and recognised (same id) on re-runs."""

    repo = init_repo(tmp_path / "repo", remotes={"origin": "git@github.com:x/repo.git"})

    first = resolve(repo, root=store_root)
    assert first.status is ResolutionStatus.CREATED
    second = resolve(repo, root=store_root)

    assert second.status is ResolutionStatus.RECOGNISED
    assert second.project_id == first.project_id


def test_registry_records_remote_and_path_aliases(store_root: Path, tmp_path: Path) -> None:
    """Resolution records the project's remote and path as registry aliases."""

    repo = init_repo(tmp_path / "repo", remotes={"origin": "git@github.com:x/repo.git"})

    result = resolve(repo, root=store_root)

    assert result.project_id is not None
    record = Registry.load(store_root).find_by_id(result.project_id)
    assert record is not None
    assert "github.com/x/repo" in record.remotes
    assert str(repo.resolve()) in record.paths


def test_ssh_and_https_clones_share_identity(store_root: Path, tmp_path: Path) -> None:
    """Two clones addressing one repo over SSH and HTTPS resolve to one id."""

    ssh_clone = init_repo(tmp_path / "ssh", remotes={"origin": "git@github.com:x/repo.git"})
    https_clone = init_repo(tmp_path / "https", remotes={"origin": "https://github.com/x/repo.git"})

    first = resolve(ssh_clone, root=store_root)
    second = resolve(https_clone, root=store_root)

    assert second.project_id == first.project_id
    assert second.status is ResolutionStatus.RECONCILED


def test_multiple_remotes_prefer_origin(store_root: Path, tmp_path: Path) -> None:
    """With several remotes the id derives from origin, and all are recorded."""

    repo = init_repo(
        tmp_path / "repo",
        remotes={
            "upstream": "git@github.com:upstream/repo.git",
            "origin": "git@github.com:me/repo.git",
        },
    )

    result = resolve(repo, root=store_root)

    assert result.project_id is not None
    assert "me-repo" in result.project_id
    record = Registry.load(store_root).find_by_id(result.project_id)
    assert record is not None
    assert "github.com/me/repo" in record.remotes
    assert "github.com/upstream/repo" in record.remotes


def test_worktrees_share_identity(store_root: Path, tmp_path: Path) -> None:
    """A linked worktree shares the main checkout's identity via the remote."""

    repo = init_repo(
        tmp_path / "repo", remotes={"origin": "git@github.com:x/repo.git"}, commit=True
    )
    worktree = add_worktree(repo, tmp_path / "wt")

    main = resolve(repo, root=store_root)
    linked = resolve(worktree, root=store_root)

    assert linked.project_id == main.project_id


def test_monorepo_subproject_marker_gets_separate_identity(
    store_root: Path, tmp_path: Path
) -> None:
    """A marker in a monorepo sub-directory yields a separate id from the repo."""

    repo = init_repo(tmp_path / "mono", remotes={"origin": "git@github.com:x/mono.git"})
    service = repo / "services" / "billing"
    service.mkdir(parents=True)
    (service / ".mimer").write_text("billing-service\n", encoding="utf-8")

    repo_result = resolve(repo, root=store_root)
    service_result = resolve(service, root=store_root)

    assert service_result.status is ResolutionStatus.CREATED
    assert service_result.project_id == "billing-service"
    assert service_result.project_id != repo_result.project_id


def test_non_git_project_is_path_keyed_and_stable(store_root: Path, tmp_path: Path) -> None:
    """A project with no git resolves by path and is stable across re-runs."""

    plain = tmp_path / "plain"
    plain.mkdir()

    first = resolve(plain, root=store_root)
    second = resolve(plain, root=store_root)

    assert first.status is ResolutionStatus.CREATED
    assert second.status is ResolutionStatus.RECOGNISED
    assert second.project_id == first.project_id


def test_moved_git_project_keeps_identity(store_root: Path, tmp_path: Path) -> None:
    """The same repo at a new path keeps its id and records the new path."""

    original = init_repo(tmp_path / "a", remotes={"origin": "git@github.com:x/repo.git"})
    first = resolve(original, root=store_root)

    moved = init_repo(tmp_path / "b", remotes={"origin": "git@github.com:x/repo.git"})
    second = resolve(moved, root=store_root)

    assert second.project_id == first.project_id
    assert second.status is ResolutionStatus.RECONCILED
    assert first.project_id is not None
    record = Registry.load(store_root).find_by_id(first.project_id)
    assert record is not None
    assert str(moved.resolve()) in record.paths


def test_cloned_marker_to_existing_memory_needs_confirmation(
    store_root: Path, tmp_path: Path
) -> None:
    """A marker claiming an existing project from a new directory is not bound
    silently — it demands confirmation."""

    # Seed an existing project whose id a cloned marker will claim.
    from mimer.store import ensure_store

    ensure_store(store_root)
    reg = Registry.load(store_root)
    reg.create("secret-client", remotes=[], paths=[str((tmp_path / "orig").resolve())])
    reg.save()

    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / ".mimer").write_text("secret-client\n", encoding="utf-8")

    result = resolve(clone, root=store_root)

    assert result.status is ResolutionStatus.NEEDS_CONFIRMATION
    assert result.candidate_id == "secret-client"
    # Nothing was bound: the clone path is not added to the project.
    record = Registry.load(store_root).find_by_id("secret-client")
    assert record is not None
    assert str(clone.resolve()) not in record.paths


def test_unrecognised_marker_starts_new_project(store_root: Path, tmp_path: Path) -> None:
    """A marker whose id is unknown starts a fresh project with that id."""

    directory = tmp_path / "fresh"
    directory.mkdir()
    (directory / ".mimer").write_text("brand-new-thing\n", encoding="utf-8")

    result = resolve(directory, root=store_root)

    assert result.status is ResolutionStatus.CREATED
    assert result.project_id == "brand-new-thing"


def test_confirm_link_binds_after_confirmation(store_root: Path, tmp_path: Path) -> None:
    """After explicit confirmation the claimed directory links to the project."""

    from mimer.store import ensure_store

    ensure_store(store_root)
    reg = Registry.load(store_root)
    reg.create("shared", remotes=[], paths=[str((tmp_path / "orig").resolve())])
    reg.save()

    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / ".mimer").write_text("shared\n", encoding="utf-8")
    assert resolve(clone, root=store_root).status is ResolutionStatus.NEEDS_CONFIRMATION

    confirm_link(clone, "shared", root=store_root)

    after = resolve(clone, root=store_root)
    assert after.status is ResolutionStatus.RECOGNISED
    assert after.project_id == "shared"


def test_adding_remote_to_path_keyed_project_reconciles(store_root: Path, tmp_path: Path) -> None:
    """Adding a remote to an existing path-keyed project reconciles onto it
    rather than minting a fresh, empty id."""

    project = tmp_path / "proj"
    project.mkdir()
    created = resolve(project, root=store_root)
    assert created.status is ResolutionStatus.CREATED

    init_repo(project, remotes={"origin": "git@github.com:x/proj.git"})
    reconciled = resolve(project, root=store_root)

    assert reconciled.project_id == created.project_id
    assert reconciled.status is ResolutionStatus.RECONCILED
    assert created.project_id is not None
    record = Registry.load(store_root).find_by_id(created.project_id)
    assert record is not None
    assert "github.com/x/proj" in record.remotes


def test_confirm_hint_names_command_and_candidate() -> None:
    """The needs-confirmation hint names the exact command and the candidate id,
    so a refused directory is a legible, resolvable state rather than a dead end
    (#34)."""

    hint = confirm_hint("secret-client")

    assert "mimer-manage confirm secret-client" in hint


def test_confirm_hint_without_candidate_still_names_the_command() -> None:
    """When resolution identified no single candidate (ambiguous remotes), the
    hint still names the confirm command so the user has a way forward (#34)."""

    hint = confirm_hint(None)

    assert "mimer-manage confirm" in hint


def test_confirm_command_links_pending_identity_so_memory_proceeds(
    store_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`mimer-manage confirm <id>` binds this directory to the candidate project,
    after which resolution recognises it — so injection and capture proceed (#34)."""

    ensure_store(store_root)
    registry = Registry.load(store_root)
    registry.create("shared", paths=[str((tmp_path / "orig").resolve())])
    registry.save()

    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / ".mimer").write_text("shared\n", encoding="utf-8")
    assert resolve(clone, root=store_root).status is ResolutionStatus.NEEDS_CONFIRMATION

    monkeypatch.setenv("MIMER_HOME", str(store_root))
    monkeypatch.chdir(clone)
    exit_code = main(["confirm", "shared"])

    assert exit_code == 0
    assert "shared" in capsys.readouterr().out
    after = resolve(clone, root=store_root)
    assert after.status is ResolutionStatus.RECOGNISED
    assert after.project_id == "shared"


def test_confirm_command_rejects_unknown_candidate_with_clean_message(
    store_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`mimer-manage confirm` answers an unknown candidate id with a one-line
    rejection and a non-zero exit, never a raw traceback (#34)."""

    ensure_store(store_root)
    fresh = tmp_path / "fresh"
    fresh.mkdir()

    monkeypatch.setenv("MIMER_HOME", str(store_root))
    monkeypatch.chdir(fresh)
    exit_code = main(["confirm", "no-such-project"])

    assert exit_code != 0
    out = capsys.readouterr().out
    assert out.startswith("Mimer:")
    assert "no-such-project" in out
    assert "Traceback" not in out
