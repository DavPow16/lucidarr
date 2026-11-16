<p align="center">
  <img src="../lucidadl/assets/lucidarr.svg" alt="lucidarr" width="320">
</p>

# lucidarr

**Fetch the albums Lidarr is missing from [lucida.to](https://lucida.to), and have Lidarr import them.**
A [Soularr](https://soularr.net)-style companion for Lidarr, built on
[lucidadl](https://github.com/Jude-A/lucidadl).

> **This is an unofficial fork.** For plain lucidadl (the downloader itself), use
> [Jude-A/lucidadl](https://github.com/Jude-A/lucidadl). This project adds the Lidarr
> integration on top of it and is not affiliated with lucida.to, Lidarr, Soularr, or any
> streaming service.

## What it does

lucidarr runs on a schedule. Each cycle it:

1. asks Lidarr for its **wanted** (missing, or cutoff-unmet) albums,
2. searches Lucida for each one as `Artist - Album` and downloads it as FLAC,
3. tags it, names the folder the way Lidarr expects, and tells Lidarr to **import** it,
4. checks that the wanted album actually received the files, and remembers what failed so
   it doesn't hammer the same albums every cycle.

It's configured with a Soularr-style `config.ini`, so if you've run Soularr the settings
will look familiar.

## What it is not

- **Not a replacement for everything Soularr covers.** It can only fetch what lucida.to
  can resolve (today mostly Amazon Music; upstream reports Qobuz as unreliable). Older,
  niche and some major-label albums simply aren't there and are skipped. Newer releases
  work best. Running both side by side is reasonable.
- **Not hands-off forever.** Lucida sits behind Cloudflare, so it needs a token (a cookie
  from a real browser) that expires every so often. See [The token](#the-token).
- **Lightly tested.** Developed against Lidarr 3.1.x and a few dozen albums. Expect rough
  edges and please open an issue when you find one.

## Requirements

- Lidarr (API v1; tested on 3.1.6) and its API key
- Python 3.10+
- A folder that both lucidarr and Lidarr can read and write (it is used for staging)
- A machine with a desktop and Chromium, to get the Cloudflare token

## Quick start

```bash
git clone https://github.com/DavPow16/lucidarr && cd lucidarr
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp config.ini.example config.ini                  # set [Lidarr] api_key + host_url
python scripts/lucida_token.py --install -o ~/.local/share/lucidadl/clearance.json
lucida lucidarr --dry-run                         # show what it would fetch
lucida lucidarr                                   # run one cycle
lucida lucidarr --interval 3600                   # keep running, a cycle per hour
```

> **Use a dedicated virtualenv.** lucidarr installs the same `lucidadl` package and
> `lucida` command as upstream, so don't install both into one environment. `pipx` with its
> own environment works too.

If Lidarr sees the staging folder at a different path (Docker, NAS), set
`[Lidarr] download_dir` to that path and `[Lucida] download_dir` to the local one.

## The token

Downloads need a `cf_clearance` cookie that only a real browser can obtain.
`scripts/lucida_token.py` fetches it **without lucidadl installed** (it needs only
Playwright, or `uv run scripts/lucida_token.py`):

```bash
python scripts/lucida_token.py --install                    # first time: fetch Chromium
python scripts/lucida_token.py -o clearance.json            # save it
python scripts/lucida_token.py --push http://lucidarr:8787  # upload it to the server
python scripts/lucida_token.py --push http://lucidarr:8787 --every 360   # refresh every 6 h
```

The cookie is tied to your IP address, so fetch it on the same network as the server, and
treat the file like a password. On a server, `lucida web` serves a small password-protected
page (set `[Web] password`) that accepts the upload or a pasted `clearance.json`. **It is
plain HTTP for a trusted LAN. Don't expose it to the internet.**

When the token expires, a cycle fails fast with `lucida.to access is not ready`, and
repeated empty results abort the cycle without marking albums as failed. Upload a fresh
one and carry on.

## Configuration

| Section | Keys |
|---|---|
| `[Lidarr]` | `api_key`, `host_url`, `download_dir` (staging folder *as Lidarr sees it*), `disable_sync`, `import_method` (`auto`, `scan`, `manual`) |
| `[Lucida]` (replaces Soularr's `[Slskd]`) | `download_dir` (local staging), `service`, `country`, `jobs`, `convert_to`, `bitrate`, `hidden`, `import_timeout` |
| `[Search Settings]` | `search_source` (`missing`, `cutoff_unmet`), `search_type` (`all`, `first_page`, `incrementing_page`), `number_of_albums_to_grab`, `remove_wanted_on_failure`, `retry_after_hours`, `title_blacklist` |
| `[Web]` | `host`, `port`, `password` |
| `[Logging]` | `level`, `format`, `datefmt` |

The file is found via `--config`, `$LUCIDARR_CONFIG`, `./config.ini`, then the app-data
folder. Command-line options and the `LIDARR_URL`, `LIDARR_API_KEY`, `LIDARR_REMOTE_DIR`
and `SCRIPT_INTERVAL` (seconds) variables override it. Soularr's `[Release Settings]` have
no equivalent: Lucida serves one release per album.

Start with `remove_wanted_on_failure = False`. Turning it on makes lucidarr unmonitor
albums it can't find.

## Running it as a service (Debian / Proxmox LXC)

```bash
REPO=/path/to/clone STAGING=/mnt/Downloads ./deploy/install.sh          # no browser (default)
REPO=/path/to/clone STAGING=/mnt/Downloads WITH_BROWSER=1 ./deploy/install.sh   # + Chromium/Xvfb
deploy/update.sh                                                        # after a git pull
```

This installs the `lucidarr` and `lucidarr-web` systemd units. By default the server never
opens a browser; the token is uploaded with `scripts/lucida_token.py --push`. In the
author's setup Chromium under Xvfb did not get past Cloudflare on its own, while the same
script on a desktop did, so `WITH_BROWSER=1` is optional. The staging folder must be
writable by the service user and readable and movable by Lidarr. With separate unprivileged
LXCs that usually means a shared group on the host.

## How an album flows (details)

1. The result's title must really name the wanted album, so a different album by the same
   artist (say a "Christmas Duets" for a wanted "Christmas With …") is rejected.
2. The download lands in `<download_dir>/<id>-<name>/`. A completion marker is written, so
   an interrupted download is discarded and redone, never imported half-finished.
3. The files are gathered into one folder named `Artist - Album (Year)` and tagged with
   Lidarr's own artist and album names. Lidarr reads the artist from the folder name when
   scanning, which is why plain folder names fail.
4. Lidarr is asked to import (`auto`: folder scan first, then Manual Import if files were
   left), and lucidarr verifies the wanted album received files. If they were attached to
   a same-titled twin edition, the wanted entry is skipped from then on.
5. Failures wait `retry_after_hours`. Three empty results in a row, with no success in that
   cycle, abort it without recording them.

## Troubleshooting

- **Lidarr imports nothing.** Check that Lidarr can see the staging folder at the path in
  `[Lidarr] download_dir`, and can read and write it. Lidarr's own log (Debug level) says
  why it rejected a folder.
- **`no confident match`.** Lucida returned results but none was the album (often
  karaoke, covers or a different edition). Check with `lucida search "<artist> <album>"`.
- **A wanted album stays wanted after import.** Lidarr often lists one release twice. If
  the files landed on the other record, lucidarr logs it and stops retrying that entry.

## Staying in sync with lucidadl

This repo keeps its own code in separate files and edits only about a dozen lines of
upstream's, so `git merge upstream/main` is normally clean. See
[UPSTREAM.md](../UPSTREAM.md) for the details and the helper scripts.

```bash
python selftest.py            # upstream's own suite
python selftest_lucidarr.py   # lucidarr's suite (offline, no browser or network)
```

## Disclaimer

Use lucidarr only for content you are entitled to download. You are responsible for
complying with applicable law and with the terms of the services involved. This project is
not affiliated with lucida.to, Lidarr, Soularr, or any streaming service.

## Credits and license

- [lucidadl](https://github.com/Jude-A/lucidadl) by Jude-A does all the downloading; this
  project is a fork that adds the Lidarr integration.
- The `config.ini` layout and the folder-naming idea come from
  [Soularr](https://github.com/mrusse/soularr).
- The logo is a remix of Lucida's mark in Lidarr's green, a nod and not an endorsement. It
  implies no affiliation, and will be replaced if its owners ask.
- MIT licensed; see [LICENSE](../LICENSE).
