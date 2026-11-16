"""Soularr-style Lidarr integration.

Soularr turns Lidarr's *wanted* list into downloads from another source and then asks
Lidarr to import the result. This module does the same with lucida.to as the source:

1. read monitored missing (or cutoff-unmet) albums from Lidarr's API,
2. download each one as ``"Artist - Album"`` into an isolated staging folder,
3. trigger Lidarr's ``DownloadedAlbumsScan`` on that folder so Lidarr imports it,
4. remember what was tried so failures are not hammered every cycle.

Only the pure helpers and the small HTTP client live here; the download itself is the
existing lucidadl pipeline, driven from ``cli.soularr_cmd``.
"""

from __future__ import annotations

import asyncio
import configparser
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from . import paths, utils

AUDIO_EXTS = (".flac", ".mp3", ".m4a", ".aac", ".opus", ".ogg", ".wav", ".alac",
              ".aiff", ".aif")
STATE_PATH = str(paths.DATA_DIR / "lidarr-state.json")
_DONE_STATES = {"completed", "failed", "aborted", "cancelled", "orphaned"}


class LidarrError(Exception):
    pass


# --- Soularr-style config.ini -------------------------------------------------

DEFAULT_LOG_FORMAT = "[%(levelname)s|%(module)s|L%(lineno)d] %(asctime)s: %(message)s"
DEFAULT_DATEFMT = "%Y-%m-%dT%H:%M:%S%z"
FAILURE_LIST_PATH = str(paths.DATA_DIR / "failure_list.txt")

DEFAULTS: Dict[str, Dict[str, str]] = {
    "Lidarr": {"api_key": "", "host_url": "http://localhost:8686",
               "download_dir": "", "disable_sync": "False"},
    "Lucida": {"download_dir": "", "service": "qobuz", "country": "", "jobs": "3",
               "convert_to": "", "bitrate": "", "hidden": "False",
               "import_timeout": "300"},
    "Search Settings": {"search_source": "missing", "search_type": "incrementing_page",
                        "number_of_albums_to_grab": "10",
                        "remove_wanted_on_failure": "False",
                        "retry_after_hours": "24", "title_blacklist": ""},
    "Logging": {"level": "INFO", "format": DEFAULT_LOG_FORMAT,
                "datefmt": DEFAULT_DATEFMT},
}


def find_config(explicit: Optional[str] = None) -> Optional[str]:
    """--config, $LUCIDARR_CONFIG, ./config.ini, then <app data>/config.ini."""
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    for cand in (os.environ.get("LUCIDARR_CONFIG"),
                 os.path.join(os.getcwd(), "config.ini"),
                 str(paths.DATA_DIR / "config.ini")):
        if cand and os.path.isfile(cand):
            return cand
    return None


def load_config(path: Optional[str] = None) -> configparser.ConfigParser:
    """Defaults overlaid with a Soularr-style config.ini (``%`` is literal in it)."""
    cp = configparser.ConfigParser(interpolation=None)
    cp.read_dict(DEFAULTS)
    if path:
        cp.read(path, encoding="utf-8")
    return cp


