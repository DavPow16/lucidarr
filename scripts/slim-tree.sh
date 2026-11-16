#!/usr/bin/env bash
# Hide files this fork does not use from the working tree (sparse-checkout). Nothing is
# deleted from history, so merging upstream stays conflict-free. See UPSTREAM.md.
#   scripts/slim-tree.sh          hide them
#   scripts/slim-tree.sh --off    show everything again
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

if [ "${1:-}" = "--off" ]; then git sparse-checkout disable; echo "Full tree restored."; exit 0; fi

git sparse-checkout set --no-cone --stdin <<'PATTERNS'
/*
!/.github/workflows/
!/.github/ISSUE_TEMPLATE/
!/.github/PULL_REQUEST_TEMPLATE.md
!/nix/
!/flake.nix
!/flake.lock
!/schedule.ps1
!/release-please-config.json
!/.release-please-manifest.json
!/docs/
!/tests/
!/inputs/
!/CHANGELOG.md
!/CONTRIBUTING.md
!/scripts/release.py
!/scripts/check_release_title.py
PATTERNS
echo "Working tree slimmed. Restore with: scripts/slim-tree.sh --off"
