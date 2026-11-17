"""Fork-only commands: the Lidarr integration (``lucida lucidarr``), the clearance web page
(``lucida web``) and ``lucida push-clearance``.

Kept out of cli.py so upstream's file stays (almost) untouched and merges cleanly: cli.py
only imports this module at its very end, which registers the commands on its click group.
Upstream helpers are reached through ``_base`` so tests can patch them in one place.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Dict

import click

from . import cli as _base
from . import transcode

# --- Lidarr integration (lucidarr, Soularr-style config.ini) ----------------

async def _lucidarr_cycle(cfg, dry_run: bool = False) -> Dict[str, int]:
    import logging
    import shutil
    from . import lidarr
    log = logging.getLogger("lucidarr")
    stats = {"wanted": 0, "tried": 0, "imported": 0, "failed": 0, "skipped": 0}
    root = os.path.abspath(cfg.download_dir)

    # An outage on the lucida side must never look like "album not found": check access
    # first, so a dead Cloudflare session aborts the cycle instead of marking albums.
    if not dry_run and not _base.load_clearance()[1]:
        try:
            await _base.acquire_clearance(hidden=cfg.hidden)
        except Exception as e:
            raise lidarr.LidarrError(
                f"lucida.to access is not ready ({e}). Get a fresh clearance on a machine "
                "with a desktop and upload it: `python scripts/lucida_token.py --push "
                "http://<this host>:8787`.") from e

    client = lidarr.LidarrClient(cfg.url, cfg.api_key)
    attempts = lidarr.AttemptState()
    lucida_ok = False   # set once any download succeeds this cycle (lucida demonstrably works)
    pending = []        # failures we do not trust yet: (album id, query, reason)

    async def settle() -> None:
        """Record untrusted failures once lucida is proven to work (and only then
        unmonitor), so an outage cannot burn through the wanted list."""
        for aid_, q_, why in pending:
            attempts.record(aid_, q_, why)
            if cfg.remove_on_failure and why == "no-download":
                try:
                    await client.unmonitor(aid_)
                    lidarr.log_failure(q_)
                    log.warning("Unmonitored %s (listed in %s)", q_, lidarr.FAILURE_LIST_PATH)
                except lidarr.LidarrError as e:
                    log.error("Could not unmonitor %s: %s", q_, e)
        pending.clear()

    try:
        log.info("Connected to Lidarr %s", await client.check())
        if cfg.search_type == "all":
            albums = await client.wanted(cutoff=cfg.cutoff)
            total = len(albums)
        else:
            page = 1
            if cfg.search_type == "incrementing_page":
                first = await client.wanted_page(cfg.cutoff, 1, cfg.limit)
                pages = -(-int(first.get("totalRecords") or 0) // cfg.limit)
                page = attempts.next_page(pages)
                if not dry_run:
                    attempts.set_page(page + 1 if page < pages else 1)
            data = await client.wanted_page(cfg.cutoff, page, cfg.limit)
            albums, total = data.get("records") or [], int(data.get("totalRecords") or 0)
        stats["wanted"] = total
        log.info("%d wanted album(s) (%s), processing %d (%s).", total,
                 "cutoff_unmet" if cfg.cutoff else "missing", len(albums), cfg.search_type)
        for album in albums:
            if stats["tried"] >= cfg.limit:
                break
            query, aid = lidarr.album_query(album), album.get("id")
            if not query or aid is None:
                continue
            if lidarr.blacklisted(album, cfg.blacklist):
                log.info("Skipping blacklisted title: %s", query)
                stats["skipped"] += 1
                continue
            if not attempts.should_try(aid, cfg.retry_after):
                stats["skipped"] += 1
                continue
            stats["tried"] += 1
            if dry_run:
                log.info("Would fetch: %s", query)
                continue
            stage = lidarr.staging_dir(cfg.download_dir, album)
            partial = False
            if lidarr.audio_dirs(stage) and not lidarr.is_complete(stage):
                # An interrupted download: never import half an album or download on top.
                log.warning("Discarding an incomplete earlier download of %s", query)
                if os.path.abspath(stage).startswith(root + os.sep):
                    shutil.rmtree(stage, ignore_errors=True)
            if lidarr.audio_dirs(stage):
                # A finished download Lidarr did not take: re-scan it, don't download again.
                log.info("Re-scanning files staged earlier: %s", query)
            else:
                log.info("Fetching: %s", query)
                result = await _base._run([query], "album", cfg.service, cfg.country, "original",
                                    stage, cfg.hidden, cfg.jobs, dedup=False,
                                    organize_on=True, to_fmt=cfg.to_fmt,
                                    bitrate=cfg.bitrate, save_failures=False)
                if result[0]["ok"] == 0 or not lidarr.audio_dirs(stage):
                    log.warning("Nothing downloaded for: %s", query)
                    stats["failed"] += 1
                    lidarr.prune_empty(stage)
                    pending.append((aid, query, "no-download"))
                    if lucida_ok:
                        await settle()
                    elif len(pending) >= 3:
                        log.error("3 albums in a row returned nothing and none succeeded "
                                  "this cycle; assuming a lucida.to/Cloudflare problem (an expired "
                                  "clearance is the usual cause: upload a fresh one). "
                                  "Aborting without recording them.")
                        pending.clear()
                        break
                    continue
                lucida_ok = True
                await settle()
                partial = result[0]["fail"] > 0
                if not partial:
                    lidarr.mark_complete(stage)
            if cfg.disable_sync:
                log.info("disable_sync: left in %s for manual import", stage)
                attempts.record(aid, query, "staged")
                continue
            if partial:
                log.warning("Incomplete download for %s; discarding it to retry cleanly.",
                            query)
                if os.path.abspath(stage).startswith(root + os.sep):
                    shutil.rmtree(stage, ignore_errors=True)
                attempts.record(aid, query, "partial")
                stats["failed"] += 1
                continue
            # Soularr's recipe: one folder named "Artist - Title (Year)" (Lidarr reads the
            # artist from the folder name) with albumartist/album tags set to Lidarr's own.
            try:
                artist_name = (album.get("artist") or {}).get("artistName") or ""
                folder = await asyncio.to_thread(lidarr.consolidate, stage,
                                                 lidarr.release_folder_name(album))
                await asyncio.to_thread(lidarr.tag_files, folder, artist_name,
                                        album.get("title") or "")
                remote = lidarr.map_path(folder, cfg.download_dir, cfg.remote_dir or None)
                status = "completed"
                if cfg.import_method in ("auto", "scan"):
                    status = await client.import_folder(remote, wait=cfg.import_timeout)
                if cfg.import_method == "manual" or (
                        cfg.import_method == "auto" and lidarr.audio_dirs(stage)):
                    if cfg.import_method == "auto":
                        log.info("Scan left files behind; trying Manual Import for %s", query)
                    artist_id = album.get("artistId") or (album.get("artist") or {}).get("id")
                    status, done, seen, reasons = await client.manual_import(
                        remote, artist_id, aid, wait=cfg.import_timeout, replace=cfg.cutoff)
                    log.info("Lidarr matched %d of %d file(s) for %s", done, seen, query)
                    for reason in reasons[:8]:
                        log.warning("  %s", reason)
            except lidarr.LidarrError as e:
                log.error("Lidarr import failed for %s: %s", query, e)
                attempts.record(aid, query, "import-error")
                stats["failed"] += 1
                break  # Lidarr is unhappy; don't pile more albums on it this cycle
            lidarr.prune_empty(stage)
            if status == "completed" and not lidarr.audio_dirs(stage):
                landed = True
                if not cfg.cutoff:  # a cutoff album already has files, nothing to verify
                    try:
                        landed = await client.album_has_files(aid)
                    except lidarr.LidarrError:
                        landed = True  # cannot verify; trust the import
                if landed:
                    log.info("Imported into Lidarr: %s", query)
                    attempts.forget(aid)
                    stats["imported"] += 1
                else:
                    try:
                        sibling = await client.sibling_with_files(album)
                    except lidarr.LidarrError:
                        sibling = None
                    if sibling is not None:
                        log.info("Imported into Lidarr as another edition of %s (album id "
                                 "%s, same title); skipping this wanted entry from now on.",
                                 query, sibling)
                        attempts.record(aid, query, f"sibling:{sibling}")
                        stats["imported"] += 1
                    else:
                        log.warning(
                            "Lidarr took the files but attached them to a DIFFERENT album; "
                            "%s still has none. Check its History in Lidarr.", query)
                        attempts.record(aid, query, "import-elsewhere")
                        stats["failed"] += 1
            else:
                log.warning("Lidarr did not import it (scan %s); files kept in %s",
                            status, stage)
                attempts.record(aid, query, f"import-{status}")
                stats["failed"] += 1
        for aid_, q_, why in pending:  # few failures, nothing proven: cooldown only
            attempts.record(aid_, q_, why)
    finally:
        await client.aclose()
    return stats


@_base.cli.command("lucidarr")
@click.option("--config", "config_path", type=click.Path(dir_okay=False), default=None,
              help="Soularr-style config.ini (def: $LUCIDARR_CONFIG, ./config.ini, "
                   "<app data>/config.ini).")
@click.option("--lidarr-url", "url", envvar="LIDARR_URL", default=None,
              help="Override [Lidarr] host_url (env LIDARR_URL).")
@click.option("--api-key", envvar="LIDARR_API_KEY", default=None,
              help="Override [Lidarr] api_key (env LIDARR_API_KEY).")
@click.option("--download-dir", default=None,
              help="Override [Lucida] download_dir: local staging folder.")
@click.option("--remote-dir", envvar="LIDARR_REMOTE_DIR", default=None,
              help="Override [Lidarr] download_dir: the staging folder as Lidarr sees it.")
@click.option("--import-method", "import_method", type=click.Choice(["auto", "scan", "manual"]),
              default=None, help="Override [Lidarr] import_method (auto tries the scan, then Manual Import).")
@click.option("--cutoff", "source", flag_value="cutoff_unmet", default=None,
              help="Use cutoff-unmet albums (search_source).")
@click.option("--limit", type=click.IntRange(1), default=None,
              help="Override number_of_albums_to_grab.")
@click.option("--search-type", "search_type",
              type=click.Choice(["all", "first_page", "incrementing_page"]), default=None)
@click.option("--interval", envvar="SCRIPT_INTERVAL", type=click.IntRange(0), default=0,
              help="Seconds between cycles (env SCRIPT_INTERVAL); 0 = run once and exit.")
@click.option("--retry-after", type=float, default=None, help="Override retry_after_hours.")
@click.option("--import-timeout", type=int, default=None, help="Override import_timeout.")
@click.option("--dry-run", is_flag=True, help="List what would be fetched; download nothing.")
@click.option("-s", "--service", default=None, help="Override [Lucida] service.")
@click.option("--country", default=None, help="Override [Lucida] country.")
@click.option("-j", "--jobs", type=click.IntRange(1, 100), default=None)
@click.option("--to", "to_fmt", default=None, type=click.Choice(transcode.CHOICES),
              help="Override [Lucida] convert_to.")
@click.option("--bitrate", default=None, help="Override [Lucida] bitrate.")
@click.option("--hidden/--visible", "hidden", default=None)
@click.option("--solver-url", "solver_url", envvar="LUCIDARR_SOLVER_URL", default=None,
              help="Override [Lucida] solver_url (FlareSolverr/Byparr).")
def lucidarr_cmd(config_path, **opts):
    """Lidarr integration, Soularr-style: fetch Lidarr's wanted albums from lucida.to.

    Settings come from a Soularr-style config.ini (see config.ini.example); any command
    line option overrides it. Each wanted album is downloaded into a private staging
    folder, then imported by Lidarr (DownloadedAlbumsScan). Use --interval (or
    SCRIPT_INTERVAL) to keep it running."""
    import logging
    from . import lidarr
    dry_run = opts.pop("dry_run")
    try:
        path = lidarr.find_config(config_path)
        if config_path and not path:
            raise lidarr.LidarrError(f"Config file not found: {config_path}")
        cfg = lidarr.resolve(lidarr.load_config(path), opts)
        if not cfg.api_key:
            raise lidarr.LidarrError(
                "No Lidarr api_key. Set [Lidarr] api_key in config.ini or LIDARR_API_KEY.")
    except lidarr.LidarrError as e:
        click.secho(f"✗ {e}", fg="red")
        raise click.exceptions.Exit(1)
    try:
        logging.basicConfig(level=getattr(logging, cfg.log_level, logging.INFO),
                            format=cfg.log_format, datefmt=cfg.log_datefmt, force=True)
    except Exception:
        logging.basicConfig(level=logging.INFO, force=True)
    for noisy in ("httpx", "httpcore"):  # one INFO line per request floods the journal
        logging.getLogger(noisy).setLevel(logging.WARNING)
    log = logging.getLogger("lucidarr")
    log.info("Config: %s", path or "(defaults)")
    if cfg.solver_url:
        from . import solver
        solver.install(cfg.solver_url, cfg.solver_timeout)
        log.info("Cloudflare clearance via solver at %s", cfg.solver_url)
    cfg.download_dir = os.path.abspath(
        cfg.download_dir or os.path.join(_base.DEFAULT_OUT, ".lidarr"))
    try:
        os.makedirs(cfg.download_dir, exist_ok=True)
        probe = os.path.join(cfg.download_dir, f".lucidarr-write-{os.getpid()}")
        open(probe, "w").close()
        os.remove(probe)
    except OSError as e:
        click.secho(f"✗ Staging folder {cfg.download_dir} is not writable: {e}", fg="red")
        raise click.exceptions.Exit(1)
    cfg.interval = opts.get("interval") or 0
    while True:
        try:
            stats = asyncio.run(_lucidarr_cycle(cfg, dry_run))
        except lidarr.LidarrError as e:
            log.error("%s", e)
            if not cfg.interval:
                raise click.exceptions.Exit(1)
        except Exception:
            # An unexpected error must not turn the service into a restart loop that
            # ignores --interval: log it and wait for the next cycle.
            log.exception("Cycle crashed")
            if not cfg.interval:
                raise click.exceptions.Exit(1)
        else:
            log.info("Cycle done — wanted %d, tried %d, imported %d, failed %d, "
                     "skipped %d", stats["wanted"], stats["tried"], stats["imported"],
                     stats["failed"], stats["skipped"])
            if not cfg.interval:
                if stats["failed"]:
                    raise click.exceptions.Exit(1)
                return
        log.info("Next cycle in %d s (Ctrl+C to stop).", cfg.interval)
        try:
            time.sleep(cfg.interval)
        except KeyboardInterrupt:
            return


_base.cli.add_command(lucidarr_cmd, "soularr")  # alias for the Soularr-style name


@_base.cli.command("web")
@click.option("--config", "config_path", type=click.Path(dir_okay=False), default=None)
@click.option("--host", default=None, help="Override [Web] host.")
@click.option("--port", type=int, default=None, help="Override [Web] port.")
@click.option("--password", envvar="LUCIDARR_WEB_PASSWORD", default=None,
              help="Override [Web] password (env LUCIDARR_WEB_PASSWORD).")
def web_cmd(config_path, host, port, password):
    """Serve a password-protected page for uploading a Cloudflare clearance.

    Run `lucida setup` on a machine with a desktop, then upload its clearance here (or
    use `lucida push-clearance`). LAN use only: plain HTTP, never expose it publicly."""
    from . import lidarr, webui
    path = lidarr.find_config(config_path)
    if config_path and not path:
        click.secho(f"✗ Config file not found: {config_path}", fg="red")
        raise click.exceptions.Exit(1)
    cp = lidarr.load_config(path)
    host = host or cp.get("Web", "host")
    port = port or cp.getint("Web", "port")
    password = password or cp.get("Web", "password")
    if not password:
        click.secho("✗ Set [Web] password in config.ini (or LUCIDARR_WEB_PASSWORD) "
                    "before starting the web page.", fg="red")
        raise click.exceptions.Exit(1)
    server = webui.make_server(host, port, password)
    click.echo(f"Clearance page on http://{host}:{port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


@_base.cli.command("push-clearance")
@click.argument("url")
@click.option("--password", prompt=True, hide_input=True, envvar="LUCIDARR_WEB_PASSWORD")
def push_clearance_cmd(url, password):
    """Send this machine's saved clearance to a lucidarr web page.

    Run `lucida setup` here first so the clearance is fresh, then e.g.
    `lucida push-clearance http://192.168.1.50:8787`."""
    import httpx
    cf, ua = _base.load_clearance()
    if not ua:
        click.secho("No saved clearance on this machine; run `lucida setup` first.", fg="red")
        raise click.exceptions.Exit(1)
    try:
        r = httpx.post(url.rstrip("/") + "/api/clearance", timeout=15,
                       json={"cf_clearance": cf, "ua": ua},
                       headers={"Authorization": f"Bearer {password}"})
    except httpx.HTTPError as e:
        click.secho(f"✗ Could not reach {url}: {e}", fg="red")
        raise click.exceptions.Exit(1)
    if r.status_code == 200:
        click.secho("✓ Clearance uploaded.", fg="green")
    else:
        click.secho(f"✗ Server answered {r.status_code}: {r.text[:200]}", fg="red")
        raise click.exceptions.Exit(1)
