#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright>=1.40"]
# ///
"""Get a lucida.to Cloudflare clearance ("the token") with no lucidadl installed.

Opens a real Chromium window, lets Cloudflare's check pass (click it if it asks), then
saves the clearance as JSON and/or uploads it to a lucidarr server.

    uv run lucida_token.py                       # needs only: uv
    python lucida_token.py                       # needs: pip install playwright
    python lucida_token.py --push http://lucidarr:8787       # upload (asks for password)
    python lucida_token.py --push http://lucidarr:8787 --every 360   # refresh every 6 h

First run on a machine: `python -m playwright install chromium` (or pass --install).

The JSON matches lucidadl's clearance.json ({"cf_clearance", "ua", "ts"}), so the file
can also be copied to <lucidadl app data>/clearance.json by hand. Treat it like a
password: it is a logged-in-grade cookie for your IP address.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Optional, Tuple

LUCIDA = "https://lucida.to"
DEFAULT_PROFILE = os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share"),
    "lucida-token", "profile")

_CHALLENGE_TITLES = ("just a moment", "attention required", "un instant",
                     "checking your browser", "verifying", "verification")
_CHALLENGE_BODY = ('id="challenge-form"', "cf-chl-widget", "window._cf_chl_opt",
                   "enable javascript and cookies to continue")


def is_challenge(title: str, html: str) -> bool:
    """True while the page is still Cloudflare's interstitial rather than lucida.to."""
    t = (title or "").lower()
    if any(s in t for s in _CHALLENGE_TITLES) or t.strip() == "moment":
        return True
    h = (html or "").lower()
    return any(m in h for m in _CHALLENGE_BODY)


def build_payload(cf: Optional[str], ua: str, now: Optional[float] = None) -> dict:
    return {"cf_clearance": cf, "ua": ua, "ts": time.time() if now is None else now}


def save(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # owner-only
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)


def push(url: str, password: str, payload: dict, timeout: float = 20.0) -> None:
    """Upload to a lucidarr web page (`lucida web`). Raises RuntimeError with a reason."""
    req = urllib.request.Request(
        url.rstrip("/") + "/api/clearance", method="POST",
        data=json.dumps({"cf_clearance": payload["cf_clearance"],
                         "ua": payload["ua"]}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {password}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise RuntimeError(f"server answered {resp.status}")
    except urllib.error.HTTPError as e:
        hint = " (wrong password?)" if e.code == 403 else ""
        raise RuntimeError(f"server answered {e.code}{hint}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"could not reach {url}: {e.reason}") from e


def fetch_clearance(profile: str, timeout: int, hidden: bool, channel: Optional[str]
                    ) -> Tuple[Optional[str], str]:
    """Drive Chromium to lucida.to and return (cf_clearance cookie or None, user agent)."""
    try:
        from playwright.sync_api import sync_playwright, Error as PlaywrightError
    except ImportError:
        sys.exit("Playwright is not installed. Run: pip install playwright "
                 "&& python -m playwright install chromium   (or use: uv run %s)"
                 % os.path.basename(__file__))
    args = ["--disable-blink-features=AutomationControlled", "--no-first-run"]
    if hidden:  # still headed (headless is challenged), just off-screen
        args += ["--window-position=-32000,-32000", "--window-size=1366,900"]
    os.makedirs(profile, exist_ok=True)
    with sync_playwright() as pw:
        kwargs = dict(user_data_dir=profile, headless=False, args=args,
                      viewport={"width": 1366, "height": 900})
        try:
            ctx = (pw.chromium.launch_persistent_context(channel=channel, **kwargs)
                   if channel else pw.chromium.launch_persistent_context(**kwargs))
        except PlaywrightError as e:
            sys.exit(f"Could not start Chromium: {e}\n"
                     "Try: python -m playwright install chromium (or --install)")
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_default_timeout(60_000)
            page.goto(LUCIDA + "/", wait_until="domcontentloaded")
            print("Waiting for Cloudflare... complete the check in the window if asked.")
            deadline = time.time() + timeout
            while time.time() < deadline:
                if not is_challenge(page.title(), page.content()):
                    break
                page.wait_for_timeout(1500)
            else:
                sys.exit(f"Cloudflare was not cleared within {timeout}s.")
            cookies = ctx.cookies(LUCIDA)
            cf = next((c["value"] for c in cookies if c["name"] == "cf_clearance"), None)
            ua = page.evaluate("() => navigator.userAgent").replace("HeadlessChrome", "Chrome")
            return cf, ua
        finally:
            ctx.close()


def run_once(args) -> int:
    cf, ua = fetch_clearance(args.profile, args.timeout, args.hidden, args.channel)
    payload = build_payload(cf, ua)
    note = "cookie present" if cf else "no cookie issued (user agent only)"
    if args.out:
        save(args.out, payload)
        print(f"Saved {args.out} ({note})")
    if args.push:
        try:
            push(args.push, args.password, payload)
        except RuntimeError as e:
            print(f"Upload failed: {e}", file=sys.stderr)
            return 1
        print(f"Uploaded to {args.push}")
    if not args.out and not args.push:
        print(json.dumps(payload))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", default=None,
                    help="write the clearance JSON here (default: print it, unless --push)")
    ap.add_argument("--push", metavar="URL", default=None,
                    help="upload to a lucidarr web page, e.g. http://lucidarr:8787")
    ap.add_argument("--password", default=os.environ.get("LUCIDARR_WEB_PASSWORD"),
                    help="web page password (env LUCIDARR_WEB_PASSWORD; prompted if unset)")
    ap.add_argument("--every", type=int, default=0, metavar="MIN",
                    help="repeat every MIN minutes (keep refreshing); 0 = once")
    ap.add_argument("--timeout", type=int, default=180, help="seconds to wait for the check")
    ap.add_argument("--hidden", action="store_true", help="move the window off-screen")
    ap.add_argument("--profile", default=DEFAULT_PROFILE, help="browser profile folder")
    ap.add_argument("--channel", default=os.environ.get("LUCIDA_CHANNEL"),
                    help="use an installed browser, e.g. chrome (env LUCIDA_CHANNEL)")
    ap.add_argument("--install", action="store_true",
                    help="install Playwright's Chromium first")
    args = ap.parse_args(argv)

    if args.install:
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    if args.push and not args.password:
        args.password = getpass.getpass("lucidarr web password: ")
    while True:
        code = run_once(args)
        if not args.every:
            return code
        print(f"Next refresh in {args.every} min (Ctrl+C to stop).")
        try:
            time.sleep(args.every * 60)
        except KeyboardInterrupt:
            return code


if __name__ == "__main__":
    sys.exit(main())
