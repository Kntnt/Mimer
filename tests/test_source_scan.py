"""Source scan: storeio is the only path text takes to the store's files (#56).

Architecture-review candidate 5 (#55) made redaction structural at the storeio
write seam, so the module's contract — no text reaches the store's files
unredacted — holds only while storeio stays the single write path. The sibling
tickets settled that claim with a one-off grep; this promotes that grep to a
living guard. It walks the source for file-writing primitives outside the storeio
module and fails on any hit, because candidate 5's promise is specifically about
the sinks that do not exist yet: a forgetful future sink now fails a test rather
than silently leaking.

Three exemptions are documented and stated here:

- The capture spool (``hooks/stop.py``): the transient 0600 hand-off ADR 0020
  exempts — spooled straight to a temp file, consumed and deleted in a ``finally``
  by the detached capture process, and redacted only when its content is persisted
  behind the seam; the raw transcript exists outside the store regardless.
- The empty touch markers (``store.py``, ``db.py``, ``pause.py``): ``Path.touch``
  creates an empty file and writes no content, so it can carry no secret and has
  nothing to redact — categorically outside the seam's concern.
- The native-memory switch (``native_memory.py``): its atomic write stages the
  updated ``.claude/settings.json`` in a sibling temp file (``mkstemp``) and swaps it
  in with ``os.replace``, targeting the *project's* own config — Claude Code's, not a
  store file — so the store's redaction seam does not apply. It mirrors
  storeio.write_atomic rather than routing through it, because that seam would run
  redaction over the user's *other* settings and could corrupt a secret-shaped value
  there; only the atomicity is wanted here, not the redaction (ADR 0025, #64).
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

# Characters that make an ``open`` / ``Path.open`` mode a write rather than a read:
# write, append, exclusive-create and update all mutate the file; plain read
# ("r", "rb") carries none of them.
_WRITE_MODE_CHARS = ("w", "a", "x", "+")

# The capture spool: ``mkstemp``, the file-bound ``json.dump`` and the builtin
# ``open`` that writes it, all in the Stop hook — the one hand-off ADR 0020 exempts
# from the seam.
_CAPTURE_SPOOL = "hooks/stop.py"
_CAPTURE_SPOOL_PRIMITIVES = ("mkstemp", "json.dump", "open")

# The native-memory switch: the ``mkstemp`` that stages ``autoMemoryEnabled`` for an
# atomic swap into the project's own .claude/settings.json — a config file outside the
# store, so outside the redaction seam (ADR 0025, #64).
_NATIVE_MEMORY = "native_memory.py"
_NATIVE_MEMORY_PRIMITIVES = ("mkstemp",)


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


def _opens_for_writing(call: ast.Call, *, mode_index: int) -> bool:
    """Whether an ``open`` / ``Path.open`` call opens its file for writing.

    The mode is a ``mode=`` keyword or the positional argument at ``mode_index``
    (1 for the builtin ``open(path, mode)``, 0 for the bound ``path.open(mode)``); an
    absent mode is the read default and writes nothing. A write, append,
    exclusive-create or update mode carries one of :data:`_WRITE_MODE_CHARS`.
    """

    mode = next(
        (keyword.value for keyword in call.keywords if keyword.arg == "mode"),
        call.args[mode_index] if len(call.args) > mode_index else None,
    )
    if mode is None:
        return False
    source = ast.unparse(mode)
    return any(char in source for char in _WRITE_MODE_CHARS)


def _primitive(call: ast.Call) -> str | None:
    """Name the file-writing primitive a call is, or None if it writes no file.

    Recognises the primitives the ticket enumerates — an ``os.open`` opened for
    writing, ``mkstemp``, ``write_text`` / ``write_bytes``, a file-bound
    ``json.dump``, plus ``touch`` (the empty-marker form, kept so the scan sees —
    and can then exempt — every way a file is brought into being) — together with
    the builtin ``open`` and ``Path.open`` in a write mode: the commonest way a file
    is written and the lower-level sibling of ``write_text``, so a future
    ``open(path, "w")`` sink fails the guard instead of leaking. Pure relocations
    (``os.replace``, ``os.rename``) are deliberately out of scope: they move an
    already-written file and introduce no new text, so they carry nothing the
    redaction seam could act on.
    """

    func = call.func

    # The builtin ``open(path, mode)`` is an ``ast.Name``, not an attribute, so it is
    # matched before the attribute dispatch below; a write mode makes it a sink.
    if isinstance(func, ast.Name) and func.id == "open":
        return "open" if _opens_for_writing(call, mode_index=1) else None

    if not isinstance(func, ast.Attribute):
        return None

    attr = func.attr
    dotted = _dotted_name(func)

    if dotted == "os.open":
        return "os.open" if _has_write_flag(call) else None
    if attr == "open":
        return "open" if _opens_for_writing(call, mode_index=0) else None
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
    """Whether a hit is one of the three documented exemptions."""

    if primitive == "touch":
        return True
    if rel == _CAPTURE_SPOOL and primitive in _CAPTURE_SPOOL_PRIMITIVES:
        return True
    return rel == _NATIVE_MEMORY and primitive in _NATIVE_MEMORY_PRIMITIVES


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
    assert any(
        rel == _NATIVE_MEMORY and prim in _NATIVE_MEMORY_PRIMITIVES for rel, _, prim in hits
    ), "the native-memory write was not detected — its exemption would pass vacuously"


def test_scan_catches_builtin_and_path_open_in_write_mode() -> None:
    """The scanner recognises the commonest write form — builtin ``open`` and
    ``Path.open`` in a write, append, exclusive-create or update mode — so a future
    sink that reaches the store through ``open(path, "w")`` fails this guard instead
    of leaking. The read-mode and mode-less forms write nothing and stay invisible,
    so the guard flags writes without tripping on reads (#56)."""

    def primitive_of(expression: str) -> str | None:
        node = ast.parse(expression, mode="eval").body
        assert isinstance(node, ast.Call)
        return _primitive(node)

    # Every write form is caught, on the builtin and on the bound ``.open`` alike —
    # the sibling of ``write_text`` the scan previously missed.
    assert primitive_of('open(p, "w")') == "open"
    assert primitive_of('open(p, "a")') == "open"
    assert primitive_of('open(p, mode="x")') == "open"
    assert primitive_of('p.open("w")') == "open"
    assert primitive_of('p.open(mode="r+")') == "open"

    # A read-mode or mode-less open writes nothing, so it must not be flagged.
    assert primitive_of("open(p)") is None
    assert primitive_of('open(p, "r")') is None
    assert primitive_of('p.open("rb")') is None
