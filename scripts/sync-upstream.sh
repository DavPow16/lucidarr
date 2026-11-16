#!/usr/bin/env bash
# Merge upstream lucidadl into this fork, then run both test suites. See UPSTREAM.md.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
PY="${PYTHON:-python}"

git remote get-url upstream >/dev/null 2>&1 || git remote add upstream https://github.com/Jude-A/lucidadl
git fetch upstream
n=$(git rev-list --count HEAD..upstream/main)
if [ "$n" = 0 ]; then echo "Already up to date with upstream."; exit 0; fi

echo "Incoming upstream commits ($n):"
git log --oneline HEAD..upstream/main
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "Commit or stash your changes first."; exit 1; }

if ! git merge --no-edit upstream/main; then
  echo
  echo "Merge conflicts in:"; git diff --name-only --diff-filter=U
  echo "Resolve per UPSTREAM.md, then 'git add' + 'git commit' (or 'git merge --abort')."
  exit 1
fi

"$PY" selftest.py | tail -1
"$PY" selftest_lucidarr.py | tail -1
echo "Merged and tested. Review, then: git push origin main"
