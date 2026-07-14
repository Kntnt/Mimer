"""Documentation-truthfulness sweep (issue #45).

Every checkable claim in the shipped docs must match the code, and the internal
invariants (no present-tense Cowork claim; one coherent version story) must
hold. These tests read the doc files directly, in the spirit of
``test_memory_skill.py`` — the docs are part of the product, so their factual
claims are constrained like any other behaviour.
"""

from __future__ import annotations

import inspect
import json
import re
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mimer import bundle, manage

ROOT = Path(__file__).resolve().parent.parent

README = ROOT / "README.md"
NOTICE = ROOT / "NOTICE"
CHANGELOG = ROOT / "CHANGELOG.md"
OKF_PROFILE = ROOT / "docs" / "okf-profile.md"
VISION = ROOT / "docs" / "vision.md"
SKILL = ROOT / "skills" / "memory" / "SKILL.md"
PYPROJECT = ROOT / "pyproject.toml"
PLUGIN_MANIFEST = ROOT / ".claude-plugin" / "plugin.json"
INIT = ROOT / "src" / "mimer" / "__init__.py"
CONTEXT = ROOT / "CONTEXT.md"
STOREIO = ROOT / "src" / "mimer" / "storeio.py"
INDEX = ROOT / "src" / "mimer" / "index.py"
BOUNDARY = ROOT / "src" / "mimer" / "boundary.py"
ADR_0020 = ROOT / "docs" / "adr" / "0020-redaction-at-the-write-seam.md"
ADR_0027 = ROOT / "docs" / "adr" / "0027-leakage-guard-global-scope.md"

# The one-sentence write-seam contract, worded identically in storeio's docstring,
# CONTEXT.md's glossary entry and ADR 0020 (#55).
WRITE_SEAM_CONTRACT = "no text reaches the store's files unredacted"


def _user_facing_commands() -> set[str]:
    """The ``mimer-*`` console scripts a user invokes, derived from
    ``pyproject.toml``.

    The three hook targets (``mimer.hooks.*``) are entry points Claude Code
    calls on lifecycle events, not commands a user runs, so they are excluded.
    """

    scripts = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["scripts"]
    return {name for name, target in scripts.items() if not target.startswith("mimer.hooks.")}


def _manifest_versions() -> dict[str, str]:
    """The version string as declared in each of the three places it lives."""

    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    plugin = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))["version"]
    init_match = re.search(r'__version__\s*=\s*"([^"]+)"', INIT.read_text(encoding="utf-8"))
    assert init_match is not None, "src/mimer/__init__.py declares no __version__"
    return {"pyproject.toml": pyproject, "plugin.json": plugin, "__init__.py": init_match.group(1)}


def _changelog_sections() -> dict[str, str]:
    """Map each ``## [name]`` changelog heading to the body text beneath it."""

    text = CHANGELOG.read_text(encoding="utf-8")
    headings = list(re.finditer(r"^## \[([^\]]+)\]", text, re.MULTILINE))
    sections: dict[str, str] = {}
    for index, heading in enumerate(headings):
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        sections[heading.group(1)] = text[start:end]
    return sections


def _comparison_row_mimer_cell(feature: str) -> str:
    """Return Mimer's cell for a named row of the agent-memory comparison table.

    The table's first data column is Mimer, so the cell sits at split index 2
    (``['', label, mimer, ...]``).
    """

    for line in README.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"| {feature} "):
            return [cell.strip() for cell in line.split("|")][2]
    raise AssertionError(f"No comparison row found for {feature!r}")


def test_readme_does_not_claim_mimer_is_unbuilt() -> None:
    """The README must not say the plugin is unbuilt or unshippable (issue #45)."""

    text = README.read_text(encoding="utf-8")
    assert "not built yet" not in text
    assert "They ship today" not in text


def test_readme_comparison_marks_mimer_installable() -> None:
    """The 'Installable today' row must show Mimer as available (✓), not ✗."""

    assert _comparison_row_mimer_cell("Installable today") == "✓"


def test_readme_has_no_deferred_placeholder_sections() -> None:
    """The usage and development sections document what exists, not 'will be
    added later' placeholders for a toolchain that already ships."""

    text = README.read_text(encoding="utf-8")
    assert "Detailed usage will be documented as the interface settles" not in text
    assert "Build and test instructions will be added as the toolchain takes shape" not in text


