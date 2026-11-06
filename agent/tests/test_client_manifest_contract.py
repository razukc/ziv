"""Contract: the install surface names the project the way the project does.

The browser's install prompt draws the app's name and description from
``agent/ziv_client/ziv_manifest.json``. Those strings are the product's own
one-line identity, so this test pins them: a rename of the product, or a
change of the one-sentence description, must be made here *and* in the
manifest on purpose, never by one side drifting.

The manifest is read as JSON — nothing is imported from the client.
"""

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / "agent" / "ziv_client" / "ziv_manifest.json"

#: The pinned identity. Change both lines and the manifest together.
PRODUCT_NAME = "Ziv — a haptic message channel"
PRODUCT_DESCRIPTION = (
    "A haptic message channel for deaf-blind users, and anyone who needs a "
    "quiet, glance-free reply. Phone demo today; wrist band next."
)


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def test_manifest_name_is_the_product_name():
    """The installed app's name is the product's name, unchanged."""
    assert _manifest().get("name") == PRODUCT_NAME, (
        f"manifest name drifted from the pinned product name: "
        f"{_manifest().get('name')!r} != {PRODUCT_NAME!r}"
    )


def test_manifest_description_is_the_product_description():
    """The install prompt's description is the product's one-liner, unchanged."""
    assert _manifest().get("description") == PRODUCT_DESCRIPTION, (
        "manifest description drifted from the pinned product description: "
        f"{_manifest().get('description')!r} != {PRODUCT_DESCRIPTION!r}"
    )


def test_manifest_short_name_is_the_working_title():
    """The home-screen label is the working title, nothing longer."""
    assert _manifest().get("short_name") == "Ziv"
