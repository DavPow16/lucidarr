#!/usr/bin/env bash
# Install lucidarr as an always-on service inside a Debian/Ubuntu LXC. Run as root.
#   REPO=https://github.com/DavPow16/lucidarr.git ./install.sh
# Private repo: use a URL with a token, or clone it yourself and set REPO=/path/to/clone.
set -euo pipefail

REPO="${REPO:-https://github.com/DavPow16/lucidarr.git}"
APP_USER="${APP_USER:-lucidarr}"
APP_DIR=/opt/lucidarr
DATA_DIR=/var/lib/lucidarr
STAGING="${STAGING:-/mnt/lucidarr-staging}"   # bind-mounted, shared with the Lidarr LXC

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }

apt-get update
apt-get install -y python3 python3-venv python3-pip git xvfb xauth

id "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --home-dir "$DATA_DIR" "$APP_USER"
mkdir -p "$STAGING"
chown "$APP_USER": "$STAGING" 2>/dev/null || echo "note: could not chown $STAGING (bind mount?) - make sure $APP_USER can write to it"

if [ -d "$APP_DIR/.git" ]; then runuser -u "$APP_USER" -- git -C "$APP_DIR" pull --ff-only; else git clone "$REPO" "$APP_DIR"; chown -R "$APP_USER": "$APP_DIR"; fi
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q -e "$APP_DIR"
# Browsers live inside the app dir so the service user (not just root) can launch them.
export PLAYWRIGHT_BROWSERS_PATH="$APP_DIR/.pw"
"$APP_DIR/.venv/bin/python" -m playwright install-deps chromium   # system libs (root)
"$APP_DIR/.venv/bin/python" -m playwright install chromium
chown -R "$APP_USER": "$APP_DIR" "$DATA_DIR"

mkdir -p /etc/lucidarr
[ -f /etc/lucidarr/config.ini ] || install -m 640 -o root -g "$APP_USER" "$APP_DIR/config.ini.example" /etc/lucidarr/config.ini
sed -i "s|^download_dir = /data/lucidarr_downloads|download_dir = $STAGING|" /etc/lucidarr/config.ini
[ -f /etc/lucidarr.env ] || install -m 640 -o root -g "$APP_USER" "$APP_DIR/deploy/lucidarr.env.example" /etc/lucidarr.env
install -m 644 "$APP_DIR/deploy/lucidarr.service" /etc/systemd/system/lucidarr.service
sed -i "s|@STAGING@|$STAGING|g; s|@USER@|$APP_USER|g" /etc/systemd/system/lucidarr.service
systemctl daemon-reload

cat <<MSG

Installed. Next:
  1. Edit /etc/lucidarr/config.ini  (Lidarr host_url + api_key; interval: /etc/lucidarr.env)
  2. Make sure $STAGING is writable by '$APP_USER' and readable/movable by Lidarr
     (same path in both LXCs, or set [Lidarr] download_dir in config.ini).
  3. Test one album as the service user:
       runuser -u $APP_USER -- env PLAYWRIGHT_BROWSERS_PATH=$APP_DIR/.pw bash -c 'LUCIDARR_CONFIG=/etc/lucidarr/config.ini LUCIDADL_HOME=$DATA_DIR/data xvfb-run -a $APP_DIR/.venv/bin/lucida lucidarr \\
         --limit 1'
  4. systemctl enable --now lucidarr && journalctl -fu lucidarr
MSG
