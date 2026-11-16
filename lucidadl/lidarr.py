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
import json
import os
import time
from typing import Any, Dict, List, Optional

import httpx

from . import paths, utils

AUDIO_EXTS = (".flac", ".mp3", ".m4a", ".aac", ".opus", ".ogg", ".wav")
STATE_PATH = str(paths.DATA_DIR / "lidarr-state.json")
_DONE_STATES = {"completed", "failed", "aborted", "cancelled", "orphaned"}


class LidarrError(Exception):
    pass


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

    def forget(self, album_id: int) -> None:
        if self.data.pop(str(album_id), None) is not None:
            self.save()

    def save(self) -> None:
        tmp = self.path + f".{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)


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
        return r.json()

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

    async def import_folder(self, remote_path: str, wait: float = 300.0,
                            poll: float = 3.0) -> str:
        """Run ``DownloadedAlbumsScan`` on a folder; returns the final command status."""
        cmd = await self._request("POST", "/command", json={
            "name": "DownloadedAlbumsScan", "path": remote_path,
            "importMode": "Move"})
        cid = cmd.get("id")
        deadline = time.monotonic() + wait
        status = str(cmd.get("status") or "queued")
        while status.lower() not in _DONE_STATES and time.monotonic() < deadline:
            await asyncio.sleep(poll)
            status = str((await self._request("GET", f"/command/{cid}"))
                         .get("status") or status)
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
