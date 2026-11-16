# lucidarr

<img src="lucidadl/assets/lucidarr.svg" alt="lucidarr" width="220">

A private fork of [lucidadl](https://github.com/Jude-A/lucidadl) that does for
[lucida.to](https://lucida.to) what [Soularr](https://soularr.net) does for Soulseek: it
reads Lidarr's wanted albums, downloads each from Lucida as `Artist - Album`, and has
Lidarr import the result. Configured with a Soularr-style `config.ini`.

See [UPSTREAM.md](UPSTREAM.md) for how the fork stays easy to merge with upstream.

## Quick start

```bash
pip install -e .                    # in a venv
cp config.ini.example config.ini    # set [Lidarr] api_key and host_url
python scripts/lucida_token.py -o ~/.local/share/lucidadl/clearance.json   # one-time token
lucida lucidarr --dry-run           # list what would be fetched
lucida lucidarr                     # one cycle
lucida lucidarr --interval 3600     # keep running, a cycle per hour
```

## The token (Cloudflare clearance)

lucida.to sits behind Cloudflare, so downloads need a `cf_clearance` cookie from a real
browser. `scripts/lucida_token.py` gets it **without lucidadl installed** (only Playwright,
or `uv run scripts/lucida_token.py`). It opens Chromium, lets the check pass, and either
saves the JSON or uploads it to the server:

```bash
python scripts/lucida_token.py --install                    # first time: fetch Chromium
python scripts/lucida_token.py -o clearance.json            # save it
python scripts/lucida_token.py --push http://lucidarr:8787  # upload to the server
python scripts/lucida_token.py --push http://lucidarr:8787 --every 360   # refresh every 6 h
```

Treat the file like a password. The cookie is tied to your IP address and browser user
agent, so get it from a machine on the same network as the server.

The server side is `lucida web` (service `lucidarr-web`): a small password-protected page
that accepts a pasted `clearance.json` or the script's upload. It needs `[Web] password`
in `config.ini`, is plain HTTP, and is meant for a trusted LAN only.

## Configuration (`config.ini`)

| Section | Keys |
|---|---|
| `[Lidarr]` | `api_key`, `host_url`, `download_dir` (staging folder *as Lidarr sees it*), `disable_sync`, `import_method` (`auto`/`scan`/`manual`) |
| `[Lucida]` (replaces Soularr's `[Slskd]`) | `download_dir` (local staging), `service`, `country`, `jobs`, `convert_to`, `bitrate`, `hidden`, `import_timeout` |
| `[Search Settings]` | `search_source` (`missing`/`cutoff_unmet`), `search_type` (`all`/`first_page`/`incrementing_page`), `number_of_albums_to_grab`, `remove_wanted_on_failure`, `retry_after_hours`, `title_blacklist` |
| `[Web]` | `host`, `port`, `password` |
| `[Logging]` | `level`, `format`, `datefmt` |

The file is found via `--config`, `$LUCIDARR_CONFIG`, `./config.ini`, then the app-data
folder. Command-line options and `LIDARR_URL`, `LIDARR_API_KEY`, `LIDARR_REMOTE_DIR`,
`SCRIPT_INTERVAL` (seconds) override it.

## How an album flows

1. Search Lucida for `Artist - Album` (Qobuz, then Amazon). The result's title must really
   name the wanted album, so a different album by the same artist is rejected.
2. Download into `<download_dir>/<id>-<name>/`; a completion marker is written, so an
   interrupted download is discarded and redone, never imported half-finished.
3. Gather the files into one folder called `Artist - Album (Year)` and set their
   `albumartist`/`album` tags to Lidarr's own values (Lidarr reads the artist from the
   folder name, exactly as Soularr arranges it).
4. Ask Lidarr to import (`auto`: folder scan, then Manual Import if files were left), and
   **verify the wanted album received files**. If they landed on a same-titled twin
   edition, the wanted entry is skipped from then on.
5. Failures wait `retry_after_hours` before another attempt. If 3 albums in a row return
   nothing and none succeed, the cycle aborts without recording them (an expired token
   looks like that).

## Server install (Debian LXC)

```bash
REPO=/root/lucidarr STAGING=/mnt/Downloads ./deploy/install.sh        # no browser (default)
REPO=/root/lucidarr STAGING=/mnt/Downloads WITH_BROWSER=1 ./deploy/install.sh   # + Chromium/Xvfb
deploy/update.sh                                                      # after a git pull
```

Without a browser the server never opens Chromium; the token arrives from
`scripts/lucida_token.py --push`. That is the reliable route: in our LXC, Chromium under
Xvfb did not get past Cloudflare on its own, while the same script on a desktop did.
`WITH_BROWSER=1` is there in case that works in your environment. The bind-mounted staging
folder must be writable by the `lucidarr` user and readable/movable by Lidarr.

## Tests

```bash
python selftest.py            # upstream's own suite, untouched
python selftest_lucidarr.py   # ours: Lidarr client, cycle logic, web page, token script
```
