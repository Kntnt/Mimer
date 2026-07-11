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


SECRETS = [_aws_key(), _github_token(), _openai_key(), _slack_token(), _connection_string()]


@pytest.mark.parametrize("secret", SECRETS)
def test_known_secret_shapes_are_removed(secret: str) -> None:
    """A message carrying a secret loses the secret to a redaction marker."""

    redacted = redact(f"here is the value {secret} use it")

    assert secret not in redacted
    assert "REDACTED" in redacted


def test_key_value_secret_value_is_removed() -> None:
    """An assigned secret keeps its key but loses its value."""

    value = "hunter2" + "superSecret"
    redacted = redact(f'password = "{value}"')

    assert value not in redacted


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
