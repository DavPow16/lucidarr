#!/usr/bin/env bash
# Install lucidarr as an always-on service inside a Debian/Ubuntu LXC. Run as root.
#   REPO=https://github.com/DavPow16/lucidarr.git ./install.sh
# Private repo: use a URL with a token, or clone it yourself and set REPO=/path/to/clone.
#
# By default NO browser is installed: Cloudflare clearance comes from scripts/lucida_token.py
# run on a machine with a desktop and uploaded to the web page (a much smaller install).
# Set WITH_BROWSER=1 to also install Chromium + Xvfb (renewing on the server did not pass
# Cloudflare in our LXC, so this is optional).
set -euo pipefail

REPO="${REPO:-https://github.com/DavPow16/lucidarr.git}"
APP_USER="${APP_USER:-lucidarr}"
APP_DIR=/opt/lucidarr
DATA_DIR=/var/lib/lucidarr
STAGING="${STAGING:-/mnt/lucidarr-staging}"   # bind-mounted, shared with the Lidarr LXC
WITH_BROWSER="${WITH_BROWSER:-0}"

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }

apt-get update
apt-get install -y python3 python3-venv python3-pip git
[ "$WITH_BROWSER" = 1 ] && apt-get install -y xvfb xauth

id "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --home-dir "$DATA_DIR" "$APP_USER"
mkdir -p "$STAGING"
chown "$APP_USER": "$STAGING" 2>/dev/null || echo "note: could not chown $STAGING (bind mount?) - make sure $APP_USER can write to it"

if [ -d "$APP_DIR/.git" ]; then git -C "$APP_DIR" -c safe.directory="$APP_DIR" pull --ff-only "$REPO" main; else git clone "$REPO" "$APP_DIR"; fi
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q -e "$APP_DIR"
if [ "$WITH_BROWSER" = 1 ]; then
  # Browsers live inside the app dir so the service user (not just root) can launch them.
  export PLAYWRIGHT_BROWSERS_PATH="$APP_DIR/.pw"
  "$APP_DIR/.venv/bin/python" -m playwright install-deps chromium   # system libs (root)
  "$APP_DIR/.venv/bin/python" -m playwright install chromium
  XVFB="/usr/bin/xvfb-run -a "
else
  XVFB=""
fi
chown -R "$APP_USER": "$APP_DIR" "$DATA_DIR"

mkdir -p /etc/lucidarr
[ -f /etc/lucidarr/config.ini ] || install -m 640 -o root -g "$APP_USER" "$APP_DIR/config.ini.example" /etc/lucidarr/config.ini
sed -i "s|^download_dir = /data/lucidarr_downloads|download_dir = $STAGING|" /etc/lucidarr/config.ini
[ -f /etc/lucidarr.env ] || install -m 640 -o root -g "$APP_USER" "$APP_DIR/deploy/lucidarr.env.example" /etc/lucidarr.env
for unit in lucidarr lucidarr-web; do
  install -m 644 "$APP_DIR/deploy/$unit.service" "/etc/systemd/system/$unit.service"
  sed -i "s|@STAGING@|$STAGING|g; s|@USER@|$APP_USER|g; s|@XVFB@|$XVFB|g" "/etc/systemd/system/$unit.service"
done
systemctl daemon-reload

cat <<MSG

Installed (browser on this server: $([ "$WITH_BROWSER" = 1 ] && echo yes || echo no)). Next:
  1. Edit /etc/lucidarr/config.ini: [Lidarr] host_url + api_key, and [Web] password.
     (interval: interval in /etc/lucidarr/config.ini)
  2. Make sure $STAGING is writable by '$APP_USER' and readable/movable by Lidarr
     (same path in both LXCs, or set [Lidarr] download_dir in config.ini).
  3. Start the clearance page:  systemctl enable --now lucidarr-web
     Then, on a machine with a desktop (needs: pip install playwright):
       python scripts/lucida_token.py --push http://<this-lxc>:8787
  4. Test one album as the service user:
       runuser -u $APP_USER -- env PLAYWRIGHT_BROWSERS_PATH=$APP_DIR/.pw LUCIDARR_CONFIG=/etc/lucidarr/config.ini LUCIDADL_HOME=$DATA_DIR/data ${XVFB}$APP_DIR/.venv/bin/lucida lucidarr --limit 1
  5. systemctl enable --now lucidarr && journalctl -fu lucidarr
MSG
