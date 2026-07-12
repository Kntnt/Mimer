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

# Ordered (pattern, replacement) rules. Earlier rules win on overlapping spans.
_RULES: list[tuple[re.Pattern[str], _Replacement]] = [
    # PEM private-key blocks, whole.
    (
        re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.DOTALL),
        "[REDACTED PRIVATE KEY]",
    ),
    # Credentials embedded in a URL: keep the scheme and host, drop user:pass.
    (re.compile(r"\b([a-zA-Z][\w+.\-]*://)[^\s:/@]+:[^\s:/@]+@"), r"\1[REDACTED]@"),
    # AWS access key id.
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),
    # GitHub personal-access / app tokens.
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), REDACTED),
    # OpenAI-style secret keys.
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), REDACTED),
    # Slack tokens.
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), REDACTED),
    # Assigned secrets: keep the key and quoting, redact the value.
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|auth)"
            r"(\s*[:=]\s*)(['\"]?)([^\s'\"]+)(\3)"
        ),
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{REDACTED}{m.group(5)}",
    ),
]


def redact(text: str) -> str:
    """Return ``text`` with recognised secrets replaced by a redaction marker."""

    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text
