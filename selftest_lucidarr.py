"""Offline self-tests for the fork-only code: lucidarr, the clearance web page, the
standalone token script and the search hooks. No browser, no network.

    python selftest.py && python selftest_lucidarr.py

(selftest.py is upstream's own and stays untouched so merges are clean.)
"""

import asyncio as _aio
import importlib.util as _ilu
import os as _os0

from lucidadl import cli as _cli
from lucidadl import lucidarr_cli as _lc
from lucidadl import lucidarr_ext as _ext
from lucidadl import matching
from lucidadl.downloader import _query_variants as _qv

fails = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# ellipsis / curly-quote titles get simplified search variants (after the originals)
_ev = _qv("Theory of a Deadman - The Truth Is\u2026")
check("search: ellipsis title keeps the original query first",
      _ev[0] == "Theory of a Deadman - The Truth Is\u2026")
check("search: ellipsis title also tries it without the ellipsis",
      "Theory of a Deadman - The Truth Is" in _ev and "The Truth Is" in _ev
      and "Theory of a Deadman The Truth Is" in _ev)
check("search: ASCII '...' and curly quotes are simplified too",
      "Artist - Don't Stop" in _qv("Artist - Don\u2019t Stop")
      and "Artist - Wait" in _qv("Artist - Wait..."))
check("search: ordinary titles get no extra variants",
      _qv("Daft Punk - Discovery") == ["Daft Punk - Discovery", "Discovery",
                                       "Daft Punk Discovery", "Discovery Daft Punk"])
check("matching: an ellipsis title matches its '...' / bare form",
      matching.pick_best("Theory of a Deadman - The Truth Is\u2026", [
          {"title": "The Truth Is...", "artist": "Theory of a Deadman", "url": "u1"},
          {"title": "Gasoline", "artist": "Theory of a Deadman", "url": "u2"}],
          require_artist=True, min_score=5.5, min_margin=0.25) == "u1")

# album title agreement: a different album by the same artist must not pass
_ta = _ext.title_agrees
check("album title: 'Christmas With Elvis Presley' rejects 'Elvis Presley Christmas Duets'",
      not _ta("Elvis Presley - Christmas With Elvis Presley", {"title": "Elvis Presley Christmas Duets"}))
check("album title: edition labels are ignored",
      _ta("Theory of a Deadman - Scars & Souvenirs", {"title": "Scars & Souvenirs (Special Edition)"})
      and _ta("Daft Punk - Discovery", {"title": "Discovery (Deluxe Edition)"})
      and _ta("A - Abbey Road", {"title": "Abbey Road (2019 Remastered)"}))
check("album title: anniversary ordinals are edition labels (Dr. Feelgood 35th Anniversary)",
      _ta("M\u00f6tley Cr\u00fce - Dr. Feelgood", {"title": "Dr. Feelgood (35th Anniversary)"})
      and _ta("A - Thriller", {"title": "Thriller (25th Anniversary Edition)"})
      and _ta("A - Abbey Road", {"title": "Abbey Road (50th Anniversary Super Deluxe)"})
      and not _ta("A - Thriller", {"title": "Thriller 2"})
      and not _ta("A - Dr. Feelgood", {"title": "Dr. Feelgood Live in 1989"}))
check("album title: exact and case/punctuation variants pass",
      _ta("Nickelback - Dark Horse", {"title": "Dark Horse"})
      and _ta("Tom Cardy - The Dancefloor at the End of the Universe",
              {"title": "The Dancefloor At The End Of The Universe"})
      and _ta("Mac DeMarco - One Wayne G", {"title": "One Wayne G"}))
check("album title: unrelated or much longer titles fail",
      not _ta("A - Conquest", {"title": "Greatest Hits"})
      and not _ta("A - Live at Wembley", {"title": "Live at Wembley Stadium 1986 Concert"}))
import asyncio as _aio3
from lucidadl.downloader import _resolve_url as _ru
class _SearchStub:
    def __init__(self, items): self.items = items
    async def search(self, q, svc): return {"albums": self.items, "tracks": []}
_stub = _SearchStub([{"title": "Elvis Presley Christmas Duets", "artist": "Elvis Presley", "url": "https://x/duets"}])
check("resolve: a different album by the same artist is not downloaded",
      _aio3.run(_ru(_stub, "Elvis Presley - Christmas With Elvis Presley", "qobuz", "album",
                    lambda *a, **k: None, False, True)) is None)
_stub = _SearchStub([{"title": "Dark Horse", "artist": "Nickelback", "url": "https://x/dh"}])
check("resolve: the right album still resolves",
      _aio3.run(_ru(_stub, "Nickelback - Dark Horse", "qobuz", "album",
                    lambda *a, **k: None, False, True)) == "https://x/dh")

# --- Lidarr / Soularr-style integration ---
import json as _json
import os as _os2
import tempfile as _tmp2
import httpx as _httpx
from lucidadl import lidarr as _ld

check("lidarr: album query", _ld.album_query(
    {"title": "Discovery", "artist": {"artistName": "Daft Punk"}}) == "Daft Punk - Discovery")
