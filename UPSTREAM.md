# Staying in sync with upstream lucidadl

This repo is a private fork of [Jude-A/lucidadl](https://github.com/Jude-A/lucidadl). The
goal is that `git merge upstream/main` is boring. To get there, **fork code lives in its
own files** and the upstream-owned files carry only tiny, marked hooks.

## What is ours, and what we touched

Fork-only files (upstream never touches these, so they cannot conflict):

| File | Purpose |
|---|---|
| `lucidadl/lidarr.py` | Lidarr API client, `config.ini`, retry state, staging helpers |
| `lucidadl/lucidarr_cli.py` | `lucida lucidarr` (alias `soularr`), `lucida web`, `lucida push-clearance` |
| `lucidadl/lucidarr_ext.py` | search tweaks: ellipsis/curly quotes, wrong-album title guard |
| `lucidadl/webui.py`, `lucidadl/assets/` | the clearance upload page and its logo |
| `scripts/lucida_token.py` | standalone clearance fetcher (no lucidadl needed) |
| `scripts/sync-upstream.sh`, `scripts/slim-tree.sh` | merge helper, working-tree slimmer |
| `.github/workflows/lucidarr-ci.yml` | our CI: both test suites |
| `deploy/`, `config.ini.example`, `LUCIDARR.md`, `UPSTREAM.md`, `selftest_lucidarr.py` | install, docs, tests |

Upstream-owned files we edited (a dozen lines in total; look for "fork hook"):

| File | Edit |
|---|---|
| `lucidadl/cli.py` | 5 lines right after the `ui` command: `from . import lucidarr_cli` (registers our commands) |
| `lucidadl/downloader.py` | 2 lines in `_query_variants` (simplified search variants) and 4 in `_resolve_url` (wrong-album guard); the imports are inline, so the import block is untouched |

Everything else (README, `pyproject.toml`, `selftest.py`, `matching.py`, ...) is byte-for-byte
upstream. Keep it that way: new behaviour goes in the fork-only files.

## Updating

```bash
scripts/sync-upstream.sh        # fetch, merge upstream/main, run BOTH test suites
git push origin main
```

then update the LXC as usual (`deploy/update.sh`).

If the merge reports a conflict, it can only be in the two files above (or a file we
deliberately changed later). In `cli.py` keep upstream's code and re-add the 5-line hook after the
`ui` command; in `downloader.py` keep upstream's code and re-apply the marked hook lines.
Then `python selftest.py && python selftest_lucidarr.py`.

If an upstream release *changes the function a hook calls* (e.g. renames
`_query_variants` or `_resolve_url`), `selftest_lucidarr.py` fails and says which.

## "Stripping down" without making merges hard

Deleting upstream's files or cutting code out of `api.py` / `cli.py` (the TUI, playlist
import, the Windows scheduler, the Nix flake) would turn every upstream release into a
manual merge, because upstream edits those files (the Nix files change on nearly every
release). So we **hide instead of delete**:

```bash
scripts/slim-tree.sh        # sparse-checkout: hides nix/, flake.*, docs/, release tooling...
scripts/slim-tree.sh --off  # show everything again
```

History and merges are unaffected; only the files in your working tree are fewer. The
server install is slimmed differently: it skips Chromium and Xvfb unless asked
(`WITH_BROWSER=1`), since tokens come from `scripts/lucida_token.py`.

Upstream's GitHub Actions stay as they are: its CI runs, and its release/publish/mirror
workflows skip themselves on this private repo. `.github/workflows/lucidarr-ci.yml` is ours
and also runs `selftest_lucidarr.py`.

Install the fork **editable** (`pip install -e .`, as `deploy/install.sh` does). The logo is
not listed in `pyproject.toml` (an upstream-owned file we leave alone), so a regular
wheel install would simply serve the clearance page without it.
