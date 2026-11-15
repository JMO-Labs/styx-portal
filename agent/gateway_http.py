"""HTTP handlers for the gateway: index page, favicon, files listing, selkies proxy.

Each make_* factory returns an aiohttp handler closed over its settings;
gateway.create_app wires them to routes.
"""
import asyncio
import os
import posixpath
import socket
from pathlib import Path

import aiohttp
import favicon
import refit
import yarl
from aiohttp import web
from multidict import CIMultiDict
from codecpref import inject_codecpref
from gateway_html import (
    inject_cursor_hide, inject_touch_scroll, inject_idle_watchdog, inject_webrtc,
    inject_gamemode, inject_title, inject_favicon,
)

HOP = {"host", "connection", "keep-alive", "transfer-encoding", "upgrade",
       "authorization", "origin", "content-length", "accept-encoding"}


def make_index(upstream, refit_file, seat_dir, icon_dir, idle_timeout_s, idle_lead_s, idle_enabled):
    async def index(_request):
        hold = web.Response(text=refit.HOLD_HTML, content_type="text/html",
                            headers={"Cache-Control": "no-store", "X-Styx-Hold": "1"})
        if refit_file and refit.pending(refit_file):
            return hold
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s, \
                    s.get(upstream() + "/", allow_redirects=False) as r:
                if r.status != 200:
                    hdr = {"Location": r.headers["Location"]} if "Location" in r.headers else {}
                    return web.Response(status=r.status, body=await r.read(), headers=hdr)
                html = await r.text()
        except aiohttp.ClientError:
            if seat_dir:            # GNOME seat: selkies restarting after a refit
                return hold
            return web.Response(status=502, text="stream backend unavailable")
        except asyncio.TimeoutError:
            return web.Response(status=504, text="stream backend timed out")
        html = inject_title(html, socket.gethostname())
        icon = favicon.read(Path(icon_dir)) if icon_dir else None
        if icon:
            html = inject_favicon(html, icon[2])
        html = inject_idle_watchdog(html, idle_timeout_s, idle_lead_s, idle_enabled)
        html = inject_webrtc(html, True)   # sidebar may pick WebRTC: shim arms on signaling open
        html = inject_gamemode(html)
        html = inject_codecpref(html)
        html = inject_cursor_hide(html, bool(seat_dir))
        html = inject_touch_scroll(html)
        html = refit.inject_reload(html, bool(seat_dir))
        return web.Response(text=html, content_type="text/html")
    return index


def make_favicon(icon_dir):
    async def styx_favicon(_request):
        icon = favicon.read(Path(icon_dir)) if icon_dir else None
        if not icon:
            return web.Response(status=404)
        return web.Response(body=icon[0], content_type=icon[1], headers={
            "Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy":
                "default-src 'none'; style-src 'unsafe-inline'; sandbox"})
    return styx_favicon


def make_proxy(upstream, state_file, log, timeout):
    """timeout: callable returning the aiohttp ClientTimeout (read per request)."""
    def _relative_location(request, loc):
        """Absolute-path redirects would escape a /w/<slug> prefix; make them
        relative to the request path."""
        if not loc.startswith("/") or loc.startswith("//"):
            return loc
        path, sep, query = loc.partition("?")
        rel = posixpath.relpath(path, posixpath.dirname(request.path) or "/")
        if path.endswith("/") and not rel.endswith("/"):
            rel += "/"
        return rel + sep + query

    async def forward(request, raw_path_qs):
        """Stream request to selkies and its response back, as-is."""
        headers = CIMultiDict()
        headers.extend((k, v) for k, v in request.headers.items()
                       if k.lower() not in HOP)
        body = await request.read() if request.body_exists else None
        url = yarl.URL(upstream() + raw_path_qs, encoded=True)
        resp = None
        try:
            async with aiohttp.ClientSession(
                    auto_decompress=False, timeout=timeout()) as s, s.request(
                    request.method, url, headers=headers, data=body,
                    allow_redirects=False) as r:
                out = CIMultiDict()
                out.extend((k, v) for k, v in r.headers.items()
                           if k.lower() not in HOP)
                if "Location" in out:
                    out["Location"] = _relative_location(request, out["Location"])
                resp = web.StreamResponse(status=r.status, headers=out)
                await resp.prepare(request)
                async for chunk in r.content.iter_chunked(64 * 1024):
                    await resp.write(chunk)
                await resp.write_eof()
                return resp
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if resp is not None and resp.prepared:
                # headers already sent: drop the connection, never append a 2nd response
                resp.force_close()
                if request.transport:
                    request.transport.close()
                raise
            if isinstance(e, asyncio.TimeoutError):
                return web.Response(status=504, text="stream backend timed out")
            return web.Response(status=502, text="stream backend unavailable")

    async def http_proxy(request):
        """Everything else (client assets, /api/* REST) goes to selkies as-is."""
        resp = await forward(request, request.rel_url.raw_path_qs)
        if request.method == "POST" and request.path.endswith("/api/switch") and 200 <= resp.status < 300:
            await _remember_mode(request)
        return resp

    async def _remember_mode(request):
        """Keep the sidebar's transport pick so a restarted/promoted selkies starts in it."""
        try:
            mode = (await request.json()).get("mode")
        except Exception:
            return
        if mode not in ("webrtc", "websockets") or not state_file:
            return
        path = os.path.join(os.path.dirname(state_file), "stream-mode")  # = health.STREAM_MODE_NAME
        with open(path + ".tmp", "w") as f:
            f.write(mode)
        os.replace(path + ".tmp", path)
        log(f"viewer switched transport to {mode} (kept for restarts)")
    return http_proxy, forward


def make_files(files_dir):
    async def files(request):
        # Hand-rolled index: aiohttp's show_index emits ABSOLUTE hrefs
        # (/files/x), which escape the portal's /w/{sub} prefix and land on
        # the SPA (X-Frame-Options: DENY -> blocked iframe). Relative links
        # survive any prefix.
        import html as _html
        from pathlib import Path
        from urllib.parse import quote
        base = Path(files_dir).resolve()
        rel = request.match_info.get("path", "")
        target = (base / rel).resolve() if rel else base
        if not (target == base or target.is_relative_to(base)):
            raise web.HTTPForbidden()
        if target.is_file():
            return web.FileResponse(target)
        if not target.is_dir():
            raise web.HTTPNotFound()
        if not request.path.endswith("/"):
            # relative redirect keeps the reverse-proxy prefix intact
            raise web.HTTPMovedPermanently(quote(target.name) + "/")
        items = sorted(target.iterdir(),
                       key=lambda p: (not p.is_dir(), p.name.lower()))
        rows = "".join(
            f'<li><a href="{quote(p.name)}{"/" if p.is_dir() else ""}">'
            f'{_html.escape(p.name)}{"/" if p.is_dir() else ""}</a></li>'
            for p in items) or "<li><em>empty</em></li>"
        up = '<li><a href="../">../</a></li>' if target != base else ""
        body = (f"<!doctype html><meta charset='utf-8'><title>Files</title>"
                f"<style>body{{font:14px sans-serif;background:#fff;"
                f"color:#222;padding:1.5em}}li{{margin:.25em 0}}</style>"
                f"<h2>{_html.escape(str(target))}</h2><ul>{up}{rows}</ul>")
        return web.Response(text=body, content_type="text/html")
    return files