check("lidarr: album query needs artist", _ld.album_query({"title": "X"}) == "")
check("lidarr: map_path identity", _ld.map_path("/a/b", "/a", None) == "/a/b")
check("lidarr: map_path remaps", _ld.map_path("/dl/x/y", "/dl", "/data/dl") == "/data/dl/x/y")
check("lidarr: map_path root", _ld.map_path("/dl", "/dl", "/data/dl") == "/data/dl")
with _tmp2.TemporaryDirectory() as _d:
    _st = _ld.AttemptState(_os2.path.join(_d, "s.json"))
    check("lidarr: new album is tried", _st.should_try(1, 24))
    _st.record(1, "q", "no-download", now=1000.0)
    check("lidarr: cooldown blocks", not _st.should_try(1, 24, now=1000.0 + 3600))
    check("lidarr: cooldown expires", _st.should_try(1, 24, now=1000.0 + 25 * 3600))
    check("lidarr: state persists",
          not _ld.AttemptState(_os2.path.join(_d, "s.json")).should_try(
              1, 24, now=1000.0 + 3600))
    _stage = _os2.path.join(_d, "stage", "Artists", "A", "Alb")
    _os2.makedirs(_stage)
    open(_os2.path.join(_stage, "01.flac"), "w").close()
    check("lidarr: audio_dirs finds album", _ld.audio_dirs(_os2.path.join(_d, "stage")) == [_stage])
    _ld.prune_empty(_os2.path.join(_d, "stage"))
    check("lidarr: prune keeps audio", _os2.path.isdir(_stage))
    _os2.remove(_os2.path.join(_stage, "01.flac"))
    _ld.prune_empty(_os2.path.join(_d, "stage"))
    check("lidarr: prune removes empty tree", not _os2.path.exists(_os2.path.join(_d, "stage")))
    # consolidate: nested files (+ art, + a name clash) end up in one release-named folder
    _st3 = _os2.path.join(_d, "st3")
    for _sub in ("Artists/A/B", "Artists/A/C"):
        _os2.makedirs(_os2.path.join(_st3, _sub))
    open(_os2.path.join(_st3, "Artists/A/B/01.flac"), "w").close()
    open(_os2.path.join(_st3, "Artists/A/B/cover.jpg"), "w").close()
    open(_os2.path.join(_st3, "Artists/A/C/01.flac"), "w").close()
    _tgt = _ld.consolidate(_st3, "A - Alb")
    check("lidarr: consolidate gathers files into 'Artist - Album'",
          _os2.path.basename(_tgt) == "A - Alb"
          and sorted(_os2.listdir(_tgt)) == ["01 (1).flac", "01.flac", "cover.jpg"]
          and not _os2.path.exists(_os2.path.join(_st3, "Artists")))
    check("lidarr: consolidate is idempotent", _ld.consolidate(_st3, "A - Alb") == _tgt
          and len(_os2.listdir(_tgt)) == 3)
    for _f in ("01.flac", "01 (1).flac"):
        _os2.remove(_os2.path.join(_tgt, _f))
    _ld.prune_empty(_st3)
    check("lidarr: prune clears leftover art once audio is gone", not _os2.path.exists(_st3))


def _fake_lidarr(request):
    if request.url.path.endswith("/wanted/missing"):
        page = int(request.url.params["page"])
        rec = [{"id": page, "title": f"T{page}", "artist": {"artistName": "A"}}]
        return _httpx.Response(200, json={"records": rec, "totalRecords": 2})
    if request.url.path.endswith("/command") and request.method == "POST":
        body = _json.loads(request.content)
        assert body["name"] == "DownloadedAlbumsScan" and body["path"] == "/x"
        return _httpx.Response(201, json={"id": 7, "status": "queued"})
    if request.url.path.endswith("/command/7"):
        return _httpx.Response(200, json={"id": 7, "status": "completed"})
    return _httpx.Response(404)


async def _lidarr_flow():
    c = _ld.LidarrClient("http://lidarr", "key")
    c.http._transport = _httpx.MockTransport(_fake_lidarr)
    try:
        albums = await c.wanted()
        status = await c.import_folder("/x", poll=0.01)
        return len(albums), status
    finally:
        await c.aclose()


check("lidarr: paged wanted + import scan", _aio.run(_lidarr_flow()) == (2, "completed"))

