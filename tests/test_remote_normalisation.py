"""Unit tests for remote-URL normalisation — the lowest layer of project
identity. SSH and HTTPS forms of one remote must collapse to one key (ADR 0008).
"""

from __future__ import annotations

import pytest

from mimer.project import normalise_remote

# Every form below denotes the same GitHub repository and must normalise equally.
EQUIVALENT_FORMS = [
    "git@github.com:Kntnt/Mimer.git",
    "https://github.com/Kntnt/Mimer.git",
    "https://github.com/Kntnt/Mimer",
    "ssh://git@github.com/Kntnt/Mimer.git",
    "ssh://git@github.com:22/Kntnt/Mimer.git",
    "https://user:token@github.com/Kntnt/Mimer.git",
    "git://github.com/Kntnt/Mimer.git",
    "GIT@GitHub.com:Kntnt/Mimer.git",
]


@pytest.mark.parametrize("url", EQUIVALENT_FORMS)
def test_ssh_https_and_credentialled_forms_are_equivalent(url: str) -> None:
    """All spellings of one remote normalise to a single host-lowercased key."""

    assert normalise_remote(url) == "github.com/Kntnt/Mimer"


def test_host_is_lowercased_but_path_case_preserved() -> None:
    """Only the host is lowercased (ADR 0008); the path keeps its case."""

    assert normalise_remote("git@GITHUB.com:Kntnt/Mimer.git") == "github.com/Kntnt/Mimer"


def test_trailing_git_and_slashes_stripped() -> None:
    """A trailing ``.git`` and trailing slashes are removed."""

    assert normalise_remote("https://example.org/a/b/") == "example.org/a/b"
    assert normalise_remote("https://example.org/a/b.git") == "example.org/a/b"


def test_distinct_repositories_stay_distinct() -> None:
    """Different repositories must not collide."""

    assert normalise_remote("git@github.com:Kntnt/Mimer.git") != normalise_remote(
        "git@github.com:Kntnt/Other.git"
    )


def test_blank_remote_is_empty() -> None:
    """A blank remote normalises to the empty string."""

    assert normalise_remote("   ") == ""
