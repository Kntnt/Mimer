"""Assembled sample secrets, one per class the redaction pass must strip.

Each sample is built from fragments at import time so no complete secret literal
is committed to the repository (GitHub push protection scans file contents); the
fully-assembled value is what ``redact`` receives. ``sensitive`` is the substring
that must never survive redaction at any sink, while ``text`` is how the secret
would appear in a message (a bare key, or a labelled/quoted form for the classes
that only make sense in context).

The provenance identifiers below are the counter-examples: long tokens the rest
of Mimer relies on for citations, which redaction must leave untouched.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Sample:
    """One secret-class fixture: its in-message form and the part that must vanish."""

    name: str
    text: str
    sensitive: str


def _anthropic_key() -> str:
    return "sk-ant-" + "api03-" + "0123456789abcdefghij" + "KLMNOPQRSTUVWXYZ-_09" + "AA"


def _jwt() -> str:
    return (
        "eyJ"
        + "hbGciOiJIUzI1NiJ9"
        + "."
        + "eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        + "."
        + "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )


def _github_pat() -> str:
    # GitHub fine-grained PAT: the modern `github_pat_` prefix the `gh[pousr]_`
    # rule cannot reach (the third character `i` is outside its class).
    return (
        "github_pat_"
        + "11ABCDEFGHIJ0123456789"
        + "_"
        + "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVW"
    )


def _google_api_key() -> str:
    return "AIza" + "SyABCDEFGHIJKLMNOPQRSTUVWX012345678"


def _google_oauth_token() -> str:
    return "ya29." + "a0AfH6SMB" + "dEfGhIjKlMnOpQrStUv" + "0123456789_-xyz"


def _google_refresh_token() -> str:
    # Google OAuth refresh token: the `1//0` prefix, distinct from the `ya29.`
    # access-token form.
    return "1//0" + "eABCDEFGHIJKLMNOPQRSTUVWXYZ" + "abcdefghij0123456789_-"


def _stripe_key() -> str:
    return "sk_" + "live_" + "4eC39HqLyjWDarjt" + "T1zdp7dc"


def _stripe_webhook_secret() -> str:
    # Stripe webhook signing secret: the `whsec_` prefix the `[sr]k_` rule misses.
    return "whsec_" + "abcdefABCDEF0123456789abcdefABCD"


def _slack_app_token() -> str:
    # Slack app-level token: the `xapp-` prefix the `xox[baprs]-` rule misses.
    return "xapp-" + "1-A0123456789-" + "1234567890123-" + "abcdef0123456789abcdef0123456789"


def _bearer_token() -> str:
    return "aBcDeF0123456789xYzTokenValue"


def _basic_auth() -> str:
    # Base64 of a `user:password` pair carried by an `Authorization: Basic`
    # header — as leaky as a Bearer token, but the Bearer rule never sees it.
    return "dXNlcm5hbWU6c3VwZXJTZWNyZXRQYXNzd29yZA=="


def _npmrc_token() -> str:
    # A modern npm access/automation token: the `npm_` prefix and 36 characters.
    return "npm_" + "abcdef0123456789ABCDEF012345" + "6789abcd"


def _aws_secret_bare_value() -> str:
    # A real AWS secret access key is 40 random base64 characters; ~28% contain
    # neither `+` nor `/`. This one is all-alphanumeric (mixed case plus a
    # digit) so it exercises the bare rule's shape distinguisher, not its
    # base64-special shortcut.
    return "wJalrXUtnFEMI" + "K7MDENGbPxRfiCY" + "EXAMPLEKEYab"


def _aws_secret_bare_base64_value() -> str:
    # A 40-character AWS secret whose run carries a base64-only `/` but omits an
    # upper-case letter, so it fails the mixed-case shape branch and is redacted
    # only by the bare rule's base64 shortcut — pinning that shortcut against a
    # silent removal that the shape-branch fixtures would not catch.
    return "ab/defghij" + "0123456789" + "abcdefghij" + "0123456789"


def _env_db_password_value() -> str:
    return "hunter2" + "SuperSecret"


def _env_github_token_value() -> str:
    return "someOpaqueValue" + "123456"


def _env_stripe_api_key_value() -> str:
    return "rawValueGoes" + "Here123"


def _env_my_secret_value() -> str:
    return "topSecret" + "Value123"


def _aws_secret_labelled_value() -> str:
    # A 40-character all-lower-case-hex value: shaped exactly like a git SHA, so
    # the bare rule deliberately skips it. Only the explicit `aws_secret_access_key`
    # label in the assigned-secrets rule redacts it — this pins that path.
    return "deadbeef0123456789" + "abcdef0123456789abcdef"


def _url_credential() -> str:
    return "s3cr3tTokenValue123"


# One sample per secret class the issue lists as currently missed.
SAMPLES: list[Sample] = [
    Sample("anthropic-key", _anthropic_key(), _anthropic_key()),
    Sample("jwt", _jwt(), _jwt()),
    Sample("github-fine-grained-pat", _github_pat(), _github_pat()),
    Sample("google-api-key", _google_api_key(), _google_api_key()),
    Sample("google-oauth-token", _google_oauth_token(), _google_oauth_token()),
    Sample("google-refresh-token", _google_refresh_token(), _google_refresh_token()),
    Sample("stripe-key", _stripe_key(), _stripe_key()),
    Sample("stripe-webhook-secret", _stripe_webhook_secret(), _stripe_webhook_secret()),
    Sample("slack-app-token", _slack_app_token(), _slack_app_token()),
    Sample(
        "authorization-bearer",
        f"Authorization: Bearer {_bearer_token()}",
        _bearer_token(),
    ),
    Sample(
        "authorization-basic",
        f"Authorization: Basic {_basic_auth()}",
        _basic_auth(),
    ),
    Sample(
        "npmrc-authtoken",
        f"//registry.npmjs.org/:_authToken={_npmrc_token()}",
        _npmrc_token(),
    ),
    # npm's own serialisations that never carry the literal `_authToken`: the
    # dominant `.env`/CI `NPM_TOKEN=` form and a bare pasted token value.
    Sample("npm-token-env", f"NPM_TOKEN={_npmrc_token()}", _npmrc_token()),
    Sample("npm-token-bare", _npmrc_token(), _npmrc_token()),
    Sample(
        "aws-secret-labelled",
        f"aws_secret_access_key = {_aws_secret_labelled_value()}",
        _aws_secret_labelled_value(),
    ),
    Sample("aws-secret-bare", _aws_secret_bare_value(), _aws_secret_bare_value()),
    Sample(
        "aws-secret-bare-base64",
        _aws_secret_bare_base64_value(),
        _aws_secret_bare_base64_value(),
    ),
    # A sensitive keyword glued as the suffix of a longer identifier — the way a
    # developer actually pastes secrets from `.env`, `export` and CI config.
    Sample(
        "env-db-password",
        f"DB_PASSWORD={_env_db_password_value()}",
        _env_db_password_value(),
    ),
    Sample(
        "env-github-token",
        f"GITHUB_TOKEN={_env_github_token_value()}",
        _env_github_token_value(),
    ),
    Sample(
        "env-stripe-api-key",
        f"STRIPE_API_KEY={_env_stripe_api_key_value()}",
        _env_stripe_api_key_value(),
    ),
    Sample("env-my-secret", f"MY_SECRET={_env_my_secret_value()}", _env_my_secret_value()),
    Sample(
        "env-prefixed-aws-secret",
        f"MY_AWS_SECRET_ACCESS_KEY={_aws_secret_labelled_value()}",
        _aws_secret_labelled_value(),
    ),
    Sample(
        "single-credential-url",
        f"https://{_url_credential()}@internal.example.com/path",
        _url_credential(),
    ),
]

# Provenance identifiers that must survive redaction (never over-redacted).
GIT_SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
SHORT_GIT_SHA = "a1b2c3d4e5f6"
ULID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