# Soularr-style config.ini
import logging as _lg
with _tmp2.TemporaryDirectory() as _d:
    _cfgp = _os2.path.join(_d, "config.ini")
    open(_cfgp, "w").write(
        "[Lidarr]\napi_key = k\nhost_url = http://l:8686\ndownload_dir = /remote\n"
        "disable_sync = True\n[Lucida]\nservice = amazon\njobs = 5\n"
        "[Search Settings]\nsearch_source = cutoff_unmet\nsearch_type = first_page\n"
        "number_of_albums_to_grab = 4\ntitle_blacklist = Live,Remix\n"
        "remove_wanted_on_failure = True\n"
        "[Logging]\nformat = %(message)s\n")
    _s = _ld.resolve(_ld.load_config(_cfgp), {})
    check("config: sections map to settings",
          (_s.url, _s.api_key, _s.remote_dir, _s.service, _s.jobs, _s.limit) ==
          ("http://l:8686", "k", "/remote", "amazon", 5, 4))
    check("config: flags and enums", _s.disable_sync and _s.cutoff and _s.remove_on_failure
          and _s.search_type == "first_page")
    check("config: literal % in log format kept", _s.log_format == "%(message)s")
    check("config: blacklist lowercased", _s.blacklist == ["live", "remix"])
    _o = _ld.resolve(_ld.load_config(_cfgp), {"service": "qobuz", "limit": 9, "hidden": True})
    check("config: CLI override beats file",
          (_o.service, _o.limit, _o.hidden, _o.jobs) == ("qobuz", 9, True, 5))
    _dflt = _ld.resolve(_ld.load_config(None), {})
    check("config: defaults match Soularr style",
          (_dflt.search_type, _dflt.limit, _dflt.retry_after, _dflt.log_level) ==
          ("incrementing_page", 10, 24.0, "INFO"))
    try:
        _ld.resolve(_ld.load_config(None), {"search_type": "bogus"})
        _bad = False
    except _ld.LidarrError:
        _bad = True
    check("config: invalid search_type rejected", _bad)
    check("config: find_config explicit", _ld.find_config(_cfgp) == _cfgp)
    check("blacklist matches title", _ld.blacklisted({"title": "Live at X"}, ["live"])
          and not _ld.blacklisted({"title": "Studio"}, ["live"]))
    _st2 = _ld.AttemptState(_os2.path.join(_d, "p.json"))
    check("incrementing page starts at 1 and wraps",
          _st2.next_page(3) == 1 and (_st2.set_page(3) or _st2.next_page(3)) == 3
          and (_st2.set_page(9) or _st2.next_page(3)) == 1)

# --- lucidarr cycle behaviour (mocked Lidarr + downloader) ---
import logging as _lg2
from types import SimpleNamespace as _NS
from unittest.mock import patch as _p2

_RealState = _ld.AttemptState

class _FakeLidarr:
    instances = []
    def __init__(self, url, key):
        self.unmonitored, self.imports = [], []
        _FakeLidarr.instances.append(self)
    async def check(self): return "3.1"
    async def wanted_page(self, cutoff, page, size):
        return {"records": _FakeLidarr.albums, "totalRecords": len(_FakeLidarr.albums)}
    async def wanted(self, cutoff=False): return _FakeLidarr.albums
    async def import_folder(self, path, wait=300): 
        self.imports.append(path)
        for f in _FakeLidarr.import_effect: f(path)
        return "completed"
    async def manual_import(self, path, artist_id, album_id, wait=300, poll=3, replace=False):
        status = await self.import_folder(path, wait)
        return status, 1, 1, []
    has_files = True
    sibling = None
    async def sibling_with_files(self, album): return type(self).sibling
    async def album_has_files(self, aid, retries=3, delay=2.0): return type(self).has_files
    async def unmonitor(self, aid): self.unmonitored.append(aid)
    async def aclose(self): pass

def _cycle(albums, run_results, **over):
    """Run one cycle; run_results = list of (ok, fail) per _run call, 'files' decides audio."""
    with _tmp2.TemporaryDirectory() as d:
        cfg = _ld.resolve(_ld.load_config(None), {"limit": 10, "search_type": "first_page",
                                                  "retry_after": 24, **over})
        cfg.download_dir = d
        _FakeLidarr.albums = albums
        _FakeLidarr.import_effect = [lambda path: [_os2.remove(_os2.path.join(r, f))
                                      for r, _, fs in _os2.walk(path) for f in fs]]
        calls = []
        async def fake_run(items, kind, svc, cc, ds, out, *a, **k):
            ok, fail = run_results[len(calls)] if len(calls) < len(run_results) else (0, 1)
            calls.append(items[0])
            if ok:
                _os2.makedirs(out + "/Artists/A/B", exist_ok=True)
                open(out + "/Artists/A/B/01.flac", "w").close()
            return {"ok": ok, "skip": 0, "fail": fail}, []
        _FakeLidarr.instances.clear()
        with _p2.object(_ld, "LidarrClient", _FakeLidarr), \
             _p2.object(_cli, "_run", fake_run), \
             _p2.object(_cli, "load_clearance", lambda: (None, "ua")), \
             _p2.object(_ld, "AttemptState", lambda: _RealState(d + "/st.json")), \
             _p2.object(_ld, "FAILURE_LIST_PATH", d + "/fail.txt"):
            stats = _aio.run(_lc._lucidarr_cycle(cfg))
            st = _RealState(d + "/st.json")
        return stats, _FakeLidarr.instances[0], calls, st, d

_alb = lambda i: {"id": i, "title": f"T{i}", "artist": {"artistName": "A"}}
_stats, _fl, _calls, _st, _ = _cycle([_alb(1), _alb(2)], [(3, 0), (3, 0)])
check("cycle: downloads then imports each album", _stats["imported"] == 2 and len(_fl.imports) == 2)
check("cycle: Lidarr scans one folder named like the release ('Artist - Album')",
      [_os2.path.basename(p) for p in _fl.imports] == ["A - T1", "A - T2"])