def test_readme_documents_every_user_facing_command() -> None:
    """The README must document all user-facing ``mimer-*`` commands, including
    the previously omitted mimer-memory, mimer-recall and mimer-reindex."""

    text = README.read_text(encoding="utf-8")
    missing = {command for command in _user_facing_commands() if command not in text}
    assert missing == set(), f"README omits user-facing commands: {sorted(missing)}"


def test_notice_makes_no_present_tense_cowork_claim() -> None:
    """NOTICE must not call Mimer a Cowork plugin — ADR 0010's invariant is that
    no document claims Cowork support in the present tense."""

    assert "Cowork" not in NOTICE.read_text(encoding="utf-8")


def test_no_document_calls_mimer_a_cowork_plugin() -> None:
    """The present-tense 'Claude Code and Claude Cowork plugin' construction must
    not survive anywhere in the tracked docs (ADR 0010)."""

    offenders = []
    for path in [README, NOTICE, CHANGELOG, OKF_PROFILE, ROOT / "docs" / "vision.md"]:
        if "Claude Code and Claude Cowork plugin" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert offenders == [], f"Present-tense Cowork claim in: {offenders}"


def test_manifest_versions_agree() -> None:
    """The version must be identical across pyproject, the plugin manifest and
    the package's __version__."""

    versions = _manifest_versions()
    assert len(set(versions.values())) == 1, f"Version disagreement: {versions}"


def test_changelog_records_the_v0_1_0_feature_set() -> None:
    """The 0.1.0 section must carry the actual initial feature set (Stages 0–8),
    not a bare 'Initial release' stub with the features stranded under Unreleased
    — the concern guarded at first release. Pinned to 0.1.0, not the moving
    manifest version, so a later release keeps the historical record intact
    instead of re-breaking this guard on every version bump."""

    sections = _changelog_sections()
    assert "0.1.0" in sections, "CHANGELOG has no 0.1.0 section"
    released = sections["0.1.0"]
    assert "Foundations (Stage 0)" in released
    assert "Packaging and first run (Stage 8)" in released
    assert "- Initial release." not in CHANGELOG.read_text(encoding="utf-8")


def test_changelog_documents_the_manifest_version_with_real_notes() -> None:
    """Whatever version the manifest currently declares must have a substantive
    changelog section — at least one categorised subsection with an entry — so a
    release never ships with its notes stubbed or stranded under Unreleased."""

    version = next(iter(_manifest_versions().values()))
    sections = _changelog_sections()
    assert version in sections, f"CHANGELOG has no section for {version}"
    released = sections[version]
    assert re.search(
        r"^### (Added|Changed|Deprecated|Removed|Fixed|Security)$",
        released,
        re.MULTILINE,
    ), f"CHANGELOG [{version}] has no categorised release notes"
    assert re.search(r"^- \S", released, re.MULTILINE), f"CHANGELOG [{version}] has no entries"


def test_changelog_does_not_strand_features_under_unreleased() -> None:
    """Unreleased must not still hold the shipped Stage 0–8 feature set."""

    unreleased = _changelog_sections().get("Unreleased", "")
    assert "Foundations (Stage 0)" not in unreleased
    assert "Packaging and first run (Stage 8)" not in unreleased


def test_changelog_unreleased_records_the_leakage_guard() -> None:
    """The [Unreleased] section must document #65's shipped leakage-guard build, not
    only the ADR-0027 design line. #65 landed after the changelog was reconciled over
    #60-#64, so its user-visible behaviour — a sensitive fact held at project scope
    with a consent request queued for the next session start — was left unrecorded
    even though every other build issue in the union is named. No other test enforces
    [Unreleased] completeness, so this guards the omission (integration-review
    finding)."""

    unreleased = _changelog_sections().get("Unreleased", "")
    assert "#65" in unreleased, "CHANGELOG [Unreleased] does not record #65's leakage-guard build"
    assert "leakage guard" in unreleased, "CHANGELOG [Unreleased] does not name the leakage guard"
    assert "consent request" in unreleased, "[Unreleased] omits #65's queued consent request"


def test_okf_profile_describes_vendored_spec_in_present_tense() -> None:
    """okf-profile.md must state the spec is vendored (it already is under
    docs/okf/), not that it will be when Stage 5a is built."""

    text = OKF_PROFILE.read_text(encoding="utf-8")
    assert (ROOT / "docs" / "okf" / "SPEC.md").is_file()
    assert "When Stage 5a is built" not in text
    assert "docs/okf/" in text


