"""The read-only interactive CLI browser (``mimer-browse``, ADR 0028).

The whole store, read from the terminal without starting a session. It searches
with the one hybrid index recall uses — but *unfiltered by scope*, because scope
protects clients from each other in the agent's recall, not the user from their
own memory. Full sight is the point: this is where the user audits, with their
own eyes, what has become global (ADR 0027) and what a project keeps.

The module has two seams. :func:`browse_search` is the headless search core —
no curses, no terminal, so it is testable directly. :class:`BrowseSession` is
the interactive layer as a curses-free state machine: arrow keys move the
selection, Enter opens a hit with its source and date, q quits. The curses
driver (:func:`_interact`) is a thin adapter that only paints the session's
rendered lines and forwards keystrokes, so every decision stays testable off a
terminal.

Strictly read-only: it performs no remember, forget or redact — it only reads
the derived index and the tombstone ledger — so it can never damage the store.
"""

from __future__ import annotations

import argparse
import contextlib
import curses
import textwrap
from pathlib import Path

from mimer.index import Citation, search
from mimer.paths import store_root

# Recall shows ten hits; the browser is an audit surface, so it surfaces a wider
# window of the store in one pass (still bounded by the index's candidate set).
_DEFAULT_LIMIT = 20

# The honest empty result: reported on stdout so the command is safe to run
# non-interactively, with nothing to page through.
_EMPTY_MESSAGE = 'Mimer: nothing relevant found for "{query}".'

# Key groups the session responds to. Arrow keys carry their vi aliases; Enter
# arrives as either curses' key or a raw newline/return depending on the
# terminal; the back keys close an open hit without ending the browser.
_UP_KEYS = frozenset({curses.KEY_UP, ord("k")})
_DOWN_KEYS = frozenset({curses.KEY_DOWN, ord("j")})
_OPEN_KEYS = frozenset({curses.KEY_ENTER, ord("\n"), ord("\r")})
_BACK_KEYS = frozenset({curses.KEY_LEFT, curses.KEY_BACKSPACE, 127, 27})
_QUIT_KEY = ord("q")


def browse_search(
    query: str, *, root: Path | None = None, limit: int = _DEFAULT_LIMIT
) -> list[Citation]:
    """Search the whole store the way recall does, but unfiltered by scope.

    The read-only browser's search core (ADR 0028): it reuses recall's one hybrid
    index (:func:`mimer.index.search`) with the scope filter lifted, so every
    project's logs and every Concept surface regardless of scope — the audit
    surface where the user sees for themselves what has become global. A forgotten
    fact stays suppressed here exactly as in recall (ADR 0012); only the scope
    gate is lifted. Headless and terminal-free, so it is testable under the
    interactive layer.
    """

    return search(query, root=root, unfiltered=True, limit=limit)