_stats, _fl, _calls, _st, _ = _cycle([_alb(i) for i in range(1, 6)], [], remove_on_failure=True)
check("cycle: outage aborts after 3 failures, records nothing, unmonitors nothing",
      len(_calls) == 3 and not _st.data and not _fl.unmonitored)
_stats, _fl, _calls, _st, _ = _cycle([_alb(1), _alb(2)], [(0, 1), (3, 0)], remove_on_failure=True)
check("cycle: failure before a success is settled and unmonitored once lucida proves OK",
      _fl.unmonitored == [1] and "1" in _st.data and _stats["imported"] == 1)
_FakeLidarr.has_files = False
_stats, _fl, _calls, _st, _ = _cycle([_alb(1)], [(3, 0)])
_FakeLidarr.has_files = True
check("cycle: files that land on a different album are not reported as imported",
      _stats["imported"] == 0 and _stats["failed"] == 1
      and _st.data["1"]["result"] == "import-elsewhere")
_FakeLidarr.has_files, _FakeLidarr.sibling = False, 77
_stats, _fl, _calls, _st, _ = _cycle([_alb(1)], [(3, 0)])
_FakeLidarr.has_files, _FakeLidarr.sibling = True, None
check("cycle: files on a same-title sibling edition count as imported and are never refetched",
      _stats["imported"] == 1 and _stats["failed"] == 0
      and _st.data["1"]["result"] == "sibling:77" and not _st.should_try(1, 0))
_stats, _fl, _calls, _st, _ = _cycle([_alb(1)], [(2, 1)])
check("cycle: partial album is not imported", not _fl.imports and _st.data["1"]["result"] == "partial")
# an interrupted earlier download (audio staged, no completion marker) is discarded, then fetched fresh
def _cycle_pre(prefill_complete):
    with _tmp2.TemporaryDirectory() as d:
        cfg = _ld.resolve(_ld.load_config(None), {"limit": 10, "search_type": "first_page",
                                                  "retry_after": 24})
        cfg.download_dir = d
        _FakeLidarr.albums = [_alb(1)]
        _FakeLidarr.import_effect = [lambda path: [_os2.remove(_os2.path.join(r, f))
                                      for r, _, fs in _os2.walk(path) for f in fs]]
        stage = _ld.staging_dir(d, _alb(1))
        _os2.makedirs(stage + "/Artists/A/B")
        open(stage + "/Artists/A/B/old.flac", "w").close()
        if prefill_complete:
            _ld.mark_complete(stage)
        calls = []
        async def fake_run(items, kind, svc, cc, ds, out, *a, **k):
            calls.append(1)
            _os2.makedirs(out + "/Artists/A/B", exist_ok=True)
            open(out + "/Artists/A/B/new.flac", "w").close()
            return {"ok": 1, "skip": 0, "fail": 0}, []
        _FakeLidarr.instances.clear()
        with _p2.object(_ld, "LidarrClient", _FakeLidarr), _p2.object(_cli, "_run", fake_run), \
             _p2.object(_cli, "load_clearance", lambda: (None, "ua")), \
             _p2.object(_ld, "AttemptState", lambda: _RealState(d + "/st.json")):
            _aio.run(_lc._lucidarr_cycle(cfg))
        return len(calls), len(_FakeLidarr.instances[0].imports)
check("cycle: incomplete staged download is discarded and re-downloaded", _cycle_pre(False) == (1, 1))
check("cycle: complete staged download is re-scanned without downloading", _cycle_pre(True) == (0, 1))
_stats, _fl, _calls, _st, _ = _cycle([_alb(1)], [(3, 0)], disable_sync=True)
check("cycle: disable_sync records 'staged', no import",
      not _fl.imports and _st.data["1"]["result"] == "staged")

class _Boom(_FakeLidarr):
    async def import_folder(self, path, wait=300):
        raise _ld.LidarrError("down")
    async def manual_import(self, *a, **k):
        raise _ld.LidarrError("down")
with _p2.object(_ld, "LidarrClient", _Boom), _tmp2.TemporaryDirectory() as _d3:
    _FakeLidarr.albums = [_alb(1), _alb(2)]
    _cfg = _ld.resolve(_ld.load_config(None), {"search_type": "first_page", "retry_after": 24})
    _cfg.download_dir = _d3
    _n = []
    async def _fr(items, kind, svc, cc, ds, out, *a, **k):
        _n.append(1); _os2.makedirs(out + "/x", exist_ok=True)
        open(out + "/x/1.flac", "w").close()
        return {"ok": 1, "skip": 0, "fail": 0}, []
    with _p2.object(_cli, "_run", _fr), _p2.object(_cli, "load_clearance", lambda: (None, "u")), \
         _p2.object(_ld, "AttemptState", lambda: _RealState(_d3 + "/s.json")):
        _bs = _aio.run(_lc._lucidarr_cycle(_cfg))
    check("cycle: Lidarr import error is recorded and stops the cycle",
          len(_n) == 1 and _bs["failed"] == 1
          and _RealState(_d3 + "/s.json").data["1"]["result"] == "import-error")
