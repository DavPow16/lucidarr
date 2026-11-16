"""Tiny password-protected web page for handing lucidarr a Cloudflare clearance.

A headless server often cannot clear lucida.to's Cloudflare check by itself, but any
machine with a desktop can (``lucida setup``). This page lets you upload that machine's
saved clearance (cf_clearance cookie + user agent) to the server through a browser or
``lucida push-clearance``. It is plain HTTP meant for a trusted LAN: set a password, and
do not expose the port to the internet.
"""

from __future__ import annotations

import hmac
import html
import json
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple
from urllib.parse import parse_qs

from . import session

MAX_BODY = 16 * 1024
try:
    LOGO = (Path(__file__).parent / "assets" / "lucidarr.svg").read_bytes()
except OSError:
    LOGO = b""


class BadSubmission(ValueError):
    pass


def _clean(value: str, name: str, limit: int) -> str:
    value = (value or "").strip()
    # These end up in HTTP headers: refuse anything that could inject a header.
    if len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise BadSubmission(f"{name} is too long or contains control characters")
    return value


def parse_submission(pasted: str = "", cf: str = "", ua: str = ""
                     ) -> Tuple[Optional[str], str]:
    """Accept either the pasted clearance.json or the two separate values."""
    if (pasted or "").strip():
        try:
            data = json.loads(pasted)
        except ValueError:
            raise BadSubmission("the pasted text is not valid JSON") from None
        if not isinstance(data, dict):
            raise BadSubmission("the pasted JSON must be an object")
        cf, ua = data.get("cf_clearance") or "", data.get("ua") or ""
    cf = _clean(str(cf or ""), "cf_clearance", 4096)
    ua = _clean(str(ua or ""), "user agent", 512)
    if not ua:
        raise BadSubmission("a user agent is required")
    return (cf or None), ua


def _age(ts: float) -> str:
    secs = max(0, int(time.time() - ts))
    for unit, n in (("d", 86400), ("h", 3600), ("min", 60)):
        if secs >= n:
            return f"{secs // n} {unit}"
    return f"{secs} s"


def _page(message: str = "", ok: bool = True) -> bytes:
    try:
        with open(session.CLEARANCE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        status = (f"A clearance is saved (uploaded {_age(float(d.get('ts', 0)))} ago, "
                  f"cookie {'present' if d.get('cf_clearance') else 'absent'}).")
    except Exception:
        status = "No clearance is saved yet."
    note = (f'<p class="{"ok" if ok else "err"}">{html.escape(message)}</p>'
            if message else "")
    logo = '<img class="logo" src="/logo.svg" alt="lucidarr">' if LOGO else "<h1>lucidarr</h1>"
    return f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>lucidarr &middot; clearance</title><link rel="icon" href="/logo.svg" type="image/svg+xml">
<style>
:root{{color-scheme:light;--green:#009252;--ink:#111;--muted:#5b6b62}}
*{{box-sizing:border-box}}
body{{margin:0;font:16px/1.5 system-ui,sans-serif;color:var(--ink);background:#f3f7f4}}
main{{max-width:36rem;margin:0 auto;padding:1.5rem 16px 3rem}}
.logo{{display:block;width:min(100%,18rem);height:auto;margin:0 auto 1rem}}
.card{{background:#fff;border:2px solid var(--ink);border-radius:14px;padding:1.25rem;
box-shadow:5px 5px 0 var(--green)}}
h2{{margin:0 0 .25rem;font-size:1.15rem}}.status{{color:var(--muted);margin:0 0 1rem}}
label{{display:block;font-weight:600;margin:.75rem 0 .25rem}}
textarea,input{{width:100%;font:inherit;padding:.6rem;border:2px solid var(--ink);
border-radius:8px;background:#fff;color:var(--ink)}}
textarea{{height:9rem;font-family:ui-monospace,monospace;font-size:.85rem}}
textarea:focus,input:focus{{outline:3px solid var(--green);outline-offset:1px}}
button{{margin-top:1rem;width:100%;font:inherit;font-weight:700;padding:.7rem;
color:#fff;background:var(--green);border:2px solid var(--ink);border-radius:8px;cursor:pointer}}
button:hover{{filter:brightness(1.08)}}
.ok,.err{{margin:0 0 1rem;padding:.6rem .8rem;border-radius:8px;font-weight:600}}
.ok{{background:#e3f6ea;color:#075c2f}}.err{{background:#fde8ea;color:#9b1020}}
code{{background:#eef3ef;padding:.05rem .3rem;border-radius:4px}}
</style><main>{logo}<div class="card"><h2>Cloudflare clearance</h2>
<p class="status">{html.escape(status)}</p>{note}
<form method="post" action="/upload">
<label for="p">Paste <code>clearance.json</code> from the machine where you ran
<code>lucida setup</code></label>
<textarea id="p" name="pasted" placeholder='{{"cf_clearance": "...", "ua": "..."}}'></textarea>
<label for="pw">Password</label><input id="pw" type="password" name="password" required>
<button type="submit">Upload</button></form></div></main>""".encode()


def make_handler(password: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "lucidarr"

        def log_message(self, *args):  # keep cookies/passwords out of any logs
            pass

        def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self, supplied: str) -> bool:
            good = hmac.compare_digest((supplied or "").encode(), password.encode())
            if not good:
                time.sleep(1.5)  # slow down password guessing
            return good

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise BadSubmission("request too large")
            return self.rfile.read(n)

        def do_GET(self):
            route = self.path.split("?")[0]
            if route == "/":
                self._send(200, _page())
            elif route == "/logo.svg" and LOGO:
                self._send(200, LOGO, "image/svg+xml")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            path = self.path.split("?")[0]
            try:
                raw = self._body()
                if path == "/api/clearance":
                    auth = self.headers.get("Authorization", "")
                    if not self._authorized(auth.removeprefix("Bearer ").strip()):
                        return self._send(403, b'{"error":"forbidden"}', "application/json")
                    data = json.loads(raw or b"{}")
                    cf, ua = parse_submission("", str(data.get("cf_clearance") or ""),
                                              str(data.get("ua") or ""))
                    session.save_clearance(cf, ua)
                    return self._send(200, b'{"ok":true}', "application/json")
                if path == "/upload":
                    form = parse_qs(raw.decode("utf-8", "replace"))
                    first = lambda k: (form.get(k) or [""])[0]
                    if not self._authorized(first("password")):
                        return self._send(403, _page("Wrong password.", False))
                    cf, ua = parse_submission(first("pasted"))
                    session.save_clearance(cf, ua)
                    return self._send(200, _page("Saved. The next lucidarr cycle will use it."))
                self._send(404, b"not found", "text/plain")
            except (BadSubmission, ValueError) as e:
                if path == "/api/clearance":
                    self._send(400, json.dumps({"error": str(e)}).encode(), "application/json")
                else:
                    self._send(400, _page(f"Rejected: {e}", False))

    return Handler


def make_server(host: str, port: int, password: str) -> ThreadingHTTPServer:
    if not password:
        raise ValueError("a web password is required")
    return ThreadingHTTPServer((host, port), make_handler(password))
