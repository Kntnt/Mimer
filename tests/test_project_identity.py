"""Integration tests for project-id resolution against real git repositories,
covering ADR 0022's fixtures: multiple remotes, SSH/HTTPS equivalence, worktrees,
an inert ``.mimer`` file, no-git, a moved project, confirm-before-binding and
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


def test_mimer_marker_file_has_no_effect_on_identity(store_root: Path, tmp_path: Path) -> None:
    """A ``.mimer`` file is inert: a git project resolves by its remote exactly as if
    the file were any other file in the tree, never by the marker's contents
    (ADR 0022, #61)."""

    repo = init_repo(tmp_path / "repo", remotes={"origin": "git@github.com:x/repo.git"})
    (repo / ".mimer").write_text("hijacked-id\n", encoding="utf-8")

    result = resolve(repo, root=store_root)

    assert result.status is ResolutionStatus.CREATED
    assert result.project_id != "hijacked-id"
    assert result.project_id is not None
    record = Registry.load(store_root).find_by_id(result.project_id)
    assert record is not None
    assert "github.com/x/repo" in record.remotes


def test_mimer_marker_file_in_a_plain_dir_is_path_keyed(store_root: Path, tmp_path: Path) -> None:
    """In a non-git directory a ``.mimer`` file changes nothing: identity is path-keyed,
    not taken from the marker's declared id (ADR 0022, #61)."""

    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / ".mimer").write_text("declared-id\n", encoding="utf-8")

    result = resolve(plain, root=store_root)

    assert result.status is ResolutionStatus.CREATED
    assert result.project_id != "declared-id"


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


def test_unseen_directory_claiming_existing_memory_needs_confirmation(
    store_root: Path, tmp_path: Path
) -> None:
    """Confirm-before-binding survives the marker's removal: an unseen directory whose
    remote maps to one project while its path already belongs to another is refused,
    never bound silently, and the refusal names the exact confirm command and the
    candidate id (ADR 0022 §1, #61)."""

    # An existing project owns a sensitive remote — the memory a stray directory must
    # not attach to silently.
    secret = init_repo(tmp_path / "secret", remotes={"origin": "git@github.com:acme/secret.git"})
    candidate = resolve(secret, root=store_root)
    assert candidate.project_id is not None

    # A different directory is first known by its path alone, then acquires that same
    # remote — so its path and its remote now point at different projects.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert resolve(workspace, root=store_root).status is ResolutionStatus.CREATED
    init_repo(workspace, remotes={"origin": "git@github.com:acme/secret.git"})

    conflicted = resolve(workspace, root=store_root)

    assert conflicted.status is ResolutionStatus.NEEDS_CONFIRMATION
    assert conflicted.candidate_id == candidate.project_id
    # Nothing was bound: the candidate did not silently acquire the workspace path.
    record = Registry.load(store_root).find_by_id(candidate.project_id)
    assert record is not None
    assert str(workspace.resolve()) not in record.paths
    # The refusal is a resolvable state: it names the exact command and candidate id.
    assert f"mimer-manage confirm {candidate.project_id}" in confirm_hint(conflicted.candidate_id)


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

    # The candidate project owns a remote; a separate directory is path-keyed and
    # then acquires that remote, so path and remote disagree and binding is refused.
    candidate_repo = init_repo(
        tmp_path / "candidate", remotes={"origin": "git@github.com:x/api.git"}
    )
    candidate = resolve(candidate_repo, root=store_root)
    assert candidate.project_id is not None

    clone = tmp_path / "clone"
    clone.mkdir()
    resolve(clone, root=store_root)
    init_repo(clone, remotes={"origin": "git@github.com:x/api.git"})
    assert resolve(clone, root=store_root).status is ResolutionStatus.NEEDS_CONFIRMATION

    monkeypatch.setenv("MIMER_HOME", str(store_root))
    monkeypatch.chdir(clone)
    exit_code = main(["confirm", candidate.project_id])

    assert exit_code == 0
    assert candidate.project_id in capsys.readouterr().out
    after = resolve(clone, root=store_root)
    assert after.status is ResolutionStatus.RECOGNISED
    assert after.project_id == candidate.project_id


