#!/usr/bin/env bash
# Update the installed copy from a refreshed clone. Run as root.
#   cd /root/lucidarr && git pull        # needs your GitHub token, see README
#   /root/lucidarr/deploy/update.sh
set -euo pipefail
REPO="${REPO:-/root/lucidarr}"
APP_USER="${APP_USER:-lucidarr}"
APP_DIR=/opt/lucidarr
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }

git -C "$APP_DIR" -c safe.directory="$APP_DIR" pull --ff-only "$REPO" main
"$APP_DIR/.venv/bin/pip" install -q -e "$APP_DIR"
chown -R "$APP_USER": "$APP_DIR"
# Keep whatever was chosen at install time: a browser (xvfb-run) or none.
XVFB=""
grep -q xvfb-run /etc/systemd/system/lucidarr.service 2>/dev/null && XVFB="/usr/bin/xvfb-run -a "
for unit in lucidarr lucidarr-web; do
  install -m 644 "$APP_DIR/deploy/$unit.service" "/etc/systemd/system/$unit.service"
  sed -i "s|@USER@|$APP_USER|g; s|@XVFB@|$XVFB|g" "/etc/systemd/system/$unit.service"
done
systemctl daemon-reload
for unit in lucidarr lucidarr-web; do
  systemctl is-enabled --quiet "$unit" 2>/dev/null && systemctl restart "$unit" && echo "restarted $unit"
done || true
echo "updated to $(git -C "$APP_DIR" -c safe.directory="$APP_DIR" log --oneline -1)"