def test_changelog_claim_about_readme_command_coverage_is_true() -> None:
    """If the changelog claims the README documents the mimer-* commands, that
    must be verifiably true of the README."""

    changelog = CHANGELOG.read_text(encoding="utf-8")
    if "the README documents" in changelog and "`mimer-*` commands" in changelog:
        readme = README.read_text(encoding="utf-8")
        missing = {command for command in _user_facing_commands() if command not in readme}
        assert missing == set(), f"CHANGELOG claim is false; README omits: {sorted(missing)}"


def test_vision_does_not_describe_a_nonexistent_high_water_mark() -> None:
    """vision.md must not describe distillation as gated on a per-project
    high-water mark: that mechanism exists nowhere in the code, and pointing the
    next implementer at it is exactly the untruth issue #28 fixes."""

    assert "high-water" not in VISION.read_text(encoding="utf-8").lower()


def test_vision_names_the_real_distillation_trigger_and_idempotency() -> None:
    """The Stage 5b description must name the real trigger (the short-term cap and
    session boundaries) and the real idempotency mechanism (dedup and
    supersession), which is what the code actually does (issue #28)."""

    text = VISION.read_text(encoding="utf-8").lower()
    assert "short-term cap" in text
    assert "dedup" in text and "supersession" in text


def test_skill_documents_the_claude_plugin_root_dependency() -> None:
    """The skill relies on ${CLAUDE_PLUGIN_ROOT} in skill-run Bash, which the
    platform documents only for hooks; the skill must record that guarantee so a
    future platform change does not silently break it (issue #45)."""

    text = SKILL.read_text(encoding="utf-8")
    assert "${CLAUDE_PLUGIN_ROOT}" in text
    assert "resolves in skill-run Bash" in text


def _glossary_entry(glossary_term: str) -> str:
    """The full text of CONTEXT.md's ``**glossary_term**:`` entry, from its bold
    lemma up to the next entry (or end of file)."""

    entry = re.search(
        rf"^\*\*{re.escape(glossary_term)}\*\*:.*?(?=^\*\*|\Z)",
        CONTEXT.read_text(encoding="utf-8"),
        re.MULTILINE | re.DOTALL,
    )
    assert entry is not None, f"CONTEXT.md has no glossary entry for {glossary_term!r}"
    return entry.group(0)


def _avoid_terms_for(glossary_term: str) -> list[str]:
    """The lowercased names CONTEXT.md's glossary entry for *glossary_term* lists
    under its _Avoid_ line — the names that concept must never be called."""

    avoid = re.search(r"^_Avoid_:\s*(.+?)\s*$", _glossary_entry(glossary_term), re.MULTILINE)
    assert avoid is not None, f"CONTEXT.md's {glossary_term!r} entry has no _Avoid_ line"
    return [term.strip().rstrip(".").strip().lower() for term in avoid.group(1).split(",")]


def test_storeio_docstring_carries_the_write_seam_contract() -> None:
    """storeio's module docstring must state the write-seam contract — no text
    reaches the store's files unredacted — and record its one deliberate
    exemption, the capture spool, with the reason (ADR 0020, #55)."""

    source = STOREIO.read_text(encoding="utf-8")
    assert WRITE_SEAM_CONTRACT in source
    assert "0020" in source
    assert "spool" in source.lower()


def test_context_defines_the_redaction_pass() -> None:
    """CONTEXT.md must carry the 'Redaction pass' glossary entry: the write-seam
    contract, and exactly the three _Avoid_ terms the ticket quotes (#55)."""

    text = CONTEXT.read_text(encoding="utf-8")
    assert WRITE_SEAM_CONTRACT in text
    assert set(_avoid_terms_for("Redaction pass")) == {"scrubbing", "sanitisation", "masking"}


def test_adr_0020_states_both_halves_and_the_spool_exemption() -> None:
    """ADR 0020 must exist and state both halves of the design — the structural
    disk guarantee at the seam and the never-pruned sink calls — plus the spool
    exemption (#55)."""

    assert ADR_0020.is_file()
    text = ADR_0020.read_text(encoding="utf-8")
    lowered = text.lower()
    assert WRITE_SEAM_CONTRACT in text
    assert "seam" in lowered
    assert "sink" in lowered
    assert "spool" in lowered


def test_adr_0020_excludes_secret_shaped_identifiers_from_byte_identical() -> None:
    """ADR 0020's byte-identical-provenance claim must be bounded: an identifier
    literally shaped like a recognised secret prefix (``sk-ant-`` and the other
    OpenAI/GitLab prefixes) is redacted by the seam by design, and this collision
    is deliberately NOT exempted — a credential-shaped string is safe to redact,
    and exempting it would reopen the write-seam bypass the ADR forbids
    (integration-review finding)."""

    text = ADR_0020.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "byte-identical" in text
    assert "the one exclusion" in lowered
    assert "secret prefix" in lowered
    assert "sk-ant-" in text
    assert "redacts by design" in lowered
    assert "bypass" in lowered


