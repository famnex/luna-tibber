#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
APP_DIR="$PWD"
if [[ "$APP_DIR" == *' '* || "$APP_DIR" == *'%'* ]]; then
  echo 'Bitte einen Installationspfad ohne Leerzeichen oder Prozentzeichen verwenden.' >&2
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  echo 'Zuerst install.sh mit Python 3.12+ ausführen.' >&2
  exit 1
fi
if [[ ! -f web-auth.json ]]; then
  .venv/bin/python web.py setup
fi
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/luna-web.service" <<EOF
[Unit]
Description=LUNA Webinterface

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/web.py serve --host 0.0.0.0 --port 8099
Restart=no
TimeoutStopSec=55
KillMode=mixed
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now luna-web
printf '\nWebinterface läuft auf Port 8099. Für Start ohne Anmeldung:\nsudo loginctl enable-linger "%s"\n' "$(id -un)"
