"""Unit tests for the redaction pass: secrets are stripped before anything is
stored (a load-bearing requirement — capture, digest and archive all go through
it).

The test secrets are assembled from fragments at runtime so no complete secret
literal is committed to the repository (GitHub push protection scans file
contents); ``redact`` still receives the fully-assembled strings.
"""

from __future__ import annotations

import pytest

from mimer.redaction import redact
from tests.secret_samples import GIT_SHA, SAMPLES, SHORT_GIT_SHA, ULID, Sample


def _aws_key() -> str:
    return "AKIA" + "IOSFODNN7" + "EXAMPLE"


def _github_token() -> str:
    return "ghp_" + "0123456789abcdefghij" + "klmnopqrstuvwxyzABCD"


def _openai_key() -> str:
    return "sk-" + "abcdefghijklmnopqrst" + "uvwxyz0123456789ABCDEF"


def _slack_token() -> str:
    return "xox" + "b-" + "123456789012-1234567890123-" + "abcdEFGHijklMNOPqrstUVwx"


def _connection_string() -> str:
    return "postgres://admin:" + "s3cr3tPassw0rd" + "@db.example.com:5432/prod"


def _stripe_key() -> str:
    return "sk_" + "live_" + "4eC39HqLyjWDarjtT1zdp7dc"


def _google_key() -> str:
    return "AIza" + "SyDummyGoogleApiKey" + "0123456789abcdef"


def _google_key_trailing_hyphen() -> str:
    # A valid-shape Google key whose final (35th) character is a hyphen — the case
    # a trailing word boundary cannot match against a following non-word character.
    return "AIza" + "SyDummyGoogleApiKey0123456789abc" + "de-"


def _jwt() -> str:
    return (
        "eyJ"
        + "hbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        + "."
        + "eyJzdWIiOiIxMjM0In0"
        + "."
        + "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )


SECRETS = [
    _aws_key(),
    _github_token(),
    _openai_key(),
    _slack_token(),
    _connection_string(),
    _stripe_key(),
    _google_key(),
    _google_key_trailing_hyphen(),
    _jwt(),
]


@pytest.mark.parametrize("secret", SECRETS)
def test_known_secret_shapes_are_removed(secret: str) -> None:
    """A message carrying a secret loses the secret to a redaction marker."""

    redacted = redact(f"here is the value {secret} use it")

    assert secret not in redacted
    assert "REDACTED" in redacted


def test_google_key_ending_in_hyphen_at_end_of_string_is_removed() -> None:
    """A hyphen-terminated Google key is redacted even with no character to its
    right — a trailing word boundary would silently miss this shape."""

    secret = _google_key_trailing_hyphen()
    redacted = redact(f"the key is {secret}")

    assert secret not in redacted
    assert "REDACTED" in redacted


def test_key_value_secret_value_is_removed() -> None:
    """An assigned secret keeps its key but loses its value."""

    value = "hunter2" + "superSecret"
    redacted = redact(f'password = "{value}"')

    assert value not in redacted


@pytest.mark.parametrize(
    "value",
    ["my secret pass phrase", "correct horse battery staple", "a b c d e"],
)
def test_quoted_multiword_secret_value_is_removed(value: str) -> None:
    """A quoted assigned secret whose value contains whitespace loses the whole
    value, not just the first word before the space."""

    for line in (f'password = "{value}"', f"password = '{value}'", f'PASSWORD="{value}"'):
        redacted = redact(line)

        assert value not in redacted
        assert "REDACTED" in redacted


def test_private_key_block_is_removed() -> None:
    """A PEM private-key block is redacted whole."""

    body = "MIIStuff" + "StuffStuff"
    pem = f"-----BEGIN RSA {'PRIVATE'} KEY-----\n{body}\n-----END RSA {'PRIVATE'} KEY-----"

    redacted = redact(f"my key:\n{pem}\nthanks")

    assert body not in redacted


def test_ordinary_prose_is_untouched() -> None:
    """Normal text is not mangled by redaction (no false positives on prose)."""

    text = "We decided to use sqlite-vec because it keeps the index in one file."

    assert redact(text) == text


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s.name)
def test_broadened_secret_classes_are_removed(sample: Sample) -> None:
    """Each secret class the audit found unredacted loses its sensitive part."""

    redacted = redact(f"here is the value {sample.text} use it")

    assert sample.sensitive not in redacted
    assert "REDACTED" in redacted


@pytest.mark.parametrize("identifier", [GIT_SHA, SHORT_GIT_SHA, ULID])
def test_provenance_identifiers_are_not_over_redacted(identifier: str) -> None:
    """Git SHAs and ULIDs — provenance the rest of Mimer cites — survive intact."""

    text = f"see commit {identifier} for the change"

    assert redact(text) == text


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s.name)
def test_redaction_is_idempotent(sample: Sample) -> None:
    """Redacting an already-redacted string is a no-op: ``redact(redact(s)) ==
    redact(s)`` across the secret corpus. The write seam (#55) leaves sink-level
    redaction upstream, so most content is redacted twice; this pins the property
    that lets the design lean on it."""

    once = redact(f"here is the value {sample.text} use it")

    assert redact(once) == once