def test_adr_0027_scopes_its_gate_to_the_promotion_channel_and_notes_the_raw_log() -> None:
    """ADR 0027's 'verifiable gate' must be scoped to the PROMOTION (Concept)
    channel, and must document the raw-log caveat — not overclaim a blanket
    'never appears in widened recall from another project'.

    The leakage guard holds a sensitive fact's *Concept* at project scope, so it
    never becomes a global Concept in another project's recall. But the
    confidential utterance the fact was distilled from is already captured,
    verbatim, into its origin project's daily log at capture time — before
    distillation runs — and that raw long-term log is reachable by another
    project's ``--widen`` recall by ADR 0013's design (redaction strips
    shape-detectable secrets, not confidential prose). The ADR must state the gate
    is on the promotion channel and document that raw-log caveat explicitly, or
    the 'never travels' framing overclaims a guarantee the widenable log defeats
    (integration-review finding)."""

    text = ADR_0027.read_text(encoding="utf-8")
    lowered = text.lower()

    # The bare, unqualified overclaim must be gone.
    assert (
        "a sensitive fact awaiting consent must never appear in widened recall from another project"
        not in lowered
    ), "ADR 0027 still makes the blanket 'never appears in widened recall' overclaim"

    # The gate is scoped to the promotion/Concept channel.
    assert "promotion channel" in lowered, "gate not scoped to the promotion channel"
    assert "global concept" in lowered, "gate not framed around a global Concept"

    # The raw-log caveat is documented and tied to the widenable log (ADR 0013).
    assert "raw long-term log" in lowered, "raw-log caveat undocumented"
    assert "0013" in text, "raw-log caveat does not tie back to ADR 0013's widenable log"
    assert "capture time" in lowered, "does not note the utterance travels at capture time"


# The presentation surfaces that show Concepts — every one must reach the bundle
# only through the Visible seam, never the raw enumeration (issue #54).
PRESENTATION_SURFACES: list[Callable[..., Any]] = [
    bundle.profile_concepts,
    bundle.concept_headlines,
    bundle.render_profile,
    manage.profile,
    manage.recent_concepts,
]


def test_raw_enumeration_docstring_names_it_mechanical_and_points_at_the_seam() -> None:
    """``list_concepts``' docstring must state it is the mechanical read — no
    status, scope or tombstone filter — and point presentation surfaces at the
    ``visible_concepts`` seam, so a reader is not tempted to enumerate Concepts for
    display through the raw read (issue #54)."""

    doc = inspect.getdoc(bundle.list_concepts) or ""
    assert "mechanical" in doc.lower()
    assert "visible_concepts" in doc


def test_no_presentation_surface_calls_the_raw_enumeration() -> None:
    """Every surface that shows Concepts reaches the bundle only through the
    ``visible_concepts`` seam; none calls the raw ``list_concepts`` directly, so
    status, scope and tombstone filtering can never be reintroduced by hand and
    drift between surfaces (issue #54). ``visible_concepts`` is the one sanctioned
    caller of the raw read for presentation."""

    offenders = [
        fn.__qualname__ for fn in PRESENTATION_SURFACES if "list_concepts" in inspect.getsource(fn)
    ]
    assert offenders == [], f"presentation surface(s) bypass the Visible seam: {offenders}"


def test_context_carries_the_visible_glossary_entry() -> None:
    """CONTEXT.md carries the Visible entry under Mechanics, the canonical term for
    the presentation predicate every surface uses (issue #54)."""

    text = CONTEXT.read_text(encoding="utf-8")
    assert "**Visible** (of a Concept):" in text
    assert "The presentation predicate" in text


def test_vision_stage5c_gate_names_the_injected_profile() -> None:
    """The Stage 5c gate sentence now reads 'profile enumeration matches the injected
    profile exactly' — the seam makes the enumerated and injected profiles one set,
    so the gate asserts that equality rather than the looser 'pinned set' (issue
    #54)."""

    text = VISION.read_text(encoding="utf-8")
    assert "profile enumeration matches the injected profile exactly" in text
    assert "profile enumeration matches the pinned set exactly" not in text


