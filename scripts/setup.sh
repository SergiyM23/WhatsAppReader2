#!/usr/bin/env bash
# Install/update WhatsAppReader 2.0 on the existing OCI Ubuntu host.
# Re-runnable; preserves SQLite, existing nginx HTTPS site, and Chromium profile.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Run with sudo: sudo bash scripts/setup.sh' >&2; exit 1; fi
if [[ "$(uname -m)" != 'aarch64' && "$(uname -m)" != 'x86_64' ]]; then
  echo 'Unsupported CPU architecture' >&2; exit 1
fi
APP_USER="${WA_INSTALL_USER:-ubuntu}"
id "$APP_USER" >/dev/null || { echo "User $APP_USER does not exist" >&2; exit 1; }
SOURCE="$(cd "$(dirname "$0")/.." && pwd)"
TARGET=/opt/whatsappreader
mkdir -p "$TARGET" "$TARGET/data"/{images,reports} "$TARGET/logs" /etc/nginx/snippets
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-pip nginx apache2-utils snapd
# Copy only application files; do not copy local DB, profiles or any secrets.
cp -a "$SOURCE/whatsappreader" "$TARGET/"
cp -a "$SOURCE/requirements.txt" "$TARGET/requirements.txt"
if [[ ! -e "$TARGET/app.yaml" ]]; then cp "$SOURCE/app.example.yaml" "$TARGET/app.yaml"; fi
if [[ ! -d "$TARGET/.venv" ]]; then python3 -m venv "$TARGET/.venv"; fi
"$TARGET/.venv/bin/python" -m pip install --upgrade pip
"$TARGET/.venv/bin/python" -m pip install -r "$TARGET/requirements.txt"
chown -R "$APP_USER:$APP_USER" "$TARGET/data" "$TARGET/logs" "$TARGET/whatsappreader"
chmod 750 "$TARGET/data" "$TARGET/logs"
# Existing Chrome/ChromeDriver Snap installation is deliberately not modified.
if [[ ! -x /usr/bin/chromium-browser || ! -x /usr/bin/chromedriver ]]; then
  echo 'Chromium or ChromeDriver is missing; installing supported Ubuntu packages.'
  DEBIAN_FRONTEND=noninteractive apt-get install -y chromium-browser chromium-chromedriver
fi
# Create protected credentials only once; existing values are never overwritten.
if [[ ! -f /etc/whatsappreader.env ]]; then
  read -rp 'Web administrator username [admin]: ' ADMIN_USER
  ADMIN_USER="${ADMIN_USER:-admin}"
  [[ "$ADMIN_USER" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo 'Administrator name may only use letters, digits, _ and -.' >&2; exit 1; }
  read -rsp 'Web administrator password: ' ADMIN_PASSWORD; echo
  [[ ${#ADMIN_PASSWORD} -ge 12 ]] || { echo 'Use a password at least 12 characters long.' >&2; exit 1; }
  CSRF="$(openssl rand -hex 32)"
  printf 'WA_ADMIN_USER=%s\nWA_ADMIN_PASSWORD=%s\nWA_CSRF_TOKEN=%s\nGEMINI_API_KEY=\nTELEGRAM_BOT_TOKEN=\n' \
    "$ADMIN_USER" "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1],ensure_ascii=False))' "$ADMIN_PASSWORD")" "$CSRF" > /etc/whatsappreader.env
  chmod 600 /etc/whatsappreader.env
  printf '%s\n' "$ADMIN_PASSWORD" | htpasswd -iBc /etc/nginx/.whatsappreader-htpasswd "$ADMIN_USER"
  chmod 640 /etc/nginx/.whatsappreader-htpasswd
  chown root:www-data /etc/nginx/.whatsappreader-htpasswd
  unset ADMIN_PASSWORD
else
  echo 'Existing /etc/whatsappreader.env preserved.'
  if [[ ! -f /etc/nginx/.whatsappreader-htpasswd ]]; then
    echo 'WARNING: create /etc/nginx/.whatsappreader-htpasswd matching your admin credentials.' >&2
  fi
fi
cat > /etc/systemd/system/whatsappreader.service <<EOF
[Unit]
Description=WhatsAppReader scheduled processing
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
User=$APP_USER
WorkingDirectory=$TARGET
Environment=WA_READER_CONFIG=$TARGET/app.yaml
EnvironmentFile=/etc/whatsappreader.env
ExecStart=$TARGET/.venv/bin/python -m whatsappreader run --trigger scheduled
TimeoutStartSec=0
EOF
cat > /etc/systemd/system/whatsappreader-web.service <<EOF
[Unit]
Description=WhatsAppReader administration console
Wants=network-online.target
After=network-online.target
[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$TARGET
Environment=WA_READER_CONFIG=$TARGET/app.yaml
EnvironmentFile=/etc/whatsappreader.env
ExecStart=$TARGET/.venv/bin/python -m whatsappreader web
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
# Restrict schedule management to one fixed root-owned utility.
install -o root -g root -m 755 "$SOURCE/scripts/apply_schedule.py" /usr/local/sbin/whatsappreader-apply-schedule
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/whatsappreader-apply-schedule\n' "$APP_USER" \
    >/etc/sudoers.d/whatsappreader-schedule
chmod 440 /etc/sudoers.d/whatsappreader-schedule
visudo -cf /etc/sudoers.d/whatsappreader-schedule
cat > /etc/nginx/snippets/whatsappreader.conf <<'EOF'
location = /whatsappreader { return 301 /whatsappreader/; }
location /whatsappreader/ {
    auth_basic "WhatsAppReader Console";
    auth_basic_user_file /etc/nginx/.whatsappreader-htpasswd;
    proxy_pass http://127.0.0.1:8765;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Authorization $http_authorization;
    proxy_buffering off;
    proxy_read_timeout 3600;
}
EOF
NGINX_SITE=/etc/nginx/sites-available/main-https
if [[ -f "$NGINX_SITE" ]] && ! grep -q 'snippets/whatsappreader.conf' "$NGINX_SITE"; then
  cp "$NGINX_SITE" "$NGINX_SITE.before-whatsappreader"
  python3 - "$NGINX_SITE" <<'PY'
import pathlib,sys
path=pathlib.Path(sys.argv[1]);text=path.read_text()
pos=text.rfind('}')
if pos<0:raise SystemExit('Cannot find closing server block in existing nginx site.')
text=text[:pos]+'    include /etc/nginx/snippets/whatsappreader.conf;\n'+text[pos:]
path.write_text(text)
PY
  if ! nginx -t; then
    cp "$NGINX_SITE.before-whatsappreader" "$NGINX_SITE"
    echo 'nginx config test failed. Original nginx site restored.' >&2; exit 1
  fi
elif [[ ! -f "$NGINX_SITE" ]]; then
  echo 'WARNING: nginx site main-https was not found; include the new snippet in your existing HTTPS server.' >&2
fi
nginx -t && systemctl reload nginx
cd "$TARGET"
sudo -u "$APP_USER" env WA_READER_CONFIG="$TARGET/app.yaml" "$TARGET/.venv/bin/python" -m whatsappreader init
/usr/local/sbin/whatsappreader-apply-schedule
systemctl daemon-reload
systemctl enable --now whatsappreader-web.service
echo 'WhatsAppReader deployed: /whatsappreader/ (HTTPS, Basic Auth)'
echo 'Edit GEMINI_API_KEY and TELEGRAM_BOT_TOKEN in /etc/whatsappreader.env; restart web service after secret changes.'
