#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
PYTHON="${LUNA_PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12 oder neuer erforderlich; LUNA_PYTHON=/pfad/python3.12 setzen"'
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
printf '\nInstalliert. Weiter: .venv/bin/python luna.py setup\n'