def test_storeio_write_discipline_map_names_the_announcement_queue_canonically() -> None:
    """storeio.py is the single home of the store's write-discipline map (#49), so
    it must name the announcement queue by its canonical glossary term (#57) and
    never a name CONTEXT.md's 'Announcement queue' entry forbids under _Avoid_
    (notably 'distilled queue'). The on-disk filename '.distilled-queue' is a
    hyphenated identifier, not the forbidden phrase, so it stays."""

    source = STOREIO.read_text(encoding="utf-8").lower()
    forbidden = [term for term in _avoid_terms_for("Announcement queue") if term in source]
    assert forbidden == [], f"storeio's write-discipline map uses forbidden term(s): {forbidden}"
    assert "announcement queue" in source, "storeio's map omits the canonical 'announcement queue'"


def test_storeio_map_and_context_document_the_announcement_queues_locked_clear() -> None:
    """The announcement queue is not purely lockless. Its CLEAR
    (``_clear_announcements``) is a locked read-modify-write —
    ``write_atomic``/``unlink`` under ``project_lock`` — and its enqueues are
    lockless ``O_APPEND`` *only* because every enqueue already runs under the
    caller's project lock (``rewrite_sections``' lock). That invariant is
    load-bearing: a truly lockless enqueue would lose an
    update in the window between the clear's read and its write (#40). Both
    storeio's write-discipline map and CONTEXT.md's 'Lock discipline' entry must
    state it, so a future writer cannot reintroduce a lockless enqueue believing
    the queue is append-only (integration-review finding)."""

    storeio = STOREIO.read_text(encoding="utf-8").lower()
    assert "locked clear" in storeio
    assert "write_atomic" in storeio and "unlink" in storeio
    assert "under the caller's project lock" in storeio

    lock_discipline = _glossary_entry("Lock discipline").lower()
    assert "locked clear" in lock_discipline
    assert "project_lock" in lock_discipline
    assert "under the caller's project lock" in lock_discipline


def test_storeio_write_discipline_map_names_the_consent_queue() -> None:
    """storeio.py is the single home of the store's write-discipline map (#49). The
    consent queue (``.consent-queue``, #65) is a new store-writing artefact — a
    lockless ``O_APPEND`` write through ``append_text`` (``mimer.leakage``) that,
    unlike the announcement queue, is never cleared and so has no locked clear to
    protect. It must appear as a row in the map, or the completeness the docstring
    and this suite call 'the single home of that map' is false (integration-review
    finding)."""

    source = STOREIO.read_text(encoding="utf-8")
    assert ".consent-queue" in source, "storeio's map omits the .consent-queue file"
    assert "consent queue" in source.lower(), "storeio's map does not name the consent queue"


def test_index_docstring_explains_why_inserts_trust_their_sources() -> None:
    """The indexer's docstring must state why an insert needs no redaction of its
    own: chunk text is never redacted at insert because every insert reads from an
    artefact already redacted before it reached disk, or from a Concept redacted at
    creation, and the index is derived state — so redacting again at insert could
    only make it diverge from the files its citations quote (#56)."""

    source = INDEX.read_text(encoding="utf-8").lower()
    assert "never redacted at insert" in source
    assert "redacted at creation" in source
    assert "derived state" in source
    assert "diverge" in source


def test_skill_does_not_describe_the_mimer_marker_as_an_active_binding() -> None:
    """The `.mimer` marker was made inert (#61): after that change it attaches
    nothing — only the git remote or the path binds a directory to an existing
    project's memory, and dropping the marker removed the one identity signal an
    attacker could forge as repository content. The shipped skill's
    identity-confirmation section must not still tell users a `.mimer` marker would
    attach this directory to an existing project's memory — that claim is now false
    and security-relevant (integration-review finding)."""

    assert "`.mimer` marker" not in SKILL.read_text(encoding="utf-8")


def test_index_cite_docstring_matches_the_shipped_boundary_pass_state() -> None:
    """The session digest is gone (#63): digest.py no longer exists, and the
    boundary pass distils straight from the raw record (ADR 0023). index.py's
    ``_cite`` docstring is now free to state that distillation subsumes the digest,
    and the heading-based source weight is removed (#62), so a chunk's heading no
    longer influences its rank — both truthful, shipped facts the docstring keeps."""

    assert not (ROOT / "src" / "mimer" / "digest.py").exists(), (
        "digest.py must be gone — the session digest is removed (#63)"
    )
    assert BOUNDARY.is_file(), "the boundary pass module must ship (#63)"
    index_source = INDEX.read_text(encoding="utf-8").lower()
    assert "heading no longer influences its rank" in index_source
