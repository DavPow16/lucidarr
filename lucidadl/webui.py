"""Tiny password-protected web page for lucidarr: Cloudflare clearance status/upload, and
a view of lucidarr's recent log (``/log``).

A headless server often cannot clear lucida.to's Cloudflare check by itself. Either a
FlareSolverr/Byparr service does it (``[Lucida] solver_url``), or any machine with a desktop
can (``lucida setup``) and this page lets you upload that machine's saved clearance
(cf_clearance cookie + user agent) through a browser or ``lucida push-clearance``. It is
plain HTTP meant for a trusted LAN: set a password, and do not expose the port to the
internet.
"""

from __future__ import annotations

import hmac
import html
import base64
import json
import re
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple
from urllib.parse import parse_qs

from . import lidarr, session

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


def _page(message: str = "", ok: bool = True, solver: str = "") -> bytes:
    try:
        with open(session.CLEARANCE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        status = (f"A clearance is saved (updated {_age(float(d.get('ts', 0)))} ago, "
                  f"cookie {'present' if d.get('cf_clearance') else 'absent'}).")
    except Exception:
        status = "No clearance is saved yet."
    if solver:
        status = (f"Cloudflare is cleared automatically by the solver at {solver}. "
                  + status)
    note = (f'<p class="{"ok" if ok else "err"}">{html.escape(message)}</p>'
            if message else "")
    logo = '<img class="logo" src="/logo.svg" alt="lucidarr">' if LOGO else "<h1>lucidarr</h1>"
    return f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>lucidarr &middot; clearance</title><link rel="icon" href="/logo.svg" type="image/svg+xml">
<style>
:root{{color-scheme:dark;--green:#009252;--panel:#b4dcc3;--field:#6fc79a;--ink:#101510}}
*{{box-sizing:border-box}}
html{{min-height:100%;background:#0b0b0b}}
body{{margin:0;min-height:100vh;font:16px/1.5 system-ui,sans-serif;color:var(--ink);
background:linear-gradient(180deg,#303030 0%,#1b1b1b 38%,#0b0b0b 100%) fixed}}
main{{max-width:36rem;margin:0 auto;padding:1.5rem 16px 3rem}}
.logo{{display:block;width:min(100%,18rem);height:auto;margin:0 auto 1.25rem}}
.bar{{background:#3a3a3a;color:#eee;text-align:center;font-weight:700;letter-spacing:.04em;
text-transform:uppercase;padding:.55rem 1rem;border-radius:18px 18px 0 0}}
.card{{background:var(--panel);padding:1.25rem;border-radius:0 0 18px 18px}}
.status{{margin:0 0 1rem;color:#1f3a2b}}
label{{display:block;font-weight:700;margin:.75rem 0 .25rem}}
textarea,input{{width:100%;font:inherit;padding:.6rem;border:2px solid var(--ink);
border-radius:6px;background:var(--field);color:var(--ink)}}
textarea{{height:9rem;font-family:ui-monospace,monospace;font-size:.85rem}}
::placeholder{{color:#25503a}}
textarea:focus,input:focus{{outline:3px solid #fff;outline-offset:1px}}
button{{margin-top:1rem;width:100%;font:inherit;font-weight:700;padding:.7rem;color:#fff;
background:var(--green);border:2px solid var(--ink);border-radius:6px;cursor:pointer}}
button:hover{{filter:brightness(1.12)}}
.ok,.err{{margin:0 0 1rem;padding:.6rem .8rem;border-radius:6px;font-weight:700}}
.ok{{background:#e3f6ea;color:#075c2f}}.err{{background:#fde8ea;color:#9b1020}}
code{{background:rgba(0,0,0,.12);padding:.05rem .3rem;border-radius:4px}}
summary{{cursor:pointer;font-weight:700;margin:.25rem 0 .5rem}}
.nav{{margin:1.25rem 0 0;text-align:center}}.nav a{{color:#075c2f;font-weight:700}}
</style><main>{logo}<div class="bar">Cloudflare clearance</div><div class="card">
<p class="status">{html.escape(status)}</p>{note}
{"<details><summary>Upload a clearance by hand instead (fallback)</summary>" if solver else ""}
<form method="post" action="/upload">
<label for="p">Paste <code>clearance.json</code> from the machine where you ran
<code>lucida setup</code></label>
<textarea id="p" name="pasted" placeholder='{{"cf_clearance": "...", "ua": "..."}}'></textarea>
<label for="pw">Password</label><input id="pw" type="password" name="password" required>
<button type="submit">Upload</button></form>{"</details>" if solver else ""}
<p class="nav"><a href="/log">View lucidarr log &rarr;</a></p></div></main>""".encode()


LOG_LINES = 400
_BAD = re.compile(r"\b(ERROR|CRITICAL)\b")
_WARN = re.compile(r"\bWARNING\b")


def tail_log(path: str, lines: int = LOG_LINES, max_bytes: int = 128 * 1024) -> str:
    """The last ``lines`` lines of the log file ('' if it does not exist yet)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            raw = f.read()
    except OSError:
        return ""
    text = raw.decode("utf-8", "replace").splitlines()
    if size > max_bytes and text:
        text = text[1:]  # the first line is probably cut in half
    return "\n".join(text[-lines:])


def _log_page(text: str) -> bytes:
    rows = []
    for line in text.splitlines():
        cls = "e" if _BAD.search(line) else "w" if _WARN.search(line) else ""
        rows.append(f'<span class="{cls}">{html.escape(line)}</span>' if cls else html.escape(line))
    body = "\n".join(rows) or "No log yet. It appears after the next lucidarr cycle starts."
    logo = '<img class="logo" src="/logo.svg" alt="lucidarr">' if LOGO else ""
    return f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>lucidarr &middot; log</title><link rel="icon" href="/logo.svg" type="image/svg+xml">
<style>
:root{{color-scheme:dark}}
*{{box-sizing:border-box}}
body{{margin:0;background:#0b0b0b;color:#d8e8de;font:14px/1.45 system-ui,sans-serif}}
header{{display:flex;align-items:center;gap:1rem;padding:.75rem 16px;background:#303030}}
header .logo{{height:2.2rem;width:auto}}
header a{{color:#7fe0ad;margin-left:auto}}
pre{{margin:0;padding:12px 16px 3rem;white-space:pre-wrap;word-break:break-word;
font:12.5px/1.45 ui-monospace,monospace}}
.e{{color:#ff8a94}}.w{{color:#ffd37a}}
</style><header>{logo}<span>Last {LOG_LINES} lines &middot; refreshes every 30 s</span>
<a href="/">&larr; Clearance</a></header><pre>{body}</pre>
<script>window.scrollTo(0,document.body.scrollHeight)</script>""".encode()


def make_handler(password: str, solver_url: str = ""):
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

        def _basic_ok(self) -> bool:
            """HTTP Basic auth: any user name, the web password."""
            head = self.headers.get("Authorization", "")
            if head.startswith("Basic "):
                try:
                    supplied = base64.b64decode(head[6:]).decode("utf-8", "replace")
                    return self._authorized(supplied.partition(":")[2])
                except ValueError:
                    pass
            return False

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise BadSubmission("request too large")
            return self.rfile.read(n)

        def do_GET(self):
            route = self.path.split("?")[0]
            if route == "/":
                self._send(200, _page(solver=solver_url))
            elif route == "/log":
                if not self._basic_ok():
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="lucidarr"')
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self._send(200, _log_page(tail_log(lidarr.LOG_PATH)))
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
                        return self._send(403, _page("Wrong password.", False, solver_url))
                    cf, ua = parse_submission(first("pasted"))
                    session.save_clearance(cf, ua)
                    return self._send(200, _page("Saved. The next lucidarr cycle will use it.", True, solver_url))
                self._send(404, b"not found", "text/plain")
            except (BadSubmission, ValueError) as e:
                if path == "/api/clearance":
                    self._send(400, json.dumps({"error": str(e)}).encode(), "application/json")
                else:
                    self._send(400, _page(f"Rejected: {e}", False, solver_url))

    return Handler


def make_server(host: str, port: int, password: str, solver_url: str = "") -> ThreadingHTTPServer:
    if not password:
        raise ValueError("a web password is required")
    return ThreadingHTTPServer((host, port), make_handler(password, solver_url))