for _bad in ({"limit": 0}, {"jobs": 0}):
    try:
        _ld.resolve(_ld.load_config(None), _bad); _ok = False
    except _ld.LidarrError:
        _ok = True
    check(f"config: rejects {_bad}", _ok)
check("find_config: missing explicit path is not silently replaced",
      _ld.find_config("/definitely/not/here.ini") is None)

# --- clearance web page ---
import threading as _th
from lucidadl import webui as _web, session as _sess

check("web: pasted JSON parsed", _web.parse_submission('{"cf_clearance":"abc","ua":"UA/1"}')
      == ("abc", "UA/1"))
check("web: cookie may be absent", _web.parse_submission("", "", "UA/1") == (None, "UA/1"))
_rej = []
for _args in (("not json",), ('{"cf_clearance":"a"}',), ("", "bad\r\nX: 1", "UA"),
              ("", "ok", "UA\nInjected: 1"), ("[1]",)):
    try:
        _web.parse_submission(*_args); _rej.append(False)
    except _web.BadSubmission:
        _rej.append(True)
check("web: bad / injecting submissions rejected", all(_rej))
try:
    _web.make_server("127.0.0.1", 0, ""); _nopw = False
except ValueError:
    _nopw = True
check("web: refuses to start without a password", _nopw)

with _tmp2.TemporaryDirectory() as _wd, _p2.object(
        _sess, "CLEARANCE_PATH", _os2.path.join(_wd, "clearance.json")), \
        _p2.object(_web.time, "sleep", lambda s: None):
    _srv = _web.make_server("127.0.0.1", 0, "s3cret")
    _port = _srv.server_address[1]
    _th.Thread(target=_srv.serve_forever, daemon=True).start()
    _u = f"http://127.0.0.1:{_port}"
    try:
        check("web: page loads", _httpx.get(_u + "/").status_code == 200)
        _lg = _httpx.get(_u + "/logo.svg")
        check("web: logo served as SVG", _lg.status_code == 200
              and _lg.headers["content-type"] == "image/svg+xml" and b"<svg" in _lg.content
              and b"<script" not in _lg.content)
        check("web: wrong password refused, nothing saved",
              _httpx.post(_u + "/upload", data={"password": "no", "pasted":
                          '{"cf_clearance":"x","ua":"U"}'}).status_code == 403
              and not _os2.path.exists(_sess.CLEARANCE_PATH))
        _r = _httpx.post(_u + "/upload", data={"password": "s3cret", "pasted":
                         '{"cf_clearance":"cookie1","ua":"UA/9"}'})
        check("web: form upload saved", _r.status_code == 200
              and _sess.load_clearance() == ("cookie1", "UA/9"))
        check("web: page never reveals the cookie", "cookie1" not in _httpx.get(_u + "/").text)
        check("web: api rejects missing/incorrect bearer",
              _httpx.post(_u + "/api/clearance", json={"ua": "U"}).status_code == 403)
        _r = _httpx.post(_u + "/api/clearance", json={"cf_clearance": "c2", "ua": "UA/10"},
                         headers={"Authorization": "Bearer s3cret"})
        check("web: api upload saved", _r.status_code == 200
              and _sess.load_clearance() == ("c2", "UA/10"))
        check("web: oversized body rejected", _httpx.post(
              _u + "/api/clearance", content=b"x" * 20000,
              headers={"Authorization": "Bearer s3cret"}).status_code == 400)
    finally:
        _srv.shutdown()
check("cli: web + push-clearance registered",
      "web" in _cli.cli.commands and "push-clearance" in _cli.cli.commands)

# --- Manual Import API ---
_posted = []
def _fake_manual(request):
    if request.url.path.endswith("/manualimport"):
        q = dict(request.url.params)
        assert q["folder"] == "/r/A - T" and q["artistId"] == "5" and q["replaceExistingFiles"] == "false"
        return _httpx.Response(200, json=[
            {"name": "01", "path": "/r/A - T/01.flac", "artist": {"id": 5}, "album": {"id": 9},
             "albumReleaseId": 77, "tracks": [{"id": 101}], "quality": {"q": 1}, "rejections": []},
            {"name": "02", "path": "/r/A - T/02.flac", "artist": {"id": 5}, "album": {"id": 9},
             "albumReleaseId": 77, "tracks": [{"id": 102}], "quality": {"q": 1},
             "rejections": [{"reason": "Not an upgrade"}]},
            {"name": "03", "path": "/r/A - T/03.flac", "artist": {}, "album": {}, "tracks": [],
             "rejections": [{"reason": "Unknown Artist"}]},
            {"name": "04", "path": "/r/A - T/04.flac", "artist": {"id": 5}, "album": {"id": 10},
             "albumReleaseId": 1, "tracks": [{"id": 1}], "rejections": []}])
    if request.url.path.endswith("/command") and request.method == "POST":
        _posted.append(_json.loads(request.content))
        return _httpx.Response(201, json={"id": 3, "status": "queued"})
    if request.url.path.endswith("/command/3"):
        return _httpx.Response(200, json={"status": "completed"})
    return _httpx.Response(404)

