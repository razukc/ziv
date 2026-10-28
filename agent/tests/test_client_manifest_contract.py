"""Contract: the install surface names the project the way the cover does.

The browser's install prompt draws the app's name and description from
``agent/ziv_client/ziv_manifest.json``. Those strings are not copy of their
own: they are the cover slide's title and caption, authored in
``media/make_gallery.py`` (``GALLERY[0]``, the ``hero.png`` entry). Editing
either side alone leaves the installed app describing a project the page no
longer shows.

Both sides are read as data — the manifest as JSON, the gallery as an AST
literal — so this test neither imports ``make_gallery`` (and its Pillow
dependency) nor copies the strings into a third place that could drift too.
"""

import ast
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / "agent" / "ziv_client" / "ziv_manifest.json"
_GALLERY = _ROOT / "media" / "make_gallery.py"
_COVER_FILE = "hero.png"


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def _cover() -> dict:
    """The cover entry from GALLERY, without importing the renderer."""
    tree = ast.parse(_GALLERY.read_text(encoding="utf-8"))
    gallery = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "GALLERY"
            for target in node.targets
        ):
            gallery = ast.literal_eval(node.value)
            break
    assert gallery is not None, "GALLERY is missing from media/make_gallery.py"

    covers = [item for item in gallery if item.get("file") == _COVER_FILE]
    assert len(covers) == 1, (
        f"expected exactly one {_COVER_FILE!r} entry in GALLERY, found {len(covers)}"
    )
    return covers[0]


def test_manifest_name_is_the_cover_title():
    """The installed app's name is the cover slide's title, unchanged."""
    manifest, cover = _manifest(), _cover()
    assert manifest.get("name") == cover.get("title"), (
        "manifest name drifted from the cover title in media/make_gallery.py: "
        f"{manifest.get('name')!r} != {cover.get('title')!r}"
    )


def test_manifest_description_is_the_cover_caption():
    """The install prompt's description is the cover caption, unchanged."""
    manifest, cover = _manifest(), _cover()
    assert manifest.get("description") == cover.get("caption"), (
        "manifest description drifted from the cover caption in "
        f"media/make_gallery.py: {manifest.get('description')!r} != "
        f"{cover.get('caption')!r}"
    )