def _csv(value: str) -> List[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


@dataclass
class Settings:
    url: str
    api_key: str
    download_dir: str
    remote_dir: str
    disable_sync: bool
    service: str
    country: Optional[str]
    jobs: int
    to_fmt: Optional[str]
    bitrate: Optional[str]
    hidden: bool
    import_timeout: int
    cutoff: bool
    search_type: str
    limit: int
    remove_on_failure: bool
    retry_after: float
    blacklist: List[str]
    interval: int
    log_level: str
    log_format: str
    log_datefmt: str


def resolve(cp: configparser.ConfigParser, o: Dict[str, Any]) -> Settings:
    """Validated settings; a bad value is a LidarrError, never a traceback."""
    try:
        s = _resolve(cp, o)
    except (ValueError, TypeError) as e:
        raise LidarrError(f"Invalid value in config/options: {e}") from e
    if s.limit < 1 or not 1 <= s.jobs <= 100 or s.import_timeout < 1 or s.retry_after < 0:
        raise LidarrError("number_of_albums_to_grab and import_timeout must be >= 1, "
                          "jobs 1-100, retry_after_hours >= 0.")
    return s


def _resolve(cp: configparser.ConfigParser, o: Dict[str, Any]) -> Settings:
    """Precedence: command-line/env override (non-None) > config.ini > default."""
    def pick(key, section, name, conv=str):
        v = o.get(key)
        if v is None:
            v = cp.get(section, name, fallback=DEFAULTS[section][name])
        return conv(v)

    def boolean(v):
        return v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")

    source = pick("source", "Search Settings", "search_source").strip().lower()
    stype = pick("search_type", "Search Settings", "search_type").strip().lower()
    if stype not in ("all", "first_page", "incrementing_page"):
        raise LidarrError(f"search_type must be all, first_page or incrementing_page "
                          f"(got {stype!r}).")
    if source not in ("missing", "cutoff_unmet"):
        raise LidarrError(f"search_source must be missing or cutoff_unmet (got {source!r}).")
    return Settings(
        url=pick("url", "Lidarr", "host_url"),
        api_key=pick("api_key", "Lidarr", "api_key"),
        download_dir=pick("download_dir", "Lucida", "download_dir"),
        remote_dir=pick("remote_dir", "Lidarr", "download_dir"),
        disable_sync=pick("disable_sync", "Lidarr", "disable_sync", boolean),
        service=pick("service", "Lucida", "service"),
        country=pick("country", "Lucida", "country") or None,
        jobs=pick("jobs", "Lucida", "jobs", int),
        to_fmt=pick("to_fmt", "Lucida", "convert_to") or None,
        bitrate=pick("bitrate", "Lucida", "bitrate") or None,
        hidden=pick("hidden", "Lucida", "hidden", boolean),
        import_timeout=pick("import_timeout", "Lucida", "import_timeout", int),
        cutoff=source == "cutoff_unmet",
        search_type=stype,
        limit=pick("limit", "Search Settings", "number_of_albums_to_grab", int),
        remove_on_failure=pick("remove_on_failure", "Search Settings",
                               "remove_wanted_on_failure", boolean),
        retry_after=pick("retry_after", "Search Settings", "retry_after_hours", float),
        blacklist=[w.lower() for w in _csv(pick("blacklist", "Search Settings",
                                                "title_blacklist"))],
        interval=int(o.get("interval") or 0),
        log_level=pick("log_level", "Logging", "level").upper(),
        log_format=pick("log_format", "Logging", "format"),
        log_datefmt=pick("log_datefmt", "Logging", "datefmt"),
    )


def blacklisted(album: Dict[str, Any], words: List[str]) -> bool:
    """Case-insensitive title_blacklist check against the wanted album's title."""
    title = (album.get("title") or "").lower()
    return any(w in title for w in words)


def log_failure(query: str, path: str = FAILURE_LIST_PATH) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{query}\n")


# --- pure helpers -------------------------------------------------------------

def album_query(album: Dict[str, Any]) -> str:
    """``"Artist - Album"`` search line for a Lidarr album record ('' if unusable)."""
    artist = ((album.get("artist") or {}).get("artistName") or "").strip()
    title = (album.get("title") or "").strip()
    return f"{artist} - {title}" if artist and title else ""


def map_path(local: str, local_root: str, remote_root: Optional[str]) -> str:
    """Translate a path under ``local_root`` into the path Lidarr sees (Docker volumes,
    network shares). With no ``remote_root`` the local path is returned unchanged."""
    if not remote_root:
        return local
    rel = os.path.relpath(local, local_root)
    if rel == ".":
        return remote_root
    sep = "\\" if "\\" in remote_root and "/" not in remote_root else "/"
    return remote_root.rstrip("/\\") + sep + rel.replace(os.sep, sep)


def audio_dirs(root: str) -> List[str]:
    """Directories under ``root`` that directly contain audio files."""
    found = []
    for folder, _dirs, files in os.walk(root):
        if any(f.lower().endswith(AUDIO_EXTS) for f in files):
            found.append(folder)
    return sorted(found)


def prune_empty(root: str) -> None:
    """Delete ``root`` if it holds no audio any more (Lidarr moved it), else keep it."""
    if not os.path.isdir(root) or audio_dirs(root):
        return
    for folder, _dirs, _files in os.walk(root, topdown=False):
        try:
            os.rmdir(folder)
        except OSError:
            pass


class AttemptState:
    """Per-album attempt memory so a failing album is retried only after a cooldown."""

    def __init__(self, path: str = STATE_PATH):
        self.path = path
        self.data: Dict[str, Dict[str, Any]] = {}
        try:
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.data = loaded
        except (OSError, ValueError):
            pass

    def should_try(self, album_id: int, retry_after_hours: float,
                   now: Optional[float] = None) -> bool:
        rec = self.data.get(str(album_id))
        if not rec:
            return True
        now = time.time() if now is None else now
        return now - float(rec.get("at", 0)) >= retry_after_hours * 3600

    def record(self, album_id: int, query: str, result: str,
               now: Optional[float] = None) -> None:
        self.data[str(album_id)] = {"query": query, "result": result,
                                    "at": time.time() if now is None else now}
        self.save()

    def next_page(self, total_pages: int) -> int:
        """Soularr's incrementing_page: current page, wrapping at the last one."""
        page = int((self.data.get("_meta") or {}).get("page", 1))
        return page if 1 <= page <= max(1, total_pages) else 1

    def set_page(self, page: int) -> None:
        self.data["_meta"] = {"page": page}
        self.save()

    def forget(self, album_id: int) -> None:
        if self.data.pop(str(album_id), None) is not None:
            self.save()

    def save(self) -> None:
        try:
            tmp = self.path + f".{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass  # a full disk must not crash the loop; worst case an album is retried


# --- Lidarr API client --------------------------------------------------------

class LidarrClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        if not base_url or not api_key:
            raise LidarrError("Lidarr URL and API key are required.")
        self.http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/api/v1",
            headers={"X-Api-Key": api_key}, timeout=timeout)

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _request(self, method: str, url: str, **kw) -> Any:
        try:
            r = await self.http.request(method, url, **kw)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            hint = " (check the API key)" if code in (401, 403) else ""
            raise LidarrError(f"Lidarr {method} {url} -> HTTP {code}{hint}") from e
        except httpx.HTTPError as e:
            raise LidarrError(f"Lidarr unreachable: {e}") from e
        try:
            return r.json()
        except ValueError as e:
            raise LidarrError(f"Lidarr {method} {url} returned non-JSON "
                              f"(check host_url / URL base)") from e

    async def check(self) -> str:
        info = await self._request("GET", "/system/status")
        return str(info.get("version", "?"))

    async def wanted(self, cutoff: bool = False, limit: Optional[int] = None,
                     page_size: int = 100) -> List[Dict[str, Any]]:
        """Monitored albums that are missing (or whose quality is below cutoff)."""
        kind = "cutoff" if cutoff else "missing"
        out: List[Dict[str, Any]] = []
        page = 1
        while True:
            data = await self._request("GET", f"/wanted/{kind}", params={
                "page": page, "pageSize": page_size, "monitored": "true",
                "includeArtist": "true", "sortKey": "albums.releaseDate",
                "sortDirection": "descending"})
            records = data.get("records") or []
            out.extend(records)
            if limit and len(out) >= limit:
                return out[:limit]
            if not records or len(out) >= int(data.get("totalRecords") or 0):
                return out
            page += 1

    async def wanted_page(self, cutoff: bool, page: int, page_size: int
                          ) -> Dict[str, Any]:
        kind = "cutoff" if cutoff else "missing"
        return await self._request("GET", f"/wanted/{kind}", params={
            "page": page, "pageSize": page_size, "monitored": "true",
            "includeArtist": "true", "sortKey": "albums.releaseDate",
            "sortDirection": "descending"})

    async def unmonitor(self, album_id: int) -> None:
        await self._request("PUT", "/album/monitor",
                            json={"albumIds": [album_id], "monitored": False})

    async def import_folder(self, remote_path: str, wait: float = 300.0,
                            poll: float = 3.0) -> str:
        """Run ``DownloadedAlbumsScan`` on a folder; returns the final command status."""
        cmd = await self._request("POST", "/command", json={
            "name": "DownloadedAlbumsScan", "path": remote_path,
            "importMode": "Move"})
        cid = cmd.get("id")
        if cid is None:
            raise LidarrError("Lidarr did not return a command id for the import scan.")
        deadline = time.monotonic() + wait
        status = str(cmd.get("status") or "queued")
        while status.lower() not in _DONE_STATES and time.monotonic() < deadline:
            await asyncio.sleep(poll)
            try:  # a transient poll error must not abandon a scan Lidarr is running
                status = str((await self._request("GET", f"/command/{cid}"))
                             .get("status") or status)
            except LidarrError:
                if time.monotonic() >= deadline:
                    raise
        return status.lower()

    async def album_has_files(self, album_id: int) -> bool:
        data = await self._request("GET", "/album", params={"albumIds": album_id})
        if isinstance(data, list) and data:
            return int((data[0].get("statistics") or {}).get("trackFileCount") or 0) > 0
        return False


def staging_dir(download_dir: str, album: Dict[str, Any]) -> str:
    """Isolated per-album folder so one album's files never mix with another's."""
    return os.path.join(
        download_dir, f"{album.get('id')}-{utils.sanitize(album_query(album))[:80]}")
