"""Permanent memory: the OKF bundle of curated Concepts (Stage 5a).

The bundle is ``~/.mimer/permanent/`` — a directory of Markdown Concept files
with YAML frontmatter, per the vendored OKF v0.1 spec and Mimer's profile
(``docs/okf-profile.md``). On top of OKF, Mimer adds a stable ULID ``id`` that
survives rename, ``origin``/``scope`` for confidentiality (ADR 0013),
``pinned`` for the profile, and the ``status``/``supersedes`` supersession
chain (ADR 0015). Every write regenerates ``index.md`` and keeps the search
index in step; renames rewrite inbound links atomically.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from mimer.failure_log import log_failure
from mimer.framing import neutralise
from mimer.paths import safe_identifier, store_root
from mimer.redaction import redact
from mimer.registry import project_dir  # noqa: F401  (kept for symmetry of store layout)
from mimer.store import ensure_store
from mimer.storeio import project_lock, write_atomic
from mimer.tombstones import is_suppressed, load_tombstones, write_tombstone

BUNDLE_DIRNAME = "permanent"
INDEX_FILENAME = "index.md"
OKF_VERSION = "0.1"

# Everything pinned is injected into every session, so the profile is capped and
# the oldest pinned Concept is demoted when the cap is exceeded (ADR 0015).
PINNED_CAP = 10

# One store-level lock serialises all bundle mutations.
_BUNDLE_LOCK = "__bundle__"

# Concept files already reported as unparseable in this process, so a single bad
# file logs one actionable line rather than one per list_concepts call — and
# list_concepts is called many times per session (recall, manifest, injection).
_LOGGED_SKIPS: set[Path] = set()

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CITATION_RE = re.compile(r'^\[\d+\]\s+\[.*?\]\((.*?)\)\s+—\s+"(.*?)"\s+\((.*?)\)', re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


class ConfirmationRequired(Exception):
    """Raised when a pinned/profile write is attempted without confirmation."""


@dataclass(frozen=True)
class Source:
    """A citation: the source, a quoted excerpt that stays checkable, its date."""

    source: str
    excerpt: str
    date: str


@dataclass
class Concept:
    """One atomic, curated unit of permanent knowledge (ADR 0015)."""

    id: str
    slug: str
    type: str
    title: str
    body: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    timestamp: str = ""
    pinned: bool = False
    origin: str = ""
    scope: str = "project"
    status: str = "active"
    supersedes: str | None = None
    superseded_by: str | None = None
    citations: list[Source] = field(default_factory=list)


def bundle_dir(root: Path | None = None) -> Path:
    """The OKF bundle directory."""

    return (root or store_root()) / BUNDLE_DIRNAME


def concept_path(slug: str, root: Path | None = None) -> Path:
    """The file backing a Concept.

    Every Concept read, write, rename and retract funnels through here, so the
    slug is validated as a bare, path-safe identifier before it is joined into
    the path — closing traversal via an attacker-directed slug (#25).
    """

    return bundle_dir(root) / f"{safe_identifier(slug, kind='slug')}.md"


def index_md_path(root: Path | None = None) -> Path:
    """The bundle's regenerated index file."""

    return bundle_dir(root) / INDEX_FILENAME


def new_ulid() -> str:
    """Generate a ULID: a time-ordered, 26-char Crockford-base32 identifier."""

    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def create_concept(
    *,
    title: str,
    body: str,
    concept_type: str,
    origin: str,
    scope: str = "project",
    description: str = "",
    tags: list[str] | None = None,
    pinned: bool = False,
    confirmed: bool = False,
    citations: list[Source] | None = None,
    supersede: Concept | None = None,
    timestamp: str | None = None,
    root: Path | None = None,
) -> Concept:
    """Create and persist a Concept, minting a stable id (ADRs 0013, 0014, 0015).

    A pinned/profile write requires explicit confirmation. Creation regenerates
    the bundle index and updates the search index when one exists.

    When ``supersede`` is given, this replaces a changed fact: the predecessor is
    retired and the successor created as one atomic unit under a single bundle-lock
    acquisition, and the two writes are ordered so no reader ever observes both as
    active — closing the two-answer window the former two-step path opened
    (issue #30, ADR 0015).

    Redaction is enforced here at the Concept-creation boundary: a secret in the
    incoming text is stripped before it is ever persisted, so the guarantee holds
    for every store path that mints a Concept (issue #23).
    """

    root = root or store_root()
    ensure_store(root)
    if pinned and not confirmed:
        raise ConfirmationRequired("a pinned/profile write requires explicit confirmation")

    # Strip secrets from every persisted free-text field at the sink, so no
    # caller can land one in the bundle — the body, the title (and the slug and
    # index entry derived from it), the description, the tags, and the citation
    # sources and excerpts written verbatim into the file (issue #23).
    title, body, description = redact(title), redact(body), redact(description)
    tags = [redact(tag) for tag in tags] if tags else tags
    citations = (
        [Source(redact(s.source), redact(s.excerpt), s.date) for s in citations]
        if citations
        else citations
    )

    with project_lock(_BUNDLE_LOCK, root=root):
        concept = Concept(
            id=new_ulid(),
            slug=_unique_slug(title, root),
            type=concept_type,
            title=title,
            body=body.strip(),
            description=description,
            tags=list(tags or []),
            timestamp=timestamp or datetime.now(UTC).isoformat(),
            pinned=pinned,
            origin=origin,
            scope=scope,
            supersedes=supersede.id if supersede is not None else None,
            citations=list(citations or []),
        )

        # Retire the predecessor before the successor is written. Each write is a
        # single atomic os.replace, so ordering the retirement first means the only
        # state a lockless reader can observe between the two is "predecessor
        # superseded, successor not yet present" — never both active — and a crash
        # between them leaves at most the predecessor retired, never a live pair
        # (issue #30).
        if supersede is not None:
            _supersede_in_place(supersede.slug, concept.id, root)

        _write(concept, root)
        if pinned:
            _enforce_pin_cap(root)
        regenerate_index(root)

    _index_concept_if_present(concept, root)
    return read_concept(concept.slug, root)


def read_concept(slug: str, root: Path | None = None) -> Concept:
    """Read a Concept by slug."""

    return _parse(concept_path(slug, root).read_text(encoding="utf-8"), slug)


def list_concepts(root: Path | None = None) -> list[Concept]:
    """Every parseable Concept in the bundle, sorted by slug.

    ``list_concepts`` sits under recall reindex, distillation, the manifest,
    ``mimer-manage`` and session-start injection, so a single truncated or
    hand-mangled file must not take all of those down at once. A file that is
    unparseable, or that a concurrent writer has removed or left transiently
    unreadable, is skipped and logged rather than allowed to propagate (issue
    #17); a direct :func:`read_concept` on a named slug still raises.
    """

    directory = bundle_dir(root)
    if not directory.exists():
        return []

    concepts = []
    for path in sorted(directory.glob("*.md")):
        if path.name == INDEX_FILENAME:
            continue
        # Contain a per-file failure so one bad Concept never denies every valid
        # one to every caller. Separate the two causes: an OSError means the file
        # was concurrently removed or is transiently unreadable — readers hold no
        # lock and ADR 0011 allows detached writers to unlink underneath us — so
        # it is not corruption and must not be blamed on unparseable content.
        try:
            concepts.append(read_concept(path.stem, root))
        except OSError as exc:
            _log_skip(path, "unreadable Concept", exc, root)
        except Exception as exc:  # noqa: BLE001 - any failure to parse one file must stay contained
            _log_skip(path, "unparseable Concept", exc, root)
    return concepts


def profile_concepts(root: Path | None = None) -> list[Concept]:
    """The active pinned Concepts that form the profile.

    A superseded pinned Concept is no longer current, so — as recall already
    does — it is excluded, leaving exactly the pinned Concepts in force. Without
    the status filter a reworded re-derivation would leave both the superseded
    predecessor and its successor pinned, duplicating the profile (ADR 0015).
    """

    return [
        concept for concept in list_concepts(root) if concept.pinned and concept.status == "active"
    ]


def concept_identity_text(title: str, body: str) -> str:
    """The text a Concept presents when asking "is this the same fact?".

    Its title and body joined, exactly as the search index stores a Concept's
    chunk (:func:`mimer.index.concept_chunk`). Recall matches tombstones against
    this text, so a forget's retraction and the injection paths below all test the
    very same string — the sites that must agree on what a Concept's fact *is*
    cannot drift apart (issue #32).
    """

    return f"{title}\n{body}".strip()


def _not_tombstoned(concept: Concept, tombstones: list[dict[str, str]]) -> bool:
    """Whether ``concept`` has not been forgotten, for the injection filters.

    Suppression is keyed on the Concept's origin — the same origin-keyed rule
    recall applies to a Concept row (ADR 0013) — so the manifest and the profile
    hide a forgotten Concept exactly as recall does (issue #32).
    """

    text = concept_identity_text(concept.title, concept.body)
    return not is_suppressed(text, project_id=concept.origin, tombstones=tombstones)


def concept_headlines(root: Path | None = None, *, project_id: str | None = None) -> list[str]:
    """A one-line headline per Concept visible to ``project_id``, for the manifest.

    A global Concept is visible everywhere; a project-scoped one only within its
    origin (ADR 0013). Without a project id, all Concepts are listed. A Concept a
    forget has tombstoned is filtered out, so a forgotten fact stops appearing in
    the manifest the way it already stops appearing in recall (issue #32).
    """

    tombstones = load_tombstones(root)
    visible = [
        c
        for c in list_concepts(root)
        if (project_id is None or c.scope == "global" or c.origin == project_id)
        and _not_tombstoned(c, tombstones)
    ]
    headlines = []
    for concept in visible:
        detail = concept.description or _first_line(concept.body)
        headlines.append(
            f"{concept.title} — {detail}" if detail and detail != concept.title else concept.title
        )
    return headlines


def render_profile(root: Path | None = None) -> str:
    """Render the pinned profile Concepts for injection, or empty when none.

    Each Concept body is an untrusted leaf, so it is neutralised before it is
    placed under Mimer's own ``## Profile`` / ``### title`` structure (ADR 0014):
    a heading or framing marker inside a body cannot then reopen the surrounding
    context as instructions once the snapshot is framed and injected.

    A pinned Concept a forget has tombstoned is filtered out, so a forgotten fact
    stops being injected into every session — the "theatre" ADR 0012 rejects — the
    way recall already suppresses it (issue #32).
    """

    tombstones = load_tombstones(root)
    pinned = [c for c in profile_concepts(root) if _not_tombstoned(c, tombstones)]
    if not pinned:
        return ""
    blocks = "\n\n".join(f"### {concept.title}\n{neutralise(concept.body)}" for concept in pinned)
    return f"## Profile\n\n{blocks}"


def rename_concept(old_slug: str, new_slug: str, root: Path | None = None) -> Concept:
    """Rename a Concept, rewriting inbound links and the index atomically.

    The Concept's ``id`` is unchanged — identity survives the rename (ADR 0015).
    """

    root = root or store_root()

    with project_lock(_BUNDLE_LOCK, root=root):
        concept = read_concept(old_slug, root)
        concept.slug = new_slug
        _write(concept, root)
        concept_path(old_slug, root).unlink()

        # Rewrite every inbound path link across the bundle.
        for other in list_concepts(root):
            rewritten = other.body.replace(f"/{old_slug}.md", f"/{new_slug}.md").replace(
                f"({old_slug}.md)", f"({new_slug}.md)"
            )
            if rewritten != other.body:
                other.body = rewritten
                _write(other, root)

        regenerate_index(root)

    _reindex_if_present(root)
    return read_concept(new_slug, root)


def retract_concept(slug: str, root: Path | None = None) -> Concept:
    """Retract a Concept on request: remove it and tombstone it so it stops
    surfacing in recall and injection and is never re-distilled (ADR 0012)."""

    with project_lock(_BUNDLE_LOCK, root=root):
        concept = read_concept(slug, root)
        concept_path(slug, root).unlink()
        regenerate_index(root)

    write_tombstone(concept.body, project_id=concept.origin, root=root)
    _reindex_if_present(root)
    return concept


def mark_superseded(slug: str, superseded_by: str, root: Path | None = None) -> None:
    """Mark a Concept superseded by another; recall then drops it (ADR 0015).

    This is the standalone retirement of an already-persisted Concept. A changed
    fact's replacement does not go through here — :func:`create_concept` retires the
    predecessor and mints the successor atomically instead, so no window leaves both
    active (issue #30).
    """

    with project_lock(_BUNDLE_LOCK, root=root):
        _supersede_in_place(slug, superseded_by, root)
        regenerate_index(root)

    _reindex_if_present(root)


def _supersede_in_place(slug: str, superseded_by: str, root: Path | None) -> None:
    """Flip a Concept to superseded and persist it; the caller holds the bundle lock
    and regenerates the index. Shared by :func:`mark_superseded` and the atomic
    create-and-supersede path so both retire a predecessor identically (issue #30)."""

    concept = read_concept(slug, root)
    concept.status = "superseded"
    concept.superseded_by = superseded_by
    _write(concept, root)


def regenerate_index(root: Path | None = None) -> None:
    """Regenerate ``index.md`` from the current Concepts (OKF §6)."""

    concepts = list_concepts(root)
    lines = ["---", f'okf_version: "{OKF_VERSION}"', "---", "", "# Concepts", ""]
    lines.extend(
        f"* [{c.title}]({c.slug}.md) - {c.description or _first_line(c.body)}" for c in concepts
    )
    path = index_md_path(root)
    write_atomic(path, "\n".join(lines) + "\n")


def _write(concept: Concept, root: Path | None) -> None:
    """Serialise and write a Concept file atomically, with owner-only permissions.

    Routed through :func:`storeio.write_atomic` (temp file then ``os.replace``)
    so a crash mid-write can never corrupt the previous Concept — a reader sees
    either the old file or the new, never a torn one (issue #17). Callers already
    hold the bundle lock, which serialises concurrent writers.
    """

    path = concept_path(concept.slug, root)
    write_atomic(path, _serialise(concept))


def _serialise(concept: Concept) -> str:
    """Render a Concept to OKF-conformant Markdown with Mimer's extensions."""

    frontmatter: dict[str, object] = {"type": concept.type, "title": concept.title}
    if concept.description:
        frontmatter["description"] = concept.description
    if concept.tags:
        frontmatter["tags"] = concept.tags
    frontmatter["timestamp"] = concept.timestamp
    frontmatter["id"] = concept.id
    frontmatter["okf_version"] = OKF_VERSION
    frontmatter["pinned"] = concept.pinned
    frontmatter["origin"] = concept.origin
    frontmatter["scope"] = concept.scope
    frontmatter["status"] = concept.status
    if concept.supersedes:
        frontmatter["supersedes"] = concept.supersedes
    if concept.superseded_by:
        frontmatter["superseded_by"] = concept.superseded_by

    front = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    parts = [f"---\n{front}\n---", concept.body.strip()]
    if concept.citations:
        cites = "\n".join(
            f'[{i + 1}] [{s.source}]({s.source}) — "{s.excerpt}" ({s.date})'
            for i, s in enumerate(concept.citations)
        )
        parts.append(f"# Citations\n\n{cites}")
    return "\n\n".join(parts) + "\n"


def _parse(text: str, slug: str) -> Concept:
    """Parse a Concept file back into a Concept."""

    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise ValueError(f"concept {slug} has no frontmatter")
    frontmatter = yaml.safe_load(match.group(1)) or {}

    rest = match.group(2).strip("\n")
    body, _, citation_block = rest.partition("\n# Citations")
    return Concept(
        id=str(frontmatter["id"]),
        slug=slug,
        type=str(frontmatter["type"]),
        title=str(frontmatter.get("title", slug)),
        body=body.strip(),
        description=str(frontmatter.get("description", "")),
        tags=list(frontmatter.get("tags") or []),
        timestamp=str(frontmatter.get("timestamp", "")),
        pinned=bool(frontmatter.get("pinned", False)),
        origin=str(frontmatter.get("origin", "")),
        scope=str(frontmatter.get("scope", "project")),
        status=str(frontmatter.get("status", "active")),
        supersedes=frontmatter.get("supersedes"),
        superseded_by=frontmatter.get("superseded_by"),
        citations=[Source(s, e, d) for s, e, d in _CITATION_RE.findall(citation_block)],
    )


def _enforce_pin_cap(root: Path | None) -> None:
    """Demote the oldest pinned Concepts until the pinned cap holds (ADR 0015)."""

    pinned = sorted((c for c in list_concepts(root) if c.pinned), key=lambda c: c.timestamp)
    for concept in pinned[: max(0, len(pinned) - PINNED_CAP)]:
        concept.pinned = False
        _write(concept, root)


def _unique_slug(title: str, root: Path | None) -> str:
    """A filesystem-safe, unique slug derived from a Concept title."""

    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "concept"
    slug, suffix = base, 2
    while concept_path(slug, root).exists():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _first_line(body: str) -> str:
    """The first non-empty line of a body, for a headline."""

    for line in body.splitlines():
        stripped = line.strip().lstrip("# ").strip()
        if stripped:
            return stripped[:100]
    return ""


def _log_skip(path: Path, reason: str, exc: Exception, root: Path | None) -> None:
    """Log a skipped Concept file once per process, so the store is hand-editable
    and a concurrently-removed or unreadable file stays observable — without a
    single bad file silently emptying injected memory. ``reason`` names the cause
    (an unparseable content error versus an unreadable file) so a reader is not
    sent hunting for a corruption that never happened."""

    if path in _LOGGED_SKIPS:
        return
    _LOGGED_SKIPS.add(path)

    # Log the file name and exception type, never the exception repr: a parse error
    # can quote the Concept's own body (memory prose), which log_failure's shape-based
    # pass cannot strip from the health-surfaced log (#24). The reason and file name
    # keep the skip diagnosable without the repr.
    log_failure(f"bundle: skipped {reason} {path.name}: {type(exc).__name__}", root=root)


def _index_concept_if_present(concept: Concept, root: Path | None) -> None:
    """Index a new Concept into the search index when one exists."""

    from mimer.index import index_concept_if_present

    index_concept_if_present(concept, root)


def _reindex_if_present(root: Path | None) -> None:
    """Rebuild the search index after a rename, when one exists."""

    from mimer.index import index_db_path, reindex

    if index_db_path(root).exists():
        reindex(root)
