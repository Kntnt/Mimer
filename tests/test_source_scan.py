"""Source scan: storeio is the only path text takes to the store's files (#56).

Architecture-review candidate 5 (#55) made redaction structural at the storeio
write seam, so the module's contract — no text reaches the store's files
unredacted — holds only while storeio stays the single write path. The sibling
tickets settled that claim with a one-off grep; this promotes that grep to a
living guard. It walks the source for file-writing primitives outside the storeio
module and fails on any hit, because candidate 5's promise is specifically about
the sinks that do not exist yet: a forgetful future sink now fails a test rather
than silently leaking.

Two exemptions are documented and stated here:

- The capture spool (``hooks/stop.py``): the transient 0600 hand-off ADR 0020
  exempts — spooled straight to a temp file, consumed and deleted in a ``finally``
  by the detached capture process, and redacted only when its content is persisted
  behind the seam; the raw transcript exists outside the store regardless.
- The empty touch markers (``store.py``, ``db.py``, ``pause.py``): ``Path.touch``
  creates an empty file and writes no content, so it can carry no secret and has
  nothing to redact — categorically outside the seam's concern.
"""

from __future__ import annotations

import ast
from pathlib import Path

# The source tree scanned, and the one module that legitimately owns every
# file-writing primitive: the write seam itself.
SRC = Path(__file__).resolve().parent.parent / "src" / "mimer"
STOREIO_MODULE = "storeio.py"

# Flags that make an ``os.open`` a write rather than a read; a lock file opened
# read/create still writes (it creates), so O_CREAT counts.
_WRITE_FLAGS = ("O_WRONLY", "O_RDWR", "O_APPEND", "O_CREAT", "O_TRUNC")

# The capture spool: ``mkstemp`` plus the file-bound ``json.dump`` in the Stop
# hook, the one hand-off ADR 0020 exempts from the seam.
_CAPTURE_SPOOL = "hooks/stop.py"
_CAPTURE_SPOOL_PRIMITIVES = ("mkstemp", "json.dump")


def _dotted_name(node: ast.expr) -> str | None:
    """Return the dotted name of an attribute/name chain (``os.open``), else None."""

    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _has_write_flag(call: ast.Call) -> bool:
    """Whether an ``os.open`` call's flags argument names any write flag."""

    if len(call.args) < 2:
        return False
    source = ast.unparse(call.args[1])
    return any(flag in source for flag in _WRITE_FLAGS)


def _primitive(call: ast.Call) -> str | None:
    """Name the file-writing primitive a call is, or None if it writes no file.

    Recognises exactly the primitives the ticket enumerates: an ``os.open`` opened
    for writing, ``mkstemp``, ``write_text`` / ``write_bytes``, a file-bound
    ``json.dump``, plus ``touch`` (the empty-marker form, kept so the scan sees —
    and can then exempt — every way a file is brought into being).
    """

    func = call.func
    if not isinstance(func, ast.Attribute):
        return None

    attr = func.attr
    dotted = _dotted_name(func)

    if dotted == "os.open":
        return "os.open" if _has_write_flag(call) else None
    if attr == "mkstemp":
        return "mkstemp"
    if attr in ("write_text", "write_bytes"):
        return attr
    if dotted == "json.dump":
        return "json.dump"
    if attr == "touch":
        return "touch"
    return None


def _scan() -> list[tuple[str, int, str]]:
    """Every file-writing primitive call outside storeio, as (path, line, name)."""

    hits: list[tuple[str, int, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == STOREIO_MODULE:
            continue
        rel = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                primitive = _primitive(node)
                if primitive is not None:
                    hits.append((rel, node.lineno, primitive))
    return hits


def _is_exempt(rel: str, primitive: str) -> bool:
    """Whether a hit is one of the two documented exemptions."""

    if primitive == "touch":
        return True
    return rel == _CAPTURE_SPOOL and primitive in _CAPTURE_SPOOL_PRIMITIVES


def test_no_file_writing_primitive_bypasses_storeio() -> None:
    """Outside storeio, the only file-writing primitives are the two documented
    exemptions — so every other path to the store's files runs through the seam
    and its redaction (#56)."""

    violations = [(rel, line, prim) for rel, line, prim in _scan() if not _is_exempt(rel, prim)]
    assert violations == [], f"file-writing primitives bypass storeio: {violations}"


def test_scan_detects_the_documented_exemptions() -> None:
    """The scanner really fires: it finds both exemptions, so the guard above is
    proven to detect writes rather than pass vacuously over a scan that matches
    nothing (#56)."""

    hits = _scan()
    assert any(
        rel == _CAPTURE_SPOOL and prim in _CAPTURE_SPOOL_PRIMITIVES for rel, _, prim in hits
    ), "the capture-spool exemption was not detected — the scanner may be broken"
    assert any(prim == "touch" for _, _, prim in hits), "no empty touch marker was detected"
