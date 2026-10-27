"""Contract: the dev band exposes only surfaces this build can perform.

The old shell offered **Wake band**, **Stand by**, and a listening screen whose
bar implied a microphone. None of it was wired to capture: no ``getUserMedia``,
no ``MediaRecorder``, no request to the relay's audio seam. The mic stays a
server-side held asset until an audio-capable endpoint exists, and this client
must not advertise it.

These tests pin the two properties that keep the redesign honest: no capture
path or capture copy, and no dead controls — every button in the page is wired
to a handler, and the removed wake/standby markup does not grow back.
"""

from html.parser import HTMLParser
import re
from pathlib import Path

CLIENT = Path(__file__).resolve().parents[1] / "ziv_client" / "index.html"

REMOVED_IDS = {
    "btnUnlock",
    "btnCancelLocked",
    "btnCancelListen",
    "screen-off",
    "screen-locked",
    "screen-listening",
}
REAL_SCREENS = {
    "screen-start",
    "screen-ready",
    "screen-incoming",
    "screen-processing",
    "screen-reply-text",
    "screen-compose",
    "screen-sending",
    "screen-reply",
    "screen-cooldown",
}
CAPTURE_APIS = (
    "getUserMedia",
    "MediaRecorder",
    "AudioContext",
    "SpeechRecognition",
    "mediaDevices",
)
CAPTURE_CLAIMS = (
    "listening for your cue",
    "capturing the wearer",
    "Talk to Omni",
    "mic records",
)
HELD_NOTE = "No microphone in this build"


class _Ids(HTMLParser):
    """Every element that carries an id, and its tag name."""

    def __init__(self) -> None:
        super().__init__()
        self.elements: dict[str, str] = {}
        self.duplicates: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ident = dict(attrs).get("id")
        if not ident:
            return
        if ident in self.elements:
            self.duplicates.append(ident)
        self.elements[ident] = tag


def _source() -> str:
    return CLIENT.read_text(encoding="utf-8")


def _parser(html: str) -> _Ids:
    parser = _Ids()
    parser.feed(html)
    assert not parser.duplicates, parser.duplicates
    return parser


def _script(html: str) -> str:
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert scripts, "the client's inline script is missing"
    return max(scripts, key=len)


def test_the_client_has_no_capture_path_or_capture_claims():
    """A microphone that cannot run is not a feature; neither is its copy."""
    html = _source()
    for api in CAPTURE_APIS:
        assert api not in html, (
            f"{api} is back in the client — the audio seam is server-side only "
            "until an audio-capable endpoint is configured"
        )
    lowered = html.lower()
    for claim in CAPTURE_CLAIMS:
        assert claim.lower() not in lowered, f"capture copy is back: {claim!r}"
    assert HELD_NOTE in html, (
        "the held-asset note is the only honest mention of the missing mic"
    )


def test_every_button_is_wired_and_the_dead_screens_are_gone():
    """No control may be decoration: Stand by was exactly that."""
    html = _source()
    parser = _parser(html)
    js = _script(html)

    for ident in REMOVED_IDS:
        assert ident not in parser.elements, f"{ident} came back without behavior"
    assert REAL_SCREENS <= set(parser.elements), REAL_SCREENS - set(parser.elements)

    for ident, tag in parser.elements.items():
        if tag != "button":
            continue
        assert f'getElementById("{ident}").addEventListener' in js, (
            f"#{ident} is visible but not wired to a handler"
        )


def test_the_judge_key_panel_is_one_shot_and_not_stored():
    """BYOK is a single request, not a saved credential: a collapsed panel,
    a password field, one route call, and no browser storage of the key."""
    html = _source()
    parser = _parser(html)
    js = _script(html)

    assert parser.elements.get("byokKey") == "input"
    assert parser.elements.get("btnByok") == "button"
    assert '<details class="byok" id="byok">' in html, "the panel must start collapsed"
    assert 'type="password"' in html
    assert "X-Nebius-Key" in html
    assert '"/api/ziv/compose"' in html

    for line in js.splitlines():
        if "byokKey" in line:
            assert "localStorage" not in line and "sessionStorage" not in line, (
                "the judge's key must never be written to browser storage"
            )
