"""Hermetic contract for the PWA's visible mid-turn compose sheet.

The browser suite proves the behavior with a real relay
(``test_redial_e2e.py::test_busy_sheet_queues_second_message_and_replays``).
This test pins the markup and wiring that make that path reachable at all:
the device-bar button, the bottom sheet's visible IDs, and the fact that
sending from the sheet does not navigate away from the playing turn.

It reads the single-file PWA's source, so removing the button, renaming an
ID, or making the sheet navigate to another screen fails in the default
hermetic suite — no Playwright or system Chrome required.
"""

from html.parser import HTMLParser
import re
from pathlib import Path

CLIENT = Path(__file__).resolve().parents[1] / "ziv_client" / "index.html"

EXPECTED_IDS = {
    "btnWriteDuring": "button",
    "composeSheet": "div",
    "composeSheetInput": "input",
    "btnSheetSend": "button",
    "btnSheetCancel": "button",
    "sheetStatus": "p",
}


class _IdParser(HTMLParser):
    """Collect every start tag that carries an id, and flag duplicates."""

    def __init__(self) -> None:
        super().__init__()
        self.elements: dict[str, tuple[str, dict[str, str | None]]] = {}
        self.duplicates: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        ident = attributes.get("id")
        if not ident:
            return
        if ident in self.elements:
            self.duplicates.append(ident)
        self.elements[ident] = (tag, attributes)


def _source() -> str:
    return CLIENT.read_text(encoding="utf-8")


def _script(html: str) -> str:
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert scripts, "the client's inline script is missing"
    return max(scripts, key=len)


def _fn(js: str, name: str) -> str:
    """One top-level function's body, using the client's column-0 house style."""
    match = re.search(r"function %s\(" % re.escape(name), js)
    assert match, "client function %s() is missing" % name
    body = re.search(r"\{(.*?)\n\}", js[match.start():], re.S)
    assert body, "could not isolate %s()'s body" % name
    return body.group(1)


def test_busy_sheet_contract_keeps_the_visible_mid_turn_compose_path():
    html = _source()
    parser = _IdParser()
    parser.feed(html)

    assert not parser.duplicates, parser.duplicates
    for ident, tag in EXPECTED_IDS.items():
        assert ident in parser.elements, f"missing busy-sheet control #{ident}"
        assert parser.elements[ident][0] == tag, (
            f"#{ident} must be a <{tag}>, got <{parser.elements[ident][0]}>"
        )

    button_tag, button_attrs = parser.elements["btnWriteDuring"]
    assert button_tag == "button"
    assert button_attrs.get("class") == "write-during"
    assert "hidden" in button_attrs, "the busy button starts hidden"

    sheet_tag, sheet_attrs = parser.elements["composeSheet"]
    assert sheet_tag == "div"
    assert "hidden" in sheet_attrs, "the sheet starts hidden"
    assert sheet_attrs.get("role") == "dialog"

    input_tag, input_attrs = parser.elements["composeSheetInput"]
    assert input_tag == "input"
    assert input_attrs.get("type") == "text"
    assert input_attrs.get("maxlength") == "120"

    # The HTML hidden property is only a hint for a styled <div>; both the
    # sheet and the device-bar button need an explicit display:none rule.
    assert "#composeSheet[hidden] { display: none; }" in html
    assert ".devicebar .write-during[hidden] { display: none; }" in html

    js = _script(html)

    # The screen switcher must keep the device-bar affordance in sync, and
    # only the idle screens (start/ready/compose) may hide it. Reply,
    # cooldown, processing, and reply-text keep it visible.
    go_screen = _fn(js, "goScreen")
    assert "syncWriteDuring();" in go_screen
    sync = _fn(js, "syncWriteDuring")
    assert 'S.currentScreen === "start"' in sync
    assert 'S.currentScreen === "ready"' in sync
    assert 'S.currentScreen === "compose"' in sync
    assert 'btn.hidden = !S.opened || isIdle || (sheet && !sheet.hidden);' in sync

    opened = _fn(js, "openComposeSheet")
    assert "sheet.hidden = false;" in opened
    assert "syncWriteDuring();" in opened
    assert "input.focus();" in opened

    closed = _fn(js, "closeComposeSheet")
    assert "sheet.hidden = true;" in closed
    assert "S.sheetBusy = false;" in closed

    sent = _fn(js, "sendSheetComposed")
    assert 'send("/api/ziv/message"' in sent
    assert "closeComposeSheet();" in sent
    assert "goScreen(" not in sent, (
        "sending from the busy sheet must not navigate away from the turn"
    )
    assert 'disarmRedial("you sent manually")' in sent

    # The queued arrival cue is felt on the wrist but must not switch the
    # phone to its listening screen while the current turn is still playing.
    on_haptic = _fn(js, "onHaptic")
    assert 'String(frame.why || "").indexOf("queued") !== 0' in on_haptic

    # The settle timer must live in the cancellable stage list: a queued
    # replay's first text/cell frame clears it, so the starter's cooldown
    # cannot blank the screen mid-replay.
    finished = _fn(js, "finishReply")
    assert "S.stageTimers.push(setTimeout(" in finished

    # Every control is wired to the visible path, not exposed as dead markup.
    for wiring in (
        'document.getElementById("btnWriteDuring").addEventListener("click", openComposeSheet);',
        'document.getElementById("btnSheetSend").addEventListener("click", sendSheetComposed);',
        'document.getElementById("btnSheetCancel").addEventListener("click", function () {',
        'document.getElementById("composeSheetInput").addEventListener("input", function () {',
    ):
        assert wiring in js
