"""Two-sided contract: the PWA badge and the server's health payload.

The queue badge renders straight from ``GET /api/ziv/health`` and renders
NOTHING when a key is missing or not a number — so the key names are a wire
contract between two files, and no single-side test owned it. The server
side is pinned with real HTTP values by
``test_ziv_server.py::test_health_payload_serves_the_pwa_badge_contract``.
This file pins the OTHER side hermetically: what the client's badge code
actually reads, parsed from its own source, must be exactly the key set the
server test pins. Rename either side and the suite fails HERE — not on a
phone with a silently blank badge.
"""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_CLIENT = _ROOT / "ziv_client" / "index.html"
_SERVER = _ROOT / "ziv_server.py"

#: The pinned contract — top-level health keys the badge reads (the queue
#: line AND the schedule line), plus the one nested read. Exact on the
#: client side (it may read nothing else); the server may carry extra keys
#: the badge ignores, but must carry these.
PINNED_TOP = {
    "gate_queue",
    "gate_queue_cap",
    "queue_rejections",
    "schedule_pending",
    "schedule_cap",
    "schedule_corrupt",
}
PINNED_NESTED = {("queue_rejections", "per_minute")}


def _client_js() -> str:
    html = _CLIENT.read_text(encoding="utf-8")
    m = re.search(r"<script>(.*)</script>", html, re.S)
    assert m, "the client's inline script is missing"
    return m.group(1)


def _fn(js: str, name: str) -> str:
    """One top-level function's body: from its signature to the first
    closing brace at column 0 (the client's house style closes there)."""
    m = re.search(r"function %s\(" % re.escape(name), js)
    assert m, "client function %s() is missing" % name
    body = re.search(r"\{(.*?)\n\}", js[m.start():], re.S)
    assert body, "could not isolate %s()'s body" % name
    return body.group(1)


def test_badge_reads_exactly_the_pinned_health_keys():
    """The client side, exact: renderQueueBadge reads the queue line's keys
    (gate_queue, gate_queue_cap, queue_rejections) and the schedule line's
    (schedule_pending, schedule_cap, schedule_corrupt) — nothing else. A
    7th read would be an unpinned dependency and must fail here until the
    server test pins it too."""
    top = set(re.findall(r"\bh\.(\w+)\b", _fn(_client_js(), "renderQueueBadge")))
    assert top == PINNED_TOP, top


def test_badge_nested_read_is_exactly_per_minute():
    """The refusal rate is the one nested read: queue_rejections.per_minute."""
    nested = set(
        re.findall(r"\bh\.(\w+)\.(\w+)", _fn(_client_js(), "renderQueueBadge"))
    )
    assert nested == PINNED_NESTED, nested


def test_badge_type_guards_still_protect_the_render():
    """The server test pins numeric types; the client's typeof guards are
    the consuming half of that contract — 'simplifying' them away would
    turn a wrong-type payload into a NaN badge instead of a blank one.
    The schedule line guards its own pair (pending/cap); the corrupt flag
    is consumed by strict identity (``=== true``), so a string "false" or
    a missing key can never render a corrupt badge."""
    body = _fn(_client_js(), "renderQueueBadge")
    assert 'typeof depth !== "number"' in body
    assert 'typeof cap !== "number"' in body
    assert 'typeof pending === "number"' in body
    assert 'typeof schedCap === "number"' in body
    assert 'schedCorrupt === true' in body


def test_badge_polls_the_pinned_endpoint():
    """The transport half: the badge's numbers come from /api/ziv/health —
    the same endpoint the server test pins."""
    body = _fn(_client_js(), "pollQueueBadge")
    assert '"/api/ziv/health"' in body


def test_server_carries_every_key_the_badge_reads():
    """The server side: health()'s literal payload contains the pinned
    top-level keys (queue line AND schedule line), and
    _RejectionStats.snapshot() contains per_minute — so a rename on either
    file trips this or the value-level server test."""
    src = _SERVER.read_text(encoding="utf-8")

    health = re.search(
        r"def health\(\) -> dict\[str, Any\]:(.*?)\n\n@app\.", src, re.S
    )
    assert health, "health() is missing"
    health_keys = set(re.findall(r'"(\w+)":', health.group(1)))
    missing = PINNED_TOP - health_keys
    assert not missing, f"health() no longer carries {sorted(missing)}"

    snap = re.search(r"def snapshot\(self\)(.*?)\n    def ", src, re.S)
    assert snap, "_RejectionStats.snapshot() is missing"
    snap_keys = set(re.findall(r'"(\w+)":', snap.group(1)))
    assert "per_minute" in snap_keys, snap_keys
