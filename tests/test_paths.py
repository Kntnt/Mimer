"""Tests for store-location primitives (#25): identifiers that become store paths
must be bare, path-safe slugs before they ever touch the filesystem.
"""

from __future__ import annotations

import pytest

from mimer.paths import safe_identifier


@pytest.mark.parametrize(
    "value",
    [
        "session",
        "concept",
        "prefer-british-english",
        "profile-fact-0",
        "550e8400-e29b-41d4-a716-446655440000",
    ],
)
def test_safe_identifier_accepts_bare_slugs(value: str) -> None:
    """A bare slug — lowercase alphanumerics and hyphens — is returned unchanged."""

    assert safe_identifier(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "../evil",
        "../../etc/passwd",
        "a/b",
        "..",
        ".",
        "foo.md",
        "foo.bar",
        "with space",
        "UPPER",
        "under_score",
        "",
    ],
)
def test_safe_identifier_rejects_non_bare_identifiers(value: str) -> None:
    """Anything containing a slash, a dot, or other non-slug characters is rejected."""

    with pytest.raises(ValueError):
        safe_identifier(value)
