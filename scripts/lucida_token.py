#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright>=1.40"]
# ///
"""Get a lucida.to Cloudflare clearance ("the token") with no lucidadl installed.

Opens a real Chromium window, lets Cloudflare's check pass (click it if it asks), then
saves the clearance as JSON and/or uploads it to a lucidarr server.

    python lucida_token.py                       # first run offers to set itself up
    uv run lucida_token.py                       # or: needs only uv
    python lucida_token.py --push http://lucidarr:8787       # upload (asks for password)
    python lucida_token.py --push http://lucidarr:8787 --every 360   # refresh every 6 h

On a machine without Playwright it asks to create a private virtualenv (in
~/.local/share/lucida-token/venv, or $LUCIDA_TOKEN_HOME) and installs Playwright and
Chromium there; nothing is installed system-wide. Pass --yes to skip the question.

The JSON matches lucidadl's clearance.json ({"cf_clearance", "ua", "ts"}), so the file
can also be copied to <lucidadl app data>/clearance.json by hand. Treat it like a
password: it is a logged-in-grade cookie for your IP address.
"""

from __future__ import annotations

import argparse
import getpass
import importlib.util
import json
import os
import subprocess
import sys
import time
import venv
import urllib.error
import urllib.request
from typing import Optional, Tuple
from urllib.parse import urlsplit

LUCIDA = "https://lucida.to"
HOME_DIR = os.environ.get("LUCIDA_TOKEN_HOME") or os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share"),
    "lucida-token")
DEFAULT_PROFILE = os.path.join(HOME_DIR, "profile")
VENV_DIR = os.path.join(HOME_DIR, "venv")

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


def page_challenged(page) -> bool:
    """is_challenge() for a live page. While Cloudflare redirects, title()/content() raise
    ("the page is navigating"); that means "not settled yet", so keep waiting."""
    try:
        return is_challenge(page.title(), page.content())
    except Exception:
        return True


def wait_until_cleared(page, timeout: float) -> bool:
    """Poll until the page is lucida.to itself (not Cloudflare's interstitial)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not page_challenged(page):
            try:
                if urlsplit(page.url).netloc.endswith("lucida.to"):
                    return True
            except Exception:
                pass
        try:
            page.wait_for_timeout(1500)
        except Exception:
            time.sleep(1.5)
    return False


def read_user_agent(page, tries: int = 5) -> str:
    """navigator.userAgent, retried: the evaluation can race a final navigation."""
    last: Optional[Exception] = None
    for _ in range(tries):
        try:
            return page.evaluate("() => navigator.userAgent").replace("HeadlessChrome", "Chrome")
        except Exception as e:
            last = e
            try:
                page.wait_for_timeout(1000)
            except Exception:
                time.sleep(1)
    raise RuntimeError(f"could not read the browser's user agent: {last}")


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


# --- self-setup: a private virtualenv when Playwright is not installed ------------------

def have_playwright() -> bool:
    return importlib.util.find_spec("playwright") is not None


def venv_python() -> str:
    sub = "Scripts" if os.name == "nt" else "bin"
    return os.path.join(VENV_DIR, sub, "python.exe" if os.name == "nt" else "python")


def venv_ready() -> bool:
    py = venv_python()
    return os.path.exists(py) and subprocess.call(
        [py, "-c", "import playwright"], stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL) == 0


def bootstrap() -> None:
    """Create the private venv, install Playwright and Chromium into it."""
    print(f"Creating a private environment in {VENV_DIR} ...")
    try:
        venv.create(VENV_DIR, with_pip=True, clear=False)
    except Exception as e:  # e.g. Debian without python3-venv
        sys.exit(f"Could not create a virtualenv: {e}\n"
                 "Install your distro's python3-venv package, or `pip install playwright` "
                 "yourself and run this script again.")
    py = venv_python()
    subprocess.check_call([py, "-m", "pip", "install", "--quiet", "playwright>=1.40"])
    subprocess.check_call([py, "-m", "playwright", "install", "chromium"])


def ensure_playwright(assume_yes: bool) -> None:
    """Return when Playwright is importable here; else set up / switch to a private venv
    and re-run this script inside it (never returns in that case)."""
    if have_playwright():
        return
    if os.environ.get("LUCIDA_TOKEN_REEXEC"):
        sys.exit("Playwright is still not importable after setup; see the messages above.")
    if not venv_ready():
        if not assume_yes:
            if not sys.stdin.isatty():
                sys.exit("Playwright is not installed. Re-run with --yes to let this script "
                         f"create a private environment in {VENV_DIR}, or "
                         "`pip install playwright` yourself.")
            ans = input("Playwright is not installed. Create a private environment in\n"
                        f"  {VENV_DIR}\nand install Playwright + Chromium there? [Y/n] ")
            if ans.strip().lower() not in ("", "y", "yes"):
                sys.exit("Cancelled. Run: pip install playwright "
                         "&& python -m playwright install chromium")
        bootstrap()
    env = dict(os.environ, LUCIDA_TOKEN_REEXEC="1")
    py = venv_python()
    os.execve(py, [py, os.path.abspath(__file__)] + sys.argv[1:], env)


def fetch_clearance(profile: str, timeout: int, hidden: bool, channel: Optional[str]
                    ) -> Tuple[Optional[str], str]:
    """Drive Chromium to lucida.to and return (cf_clearance cookie or None, user agent)."""
    try:
        from playwright.sync_api import sync_playwright, Error as PlaywrightError
    except ImportError:
        sys.exit("Playwright is not installed (run this script again to set it up).")
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
            if not wait_until_cleared(page, timeout):
                sys.exit(f"Cloudflare was not cleared within {timeout}s.")
            cookies = ctx.cookies(LUCIDA)
            cf = next((c["value"] for c in cookies if c["name"] == "cf_clearance"), None)
            ua = read_user_agent(page)
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
                    help="install Playwright's Chromium first (done automatically on first setup)")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="don't ask before creating the private environment")
    args = ap.parse_args(argv)

    ensure_playwright(args.yes)
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