class BrowseSession:
    """The browser's interactive state, decoupled from curses.

    Holds the hit list and the view state — either the list (with a highlighted
    hit) or a single hit open for reading (scrolled within a viewport). It reacts
    to keystrokes via :meth:`handle_key` and paints itself to plain lines via
    :meth:`render`, so the full interaction is exercisable without a terminal. The
    curses driver owns only the actual screen and the keyboard.
    """

    def __init__(
        self, query: str, hits: list[Citation], *, height: int = 24, width: int = 80
    ) -> None:
        """Open on the hit list, with the first hit highlighted.

        Args:
            query: The search that produced the hits, shown in the list chrome.
            hits: The hits to browse; the caller guarantees a non-empty list
                (an empty search never opens the browser — see :func:`browse`).
            height: The viewport height in rows; the curses driver keeps it in
                step with the real window via :meth:`resize`.
            width: The viewport width in columns.
        """

        self._query = query
        self._hits = hits
        self._height = height
        self._width = width

        # The list cursor and its scroll offset; the open hit and its scroll
        # offset. A ``None`` open hit means the list is showing.
        self._cursor = 0
        self._list_top = 0
        self._reading: Citation | None = None
        self._scroll = 0

    @property
    def mode(self) -> str:
        """``"reading"`` when a hit is open, ``"list"`` otherwise."""

        return "reading" if self._reading is not None else "list"

    @property
    def selection(self) -> Citation:
        """The highlighted hit in the list."""

        return self._hits[self._cursor]

    @property
    def opened(self) -> Citation | None:
        """The hit open for reading, or ``None`` while the list is showing."""

        return self._reading

    def resize(self, height: int, width: int) -> None:
        """Adopt a new viewport size, re-clamping the cursor and scroll into it."""

        self._height = height
        self._width = width
        self._follow_cursor()
        self._scroll = min(self._scroll, self._max_scroll())

    def handle_key(self, key: int) -> bool:
        """React to one keystroke; return ``False`` when the browser should exit.

        Routes to the reading handler while a hit is open and to the list handler
        otherwise. Only a ``q`` at the top-level list returns ``False``; every
        other key keeps the browser running.
        """

        if self._reading is not None:
            return self._handle_reading_key(key)
        return self._handle_list_key(key)

    def render(self) -> list[str]:
        """The lines currently visible, chrome first — the list or the open hit."""

        if self._reading is not None:
            return self._render_reading(self._reading)
        return self._render_list()

    def _handle_list_key(self, key: int) -> bool:
        """List navigation: q quits, arrows move the highlight, Enter opens it."""

        # q at the list ends the browser.
        if key == _QUIT_KEY:
            return False

        # Arrow keys move the highlighted hit, clamped to the list's ends, and the
        # window follows so the highlight stays on screen; Enter opens it.
        if key in _UP_KEYS:
            self._cursor = max(0, self._cursor - 1)
            self._follow_cursor()
        elif key in _DOWN_KEYS:
            self._cursor = min(len(self._hits) - 1, self._cursor + 1)
            self._follow_cursor()
        elif key in _OPEN_KEYS:
            self._reading = self._hits[self._cursor]
            self._scroll = 0

        return True

    def _handle_reading_key(self, key: int) -> bool:
        """Reading a hit: q or a back key closes it, arrows scroll its text."""

        # q or a back key closes the hit back to the list; the browser stays open.
        if key == _QUIT_KEY or key in _BACK_KEYS:
            self._reading = None
            return True

        # Arrow keys scroll the hit's text within the reading viewport, clamped so
        # the last line never scrolls past the bottom.
        if key in _UP_KEYS:
            self._scroll = max(0, self._scroll - 1)
        elif key in _DOWN_KEYS:
            self._scroll = min(self._max_scroll(), self._scroll + 1)

        return True

    def _render_list(self) -> list[str]:
        """The chrome line plus a window of hit rows around the highlight."""

        # Mimer's own voice: the result count and the key legend.
        header = self._fit(
            f'Mimer — {len(self._hits)} result(s) for "{self._query}"'
            "   (↑/↓ move · Enter open · q quit)"
        )

        # One row per hit — date, source, heading — windowed to the rows left
        # below the chrome, with the caret on the highlighted row.
        rows = [self._hit_row(index) for index in range(len(self._hits))]
        visible = rows[self._list_top : self._list_top + self._body_height()]
        return [header, *visible]

    def _render_reading(self, hit: Citation) -> list[str]:
        """The chrome line plus a window of the open hit's text at the scroll offset."""

        # The chrome pins the open hit's source and date so they stay in view while
        # its text scrolls beneath (acceptance criterion 2).
        header = self._fit(f"Mimer — {hit.source} · {hit.date}   (↑/↓ scroll · q back)")

        # The hit's text, wrapped to the viewport and windowed to the scroll
        # offset — vertical pagination through a hit longer than the screen.
        lines = _format_hit(hit, width=self._text_width())
        visible = lines[self._scroll : self._scroll + self._body_height()]
        return [header, *visible]

    def _hit_row(self, index: int) -> str:
        """One list row: a caret on the highlighted hit, then its date, source and
        heading, clipped to the viewport width."""

        caret = "▶ " if index == self._cursor else "  "
        hit = self._hits[index]
        return self._fit(f"{caret}{hit.date} · {hit.source} · {hit.heading}")

    def _follow_cursor(self) -> None:
        """Scroll the list so the highlighted hit stays inside the viewport."""

        height = self._body_height()
        if self._cursor < self._list_top:
            self._list_top = self._cursor
        elif self._cursor >= self._list_top + height:
            self._list_top = self._cursor - height + 1

    def _max_scroll(self) -> int:
        """The furthest the open hit can scroll before its last line reaches the
        bottom of the viewport; zero while the list is showing."""

        if self._reading is None:
            return 0
        lines = _format_hit(self._reading, width=self._text_width())
        return max(0, len(lines) - self._body_height())

    def _body_height(self) -> int:
        """The rows available below the one-line chrome (at least one)."""

        return max(1, self._height - 1)

    def _text_width(self) -> int:
        """The columns available for wrapped text (at least one)."""

        return max(1, self._width - 1)

    def _fit(self, line: str) -> str:
        """Clip a chrome or list line to the viewport width so curses never wraps it."""

        return line[: max(0, self._width - 1)]


