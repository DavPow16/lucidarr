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

if [ -d "$APP_DIR/.git" ]; then git -C "$APP_DIR" pull --ff-only; else git clone "$REPO" "$APP_DIR"; fi
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q -e "$APP_DIR"
# Chromium + the system libraries it needs (headed mode runs under Xvfb).
"$APP_DIR/.venv/bin/python" -m playwright install --with-deps chromium
chown -R "$APP_USER": "$APP_DIR" "$DATA_DIR"

[ -f /etc/lucidarr.env ] || install -m 640 -o root -g "$APP_USER" "$APP_DIR/deploy/lucidarr.env.example" /etc/lucidarr.env
install -m 644 "$APP_DIR/deploy/lucidarr.service" /etc/systemd/system/lucidarr.service
sed -i "s|@STAGING@|$STAGING|g; s|@USER@|$APP_USER|g" /etc/systemd/system/lucidarr.service
systemctl daemon-reload

cat <<MSG

Installed. Next:
  1. Edit /etc/lucidarr.env  (Lidarr URL + API key)
  2. Make sure $STAGING is writable by '$APP_USER' and readable/movable by Lidarr
     (same path in both LXCs, or set LIDARR_REMOTE_DIR in the env file).
  3. Test one album as the service user:
       sudo -u $APP_USER bash -c 'set -a; . /etc/lucidarr.env; set +a; \\
         LUCIDADL_HOME=$DATA_DIR/data xvfb-run -a $APP_DIR/.venv/bin/lucida lucidarr \\
         --download-dir $STAGING --limit 1'
  4. systemctl enable --now lucidarr && journalctl -fu lucidarr
MSG