async def _manual_flow(items_empty=False):
    c = _ld.LidarrClient("http://lidarr", "key")
    c.http._transport = _httpx.MockTransport(
        (lambda r: _httpx.Response(200, json=[]) if r.url.path.endswith("/manualimport")
         else _fake_manual(r)) if items_empty else _fake_manual)
    try:
        return await c.manual_import("/r/A - T", 5, 9, poll=0.01)
    finally:
        await c.aclose()

_mi = _aio.run(_manual_flow())
check("release folder name follows Soularr's 'Artist - Title (Year)'",
      _ld.release_folder_name({"title": "Disco/very", "artist": {"artistName": "Daft Punk"},
                               "releaseDate": "2001-03-12T00:00:00Z"}) == "Daft Punk - Disco_very (2001)"
      and _ld.release_folder_name(_alb(1)) == "A - T1")
with _tmp2.TemporaryDirectory() as _td:
    from mutagen.easyid3 import EasyID3 as _E3
    _mp3 = _os2.path.join(_td, "01.mp3"); open(_mp3, "wb").close()
    _bad = _os2.path.join(_td, "02.flac"); open(_bad, "wb").close()   # not real audio
    check("tag_files: sets albumartist/album, skips unreadable files",
          _ld.tag_files(_td, "Tom Cardy", "Dancefloor") == 1
          and _E3(_mp3)["albumartist"] == ["Tom Cardy"] and _E3(_mp3)["album"] == ["Dancefloor"])
check("manual import: imports only files matched to the wanted album",
      _mi[0] == "completed" and _mi[1] == 2 and _mi[2] == 4)
check("manual import: payload carries ids, quality and move mode",
      _posted[-1]["name"] == "ManualImport" and _posted[-1]["importMode"] == "move"
      and [f["trackIds"] for f in _posted[-1]["files"]] == [[101], [102]]
      and _posted[-1]["files"][0]["albumReleaseId"] == 77
      and _posted[-1]["files"][0]["artistId"] == 5 and _posted[-1]["files"][0]["albumId"] == 9)
check("manual import: rejection reasons are surfaced",
      any("Unknown Artist" in r for r in _mi[3]) and any("Not an upgrade" in r for r in _mi[3])
      and any("matched album id 10" in r for r in _mi[3]))
_before = len(_posted)
_mi2 = _aio.run(_manual_flow(items_empty=True))
check("manual import: nothing matched -> 'unmatched', no command posted",
      _mi2[0] == "unmatched" and len(_posted) == _before)
check("config: import_method defaults to auto",
      _ld.resolve(_ld.load_config(None), {}).import_method == "auto")
try:
    _ld.resolve(_ld.load_config(None), {"import_method": "nope"}); _imok = False
except _ld.LidarrError:
    _imok = True
check("config: invalid import_method rejected", _imok)

# album_has_files: counts, retry, and "cannot verify -> trust"
_cnt = {"n": 0}
def _fake_stats(request):
    if request.url.path.endswith("/album"):
        _cnt["n"] += 1
        if request.url.params["albumIds"] == "9":
            return _httpx.Response(200, json=[{"statistics": {"trackFileCount": 0 if _cnt["n"] < 2 else 4}}])
        if request.url.params["albumIds"] == "8":
            return _httpx.Response(200, json=[{"statistics": {"trackFileCount": 0}}])
        return _httpx.Response(200, json=[{"title": "no statistics"}])
    return _httpx.Response(404)
async def _hf(aid):
    c = _ld.LidarrClient("http://lidarr", "key")
    c.http._transport = _httpx.MockTransport(_fake_stats)
    try:
        return await c.album_has_files(aid, retries=3, delay=0.01)
    finally:
        await c.aclose()
check("album_has_files: waits for Lidarr's counts to update", _aio.run(_hf(9)) is True)
check("album_has_files: still none after retries -> False", _aio.run(_hf(8)) is False)
check("album_has_files: no statistics -> trust the import", _aio.run(_hf(7)) is True)

# sibling_with_files: same title + same artist + has files, ignoring case/accents-free punctuation
def _fake_sib(request):
    if request.url.path.endswith("/album") and request.url.params.get("artistId") == "4":
        return _httpx.Response(200, json=[
            {"id": 1, "title": "\u00c9ternelle", "statistics": {"trackFileCount": 0}},
            {"id": 2, "title": "\u00c9TERNELLE!", "statistics": {"trackFileCount": 38}},
            {"id": 3, "title": "Other", "statistics": {"trackFileCount": 9}}])
    return _httpx.Response(404)
async def _sib(album):
    c = _ld.LidarrClient("http://lidarr", "key")
    c.http._transport = _httpx.MockTransport(_fake_sib)
    try:
        return await c.sibling_with_files(album)
    finally:
        await c.aclose()