def test_confirm_resolves_path_remote_conflict_so_resolution_binds(
    store_root: Path, tmp_path: Path
) -> None:
    """When a path-keyed project acquires a remote already owned by another
    project, confirming the candidate must fold the path-keyed record into it, so
    the next resolution binds rather than looping back to NEEDS_CONFIRMATION — a
    bare additive alias would leave the old path owner competing forever (#34)."""

    # A path-keyed project is created first, at the app directory.
    app = tmp_path / "app"
    app.mkdir()
    path_keyed = resolve(app, root=store_root)
    assert path_keyed.status is ResolutionStatus.CREATED
    assert path_keyed.project_id is not None

    # A separate repo establishes the candidate project, owning the remote.
    candidate_clone = init_repo(
        tmp_path / "candidate", remotes={"origin": "git@github.com:x/api.git"}
    )
    candidate = resolve(candidate_clone, root=store_root)
    assert candidate.project_id is not None

    # The app directory acquires that same remote, so its path (owned by the
    # path-keyed project) and its remote (owned by the candidate) now disagree.
    init_repo(app, remotes={"origin": "git@github.com:x/api.git"})
    conflict = resolve(app, root=store_root)
    assert conflict.status is ResolutionStatus.NEEDS_CONFIRMATION
    assert conflict.candidate_id == candidate.project_id

    # The user paused capture on the path-keyed competitor — the record
    # confirm_link folds into the candidate. The candidate has not set capture, so
    # the fold must carry it across: confirming a project identity must not
    # re-enable a paused capture (#34).
    paused = Registry.load(store_root)
    paused.set_capture(path_keyed.project_id, enabled=False)
    paused.save()

    confirm_link(app, candidate.project_id, root=store_root)

    after = resolve(app, root=store_root)
    assert after.status is not ResolutionStatus.NEEDS_CONFIRMATION
    assert after.project_id == candidate.project_id

    # The competitor's paused capture survives the live confirm surface. This pins
    # confirm_link's merge arg order (source=competitor, target=candidate) — swap
    # it and the target-wins policy would invert end-to-end (#34).
    merged = Registry.load(store_root)
    assert merged.capture_enabled(candidate.project_id) is False


def test_confirm_resolves_ambiguous_remotes_so_resolution_binds(
    store_root: Path, tmp_path: Path
) -> None:
    """When a repo's remotes map to two projects (no single candidate), confirming
    the intended id must fold the competing project into it, so the next
    resolution binds rather than looping back to NEEDS_CONFIRMATION — adding both
    remotes to the chosen project while the other keeps its remote leaves the
    ambiguity intact (#34)."""

    # Two projects, each owning one remote; the first-created one is the competitor
    # that must precede the intended project to reproduce the loop.
    other_clone = init_repo(tmp_path / "other", remotes={"origin": "git@github.com:x/other.git"})
    resolve(other_clone, root=store_root)
    intended_clone = init_repo(
        tmp_path / "intended", remotes={"origin": "git@github.com:x/intended.git"}
    )
    intended = resolve(intended_clone, root=store_root)
    assert intended.project_id is not None

    # A repo carrying both remotes resolves to neither — an ambiguous conflict.
    both = init_repo(
        tmp_path / "both",
        remotes={
            "origin": "git@github.com:x/intended.git",
            "upstream": "git@github.com:x/other.git",
        },
    )
    ambiguous = resolve(both, root=store_root)
    assert ambiguous.status is ResolutionStatus.NEEDS_CONFIRMATION
    assert ambiguous.candidate_id is None

    confirm_link(both, intended.project_id, root=store_root)

    after = resolve(both, root=store_root)
    assert after.status is not ResolutionStatus.NEEDS_CONFIRMATION
    assert after.project_id == intended.project_id


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
