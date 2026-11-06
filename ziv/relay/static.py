"""ziv.relay.static — the relay serves the built front ends.

``/client/`` is the web device renderer and ``/console/`` the console, each
read from a ``dist`` directory the build produced (``ZIV_CLIENT_DIST``,
``ZIV_CONSOLE_DIST``). Both are single-page apps with content-hashed assets:

* a hashed asset (``main.QXL6QWXL.js``, ``styles-VVX3X44Y.css``, their maps)
  is immutable: ``Cache-Control: public, max-age=31536000, immutable``;
* ``index.html`` and everything else (``manifest.json``) is ``no-store``, so a
  new build is picked up on the next load;
* a path that names no file falls back to ``index.html`` (the console routes
  on the hash, the client has one page); a path with an extension that names
  no file is a plain 404, so a missing asset is never silently an HTML page.

Paths are resolved inside the directory only; ``..`` and absolute paths are
refused before the file system is touched. Nothing here touches the relay's
state, and no credential ever reaches a static URL.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

IMMUTABLE = "public, max-age=31536000, immutable"
NO_STORE = "no-store"
# <name>.<HASH>.js | <name>-<HASH>.css | either with .map — esbuild's [hash] is 8 upper-case base32 chars
HASHED = re.compile(r"^[A-Za-z0-9_]+[.-][A-Z0-9]{8}\.(?:js|css|woff2?|png|svg|webp)(?:\.map)?$")
MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}


def cache_control_for(name: str) -> str:
    return IMMUTABLE if HASHED.match(name) else NO_STORE


def media_type_for(path: Path) -> str:
    return MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def resolve_inside(root: Path, rel: str) -> Path | None:
    """The file ``rel`` names inside ``root``, or None when it escapes or is not a file."""
    if not rel or rel.startswith(("/", "\\")) or "\x00" in rel:
        return None
    parts = [p for p in re.split(r"[\\/]+", rel) if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    candidate = root.joinpath(*parts)
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, RuntimeError, OSError):
        return None
    if not resolved.is_relative_to(root) or not resolved.is_file():
        return None
    return resolved


def dist_router(prefix: str, directory: str | Path) -> APIRouter:
    """Routes for one built front end under ``prefix`` (``/client`` or ``/console``)."""
    root = Path(directory).resolve()
    index = root / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"{directory} has no index.html; build the front end first")
    prefix = "/" + prefix.strip("/")
    router = APIRouter()

    def file(path: Path) -> Response:
        return FileResponse(path, media_type=media_type_for(path),
                            headers={"Cache-Control": cache_control_for(path.name)})

    @router.get(prefix, include_in_schema=False)
    async def _bare(request: Request) -> Response:
        return RedirectResponse(url=prefix + "/", status_code=307)

    @router.get(prefix + "/", include_in_schema=False)
    async def _index() -> Response:
        return file(index)

    @router.get(prefix + "/{rel:path}", include_in_schema=False)
    async def _asset(rel: str) -> Response:
        found = resolve_inside(root, rel)
        if found is not None:
            return file(found)
        last = rel.rsplit("/", 1)[-1]
        if "." in last:
            return Response(status_code=404, media_type="text/plain; charset=utf-8",
                            content="not found", headers={"Cache-Control": NO_STORE})
        return file(index)

    return router