check("sibling_with_files: finds the same-title twin that has files",
      _aio.run(_sib({"id": 1, "title": "\u00c9ternelle", "artistId": 4})) == 2)
check("sibling_with_files: other titles and the wanted record itself are ignored",
      _aio.run(_sib({"id": 2, "title": "\u00c9ternelle", "artistId": 4})) is None
      and _aio.run(_sib({"id": 1, "title": "Nope", "artistId": 4})) is None)
check("cli: lucidarr command + soularr alias registered",
      "lucidarr" in _cli.cli.commands and "soularr" in _cli.cli.commands)

# --- standalone token script (scripts/lucida_token.py) ---
_spec = _ilu.spec_from_file_location(
    "lucida_token", _os0.path.join(_os0.path.dirname(_os0.path.abspath(__file__)),
                                   "scripts", "lucida_token.py"))
_tok = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_tok)
check("token script: imports without playwright/lucidadl side effects",
      "playwright" not in _tok.__dict__ and "lucidadl" not in " ".join(_tok.__dict__))
check("token script: recognises Cloudflare's interstitial vs the real page",
      _tok.is_challenge("Just a moment...", "") and _tok.is_challenge("x", '<div id="challenge-form">')
      and not _tok.is_challenge("lucida", "<html>music</html>"))
with _tmp2.TemporaryDirectory() as _td:
    _out = _os2.path.join(_td, "sub", "clearance.json")
    _tok.save(_out, _tok.build_payload("cookie", "UA/1", now=5.0))
    check("token script: saves lucidadl-format JSON, owner-only",
          _json.load(open(_out)) == {"cf_clearance": "cookie", "ua": "UA/1", "ts": 5.0}
          and (_os2.stat(_out).st_mode & 0o777) == 0o600)
    # lucidadl itself must be able to read what the script wrote
    with _p2.object(_sess, "CLEARANCE_PATH", _out):
        check("token script: output is readable by lucidadl's loader",
              _sess.load_clearance() == ("cookie", "UA/1"))
    # push to a real (local) lucidarr web page
    with _p2.object(_sess, "CLEARANCE_PATH", _os2.path.join(_td, "server.json")), \
            _p2.object(_web.time, "sleep", lambda s: None):
        _srv2 = _web.make_server("127.0.0.1", 0, "pw")
        _th.Thread(target=_srv2.serve_forever, daemon=True).start()
        _url = f"http://127.0.0.1:{_srv2.server_address[1]}"
        try:
            _tok.push(_url, "pw", _tok.build_payload("c9", "UA/9"))
            check("token script: push uploads to the web page",
                  _sess.load_clearance() == ("c9", "UA/9"))
            try:
                _tok.push(_url, "wrong", _tok.build_payload("c0", "UA/0")); _msg = ""
            except RuntimeError as _e:
                _msg = str(_e)
            check("token script: wrong password gives a clear error, nothing saved",
                  "403" in _msg and "password" in _msg and _sess.load_clearance() == ("c9", "UA/9"))
        finally:
            _srv2.shutdown()
    try:
        _tok.push("http://127.0.0.1:1", "x", _tok.build_payload("c", "u"), timeout=2); _unreach = ""
    except RuntimeError as _e:
        _unreach = str(_e)
    check("token script: unreachable server gives a clear error", "could not reach" in _unreach)

# token script: self-setup logic (no network, no installs)
class _NoTty:
    def isatty(self): return False
with _p2.object(_tok, "have_playwright", lambda: False), _p2.object(_tok, "venv_ready", lambda: False), \
        _p2.object(_tok.sys, "stdin", _NoTty()), _p2.dict(_os2.environ, {}, clear=False):
    _os2.environ.pop("LUCIDA_TOKEN_REEXEC", None)
    try:
        _tok.ensure_playwright(False); _m1 = ""
    except SystemExit as _e:
        _m1 = str(_e)
check("token script: no Playwright + no terminal -> asks for --yes, installs nothing",
      "--yes" in _m1 and "private environment" in _m1)
with _p2.object(_tok, "have_playwright", lambda: False), _p2.dict(_os2.environ, {"LUCIDA_TOKEN_REEXEC": "1"}):
    try:
        _tok.ensure_playwright(True); _m2 = ""
    except SystemExit as _e:
        _m2 = str(_e)
check("token script: never re-execs twice (no setup loop)", "still not importable" in _m2)
with _p2.object(_tok, "have_playwright", lambda: True):
    check("token script: Playwright present -> proceeds untouched", _tok.ensure_playwright(False) is None)
check("token script: private venv lives under its own home dir",
      _tok.venv_python().startswith(_tok.VENV_DIR) and _tok.VENV_DIR.startswith(_tok.HOME_DIR))