def _format_hit(hit: Citation, *, width: int) -> list[str]:
    """The content lines of a hit for the reading view: its source and date, then
    its stored text wrapped to ``width``.

    The text is shown verbatim. The browser's audience is the user, not an
    injection-vulnerable agent, so the data frame and leaf neutralisation recall
    applies would only be noise on this human-facing surface (ADR 0028, ADR 0029)
    — and the whole point is to see what is actually stored. Source and date lead
    so the user always knows which file and day a fact was read from.
    """

    header = [f"Source: {hit.source}", f"Date:   {hit.date}", ""]
    return [*header, *_wrap(hit.text, width)]


def _wrap(text: str, width: int) -> list[str]:
    """Wrap each physical line of ``text`` to ``width``, keeping blank lines and
    never breaking a word or a hyphenated token so a stored identifier stays whole."""

    lines: list[str] = []
    for physical in text.splitlines():
        wrapped = textwrap.wrap(
            physical, width=width, break_long_words=False, break_on_hyphens=False
        )
        lines.extend(wrapped or [""])
    return lines


def browse(query: str, *, root: Path | None = None) -> int:
    """Search for ``query`` and browse the hits interactively; return an exit code.

    An empty result is reported on stdout and the browser never opens — there is
    nothing to page through — so the command is safe to run non-interactively.
    """

    hits = browse_search(query, root=root)
    if not hits:
        print(_EMPTY_MESSAGE.format(query=query))
        return 0

    session = BrowseSession(query, hits)
    curses.wrapper(_interact, session)
    return 0


def _interact(stdscr: curses.window, session: BrowseSession) -> None:
    """The curses adapter: draw the session, read a key, hand it back, repeat.

    Every decision lives in the session; this loop only paints its rendered lines
    and forwards keystrokes, so the browser's behaviour is testable without a
    terminal.
    """

    curses.curs_set(0)
    while True:
        # Keep the session's viewport in step with the real window, then paint its
        # rendered lines top to bottom.
        height, width = stdscr.getmaxyx()
        session.resize(height, width)
        stdscr.erase()
        for row, line in enumerate(session.render()):
            _put(stdscr, row, line, width)
        stdscr.refresh()

        # Forward the keystroke; a False result ends the browser.
        if not session.handle_key(stdscr.getch()):
            return


def _put(stdscr: curses.window, row: int, line: str, width: int) -> None:
    """Draw one line clipped to the window.

    curses raises when a write reaches the final cell of the screen or a row
    beyond it; addnstr to width-1 keeps each draw inside, and the guard absorbs
    the last-cell quirk on a viewport too short for every rendered line.
    """

    with contextlib.suppress(curses.error):
        stdscr.addnstr(row, 0, line, max(0, width - 1))


def main(argv: list[str] | None = None) -> int:
    """``mimer-browse`` entry point: search the whole store and browse it read-only."""

    parser = argparse.ArgumentParser(
        prog="mimer-browse",
        description=(
            "Read the whole store from the terminal: search with recall's index, "
            "browse the hits, and read one with its source and date. Read-only."
        ),
    )
    parser.add_argument("query", nargs="+", help="what to search the store for")
    args = parser.parse_args(argv)

    return browse(" ".join(args.query), root=store_root())
