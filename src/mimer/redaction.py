"""The redaction pass: strip secrets before anything is stored, summarised or
indexed. Capture, the digest and the transcript archive all run through it.

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
    # Google API keys.
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}"), REDACTED),
    # Google OAuth access tokens.
    (re.compile(r"\bya29\.[0-9A-Za-z_-]+"), REDACTED),
    # Stripe secret and restricted keys (the publishable `pk_` form is public).
    (re.compile(r"\b[sr]k_(?:live|test)_[0-9A-Za-z]{16,}\b"), REDACTED),
    # OpenAI-style secret keys.
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), REDACTED),
    # Slack tokens.
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), REDACTED),
    # Bearer tokens in an Authorization header: keep the scheme, drop the token.
    (re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]{16,}"), r"\1" + REDACTED),
    # `.npmrc` registry auth tokens: keep the key, redact the value.
    (re.compile(r"(?i)(_authToken\s*=\s*)[^\s'\"]+"), r"\1" + REDACTED),
    # Assigned secrets: keep the key and quoting, redact the value. The AWS
    # secret access key is listed explicitly because none of its interior words
    # sit on a word boundary, so `secret`/`access_key` alone never match it.
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|auth"
            r"|aws[_-]?secret[_-]?access[_-]?key)"
            r"(\s*[:=]\s*)(['\"]?)([^\s'\"]+)(\3)"
        ),
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{REDACTED}{m.group(5)}",
    ),
    # A bare AWS secret access key: a standalone 40-char base64 value. It is
    # only redacted when it carries a base64-only character (`+` or `/`) that a
    # hex git SHA or a Crockford-base32 ULID can never contain, so provenance
    # identifiers are never swept up.
    (
        re.compile(r"(?<![A-Za-z0-9+/])(?=[A-Za-z0-9]*[+/])[A-Za-z0-9+/]{40}(?![A-Za-z0-9+/=])"),
        REDACTED,
    ),
]


def redact(text: str) -> str:
    """Return ``text`` with recognised secrets replaced by a redaction marker."""

    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text
