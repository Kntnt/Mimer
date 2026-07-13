"""The redaction pass: strip secrets before anything is stored, summarised or
indexed. Capture, the digest, the transcript archive, curated short-term writes
and the Concept-creation boundary all run through it.

Redaction is deliberately conservative — it targets well-known secret shapes and
credential-in-URL forms rather than blanket high-entropy stripping, so it does
not destroy provenance the rest of Mimer relies on (git SHAs, ordinary long
identifiers). It can be extended as new secret shapes appear.
"""

from __future__ import annotations

import re
from collections.abc import Callable

REDACTED = "[REDACTED]"

# A replacement is a literal string or a match-to-string function.
_Replacement = str | Callable[[re.Match[str]], str]

# Ordered (pattern, replacement) rules. Earlier rules win on overlapping spans:
# a broadly-shaped secret is caught by its specific rule before a later, more
# general one can only partially match it.
_RULES: list[tuple[re.Pattern[str], _Replacement]] = [
    # PEM private-key blocks, whole.
    (
        re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.DOTALL),
        "[REDACTED PRIVATE KEY]",
    ),
    # Credentials embedded in a URL: keep the scheme and host, drop the
    # credential — both the user:pass form and the single-token `token@host`.
    (re.compile(r"\b([a-zA-Z][\w+.\-]*://)[^\s:/@]+(?::[^\s:/@]+)?@"), r"\1[REDACTED]@"),
    # JSON Web Tokens: the `eyJ` header and its two dot-separated segments.
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), REDACTED),
    # Anthropic keys: the `sk-ant-` prefix the plain `sk-` rule cannot reach,
    # since the hyphen after `ant` falls outside its character class.
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"), REDACTED),
    # AWS access key id.
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),
    # GitHub personal-access / app tokens.
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), REDACTED),
    # GitHub fine-grained PATs: the `github_pat_` prefix the `gh[pousr]_` rule
    # cannot reach, since its third character `i` is outside that class.
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"), REDACTED),
    # GitLab tokens by their routable prefix: personal-access (`glpat-`), deploy
    # (`gldt-`) and runner (`glrt-`). The body carries `_` and `-`, so the token
    # runs to the first character outside the class rather than to a word boundary.
    (re.compile(r"\bgl(?:pat|dt|rt)-[A-Za-z0-9_-]{20,}"), REDACTED),
    # Google API keys.
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}"), REDACTED),
    # Google OAuth access tokens.
    (re.compile(r"\bya29\.[0-9A-Za-z_-]+"), REDACTED),
    # Google OAuth refresh tokens: the long-lived `1//0` form, distinct from the
    # short-lived `ya29.` access token.
    (re.compile(r"\b1//0[0-9A-Za-z_-]{30,}"), REDACTED),
    # Stripe secret/restricted keys and webhook signing secrets (the publishable
    # `pk_` form is public).
    (re.compile(r"\b(?:[sr]k_(?:live|test)_|whsec_)[0-9A-Za-z]{16,}\b"), REDACTED),
    # OpenAI project-scoped keys (`sk-proj-`, `sk-svcacct-`, `sk-admin-`): the
    # dashboard default since 2024, which the bare `sk-` rule below cannot reach —
    # the `-` after `proj`/`svcacct`/`admin` falls outside its character class, so
    # it stops at the prefix (4-7 chars, below the 20 minimum). The body carries
    # `_` and `-`, so it runs to the first character outside the class.
    (re.compile(r"\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,}"), REDACTED),
    # OpenAI-style secret keys (the classic bare `sk-` form).
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), REDACTED),
    # Slack tokens: bot/user/etc. (`xox[baprs]-`) and app-level (`xapp-`).
    (re.compile(r"\b(?:xox[baprs]|xapp)-[A-Za-z0-9-]{10,}\b"), REDACTED),
    # npm tokens by their own value prefix (`npm_` + 36 chars), like every other
    # class here — not by the `_authToken=` key name, which the common
    # `NPM_TOKEN=`, `export` and bare-pasted forms never carry.
    (re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"), REDACTED),
    # Bearer tokens in an Authorization header: keep the scheme, drop the token.
    (re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]{16,}"), r"\1" + REDACTED),
    # Basic auth in an Authorization header: keep the scheme, drop the base64
    # `user:password`. Anchored to the header so the ordinary English word
    # "Basic" in prose is never mistaken for a credential.
    (re.compile(r"(?i)(\bAuthorization:\s*Basic\s+)[A-Za-z0-9+/=]{16,}"), r"\1" + REDACTED),
    # `.npmrc` registry auth tokens: keep the key, redact the value.
    (re.compile(r"(?i)(_authToken\s*=\s*)[^\s'\"]+"), r"\1" + REDACTED),
    # Assigned secrets: keep the key and quoting, redact the value. An optional
    # identifier prefix (`DB_`, `GITHUB_`, `STRIPE_`, `MY_AWS_`) is allowed
    # before the keyword so the dominant `.env`/`export`/CI suffix forms
    # (`DB_PASSWORD=`, `GITHUB_TOKEN=`) match — the leading `\b` alone never
    # sits mid-identifier. The keyword must still be the immediate left of the
    # separator, so an ordinary `token_count = 5` is left untouched. The AWS
    # secret access key is listed explicitly because none of its interior words
    # sit on a word boundary, so `secret`/`access_key` alone never match it.
    # The value alternates on quoting: a quoted value runs to its matching
    # closing quote (so a whitespace-bearing passphrase is redacted whole, not
    # just its first word), an unquoted value is the leading non-space run.
    (
        re.compile(
            r"(?i)\b(?P<key>(?:[A-Za-z0-9]+[_.\-])*"
            r"(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|auth"
            r"|aws[_-]?secret[_-]?access[_-]?key))"
            r"(?P<sep>\s*[:=]\s*)"
            r"(?:(?P<quote>['\"])[^'\"]*(?P=quote)|[^\s'\"]+)"
        ),
        lambda m: f"{m['key']}{m['sep']}{m['quote'] or ''}{REDACTED}{m['quote'] or ''}",
    ),
    # A bare AWS secret access key: a standalone 40-char base64 value. Redacted
    # when it either carries a base64-only character (`+` or `/`) or mixes an
    # upper-case letter, a lower-case letter and a digit — the shape of a random
    # secret. A lower-case-hex git SHA (no upper case) and an upper-case
    # Crockford-base32 ULID (no lower case, and only 26 chars) both fail that
    # test, so 40-char provenance identifiers are never swept up.
    (
        re.compile(
            r"(?<![A-Za-z0-9+/])"
            r"(?:(?=[A-Za-z0-9+/]*[+/])"
            r"|(?=[A-Za-z0-9+/]*[a-z])(?=[A-Za-z0-9+/]*[A-Z])(?=[A-Za-z0-9+/]*[0-9]))"
            r"[A-Za-z0-9+/]{40}"
            r"(?![A-Za-z0-9+/=])"
        ),
        REDACTED,
    ),
]


def redact(text: str) -> str:
    """Return ``text`` with recognised secrets replaced by a redaction marker."""

    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text