# token script: robustness against Cloudflare's mid-navigation errors
class _FakePage:
    """title()/content() raise while 'navigating', then show the challenge, then lucida."""
    def __init__(self, script, url="https://lucida.to/"):
        self.script, self.i, self.url = list(script), 0, url
        self.ua_fail = 0
    def _state(self):
        st = self.script[min(self.i, len(self.script) - 1)]
        return st
    def title(self):
        st = self._state()
        if st == "navigating": raise RuntimeError("Page.content: page is navigating")
        return "Just a moment..." if st == "challenge" else "lucida"
    def content(self): return "<html>x</html>"
    def wait_for_timeout(self, ms): self.i += 1
    def evaluate(self, js):
        if self.ua_fail > 0:
            self.ua_fail -= 1; raise RuntimeError("Execution context was destroyed")
        return "HeadlessChrome/1 Safari"
_pg = _FakePage(["navigating", "challenge", "navigating", "challenge", "ok"])
check("token script: survives 'page is navigating' errors and waits for the real page",
      _tok.wait_until_cleared(_pg, timeout=30) is True and _pg.i >= 4)
check("token script: a mid-navigation error counts as 'not cleared yet'",
      _tok.page_challenged(_FakePage(["navigating"])) is True
      and _tok.page_challenged(_FakePage(["ok"])) is False)
check("token script: stuck on the challenge times out cleanly",
      _tok.wait_until_cleared(_FakePage(["challenge"]), timeout=0.05) is False)
check("token script: cleared title but still on another host is not accepted",
      _tok.wait_until_cleared(_FakePage(["ok"], url="https://challenges.example/"), timeout=0.05) is False)
_pg = _FakePage(["ok"]); _pg.ua_fail = 2
check("token script: user-agent read retries a racing navigation and fixes HeadlessChrome",
      _tok.read_user_agent(_pg) == "Chrome/1 Safari")
_pg = _FakePage(["ok"]); _pg.ua_fail = 99
try:
    _tok.read_user_agent(_pg, tries=2); _uae = ""
except RuntimeError as _e:
    _uae = str(_e)
check("token script: gives up with a clear error if the user agent never reads", "user agent" in _uae)

# token script: fail fast on a bad address, keep the token if the upload fails, --from-file
import argparse as _ap
check("token script: unreachable() reports a refused/absent server",
      bool(_tok.unreachable("http://127.0.0.1:1", timeout=2)))
with _tmp2.TemporaryDirectory() as _td:
    _clr = _os2.path.join(_td, "clearance.json")
    open(_clr, "w").write(_json.dumps({"cf_clearance": "cX", "ua": "UA/7", "ts": 3}))
    with _p2.object(_sess, "CLEARANCE_PATH", _os2.path.join(_td, "server.json")), \
            _p2.object(_web.time, "sleep", lambda s: None):
        _srv3 = _web.make_server("127.0.0.1", 0, "pw")
        _th.Thread(target=_srv3.serve_forever, daemon=True).start()
        _u3 = f"http://127.0.0.1:{_srv3.server_address[1]}"
        try:
            check("token script: unreachable() is None for a live server", _tok.unreachable(_u3) is None)
            _a = _ap.Namespace(from_file=_clr, out=None, push=_u3, password="pw", profile="x",
                               timeout=1, hidden=True, channel=None)
            with _p2.object(_tok, "fetch_clearance", lambda *a, **k: (_ for _ in ()).throw(AssertionError("browser!"))):
                _rc = _tok.run_once(_a)
            check("token script: --from-file uploads without opening a browser",
                  _rc == 0 and _sess.load_clearance() == ("cX", "UA/7"))
        finally:
            _srv3.shutdown()
    # a failed upload must keep the freshly fetched token on disk
    with _p2.object(_tok, "HOME_DIR", _td), _p2.object(_tok, "fetch_clearance", lambda *a, **k: ("cN", "UA/8")):
        _a = _ap.Namespace(from_file=None, out=None, push="http://127.0.0.1:1", password="pw",
                           profile="x", timeout=1, hidden=True, channel=None)
        _rc = _tok.run_once(_a)
        _kept = _os2.path.join(_td, "last-clearance.json")
        check("token script: failed upload keeps the token and exits non-zero",
              _rc == 1 and _os2.path.exists(_kept) and _json.load(open(_kept))["cf_clearance"] == "cN"
              and (_os2.stat(_kept).st_mode & 0o777) == 0o600)
    try:
        open(_os2.path.join(_td, "bad.json"), "w").write("{}"); _tok.load_file(_os2.path.join(_td, "bad.json")); _bad2 = False
    except ValueError:
        _bad2 = True
    check("token script: --from-file rejects a file that is not a clearance", _bad2)
_a = _ap.Namespace(from_file=None, out=None, push="http://127.0.0.1:1", password="pw", profile="x",
                   timeout=1, hidden=True, channel=None, install=False, yes=True, every=0)
with _p2.object(_tok.sys, "argv", ["t", "--push", "http://127.0.0.1:1", "--password", "pw", "--yes"]), \
        _p2.object(_tok, "fetch_clearance", lambda *a, **k: (_ for _ in ()).throw(AssertionError("browser opened before reachability check"))):
    check("token script: a bad --push address fails before any browser starts", _tok.main() == 1)

print()
if fails:
    print(f"{len(fails)} FAILURE(S): {fails}")
    raise SystemExit(1)
print("ALL LUCIDARR OFFLINE TESTS PASSED")
