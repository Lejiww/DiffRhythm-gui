#!/usr/bin/env bash
# run_gui.sh — launch your Python GUI using the venv
# Usage:
#   chmod +x run_gui.sh
#   ./run_gui.sh
# You can override the variables below by exporting them before running.

set -Eeuo pipefail

# ===== Default config (override via env vars) =====
APP_DIR="${APP_DIR:-/path/to/DiffRhythm}"
VENV_DIR="${VENV_DIR:-$APP_DIR/venv}"
APP_ENTRY="${APP_ENTRY:-$APP_DIR/gui/app.py}"
PY="${PY:-$VENV_DIR/bin/python}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-7860}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"    # optional KEY=VALUE file
OPEN_BROWSER="${OPEN_BROWSER:-1}"        # 1 = try to open browser (uses xdg-open)
AUTO_CREATE_VENV="${AUTO_CREATE_VENV:-0}" # 1 = create venv + pip install if missing

err(){ echo -e "\e[1;31m[ERR]\e[0m $*" >&2; exit 1; }
log(){ echo -e "\e[1;34m[*]\e[0m $*"; }
ok(){  echo -e "\e[1;32m[OK]\e[0m $*"; }

create_venv_if_needed(){
  if [[ "$AUTO_CREATE_VENV" == "1" && ! -x "$PY" ]]; then
    log "Creating venv at: $VENV_DIR"
    command -v python3 >/dev/null 2>&1 || err "python3 not found"
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/python" -m pip install --upgrade pip wheel >/dev/null
    if [[ -f "$APP_DIR/requirements.txt" ]]; then
      log "Installing dependencies from requirements.txt"
      "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
    else
      log "No requirements.txt found — venv created without deps"
    fi
  fi
}

load_env_file(){
  if [[ -f "$ENV_FILE" ]]; then
    log "Loading env vars from $ENV_FILE"
    set -a
    # load KEY=VALUE lines, ignore comments/empty lines
    # shellcheck disable=SC1090
    source <(grep -E '^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*=.+$' "$ENV_FILE" | sed 's/^[[:space:]]*//')
    set +a
  fi
}

maybe_open_browser(){
  if [[ "$OPEN_BROWSER" == "1" ]]; then
    if command -v xdg-open >/dev/null 2>&1; then
      ( sleep 1; xdg-open "http://localhost:$PORT" >/dev/null 2>&1 || true ) &
      ok "Opening browser at http://localhost:$PORT"
    else
      log "xdg-open not available — open http://localhost:$PORT manually"
    fi
  fi
}

[[ -d "$APP_DIR" ]] || err "APP_DIR not found: $APP_DIR"
cd "$APP_DIR"

create_venv_if_needed

[[ -x "$PY" ]] || err "Venv Python not found: $PY (set VENV_DIR or use AUTO_CREATE_VENV=1)"
[[ -f "$APP_ENTRY" ]] || err "Entry file not found: $APP_ENTRY"

export PYTHONUNBUFFERED=1

load_env_file
maybe_open_browser

log "Starting: $PY $APP_ENTRY --host $HOST --port $PORT"
exec "$PY" "$APP_ENTRY" --host "$HOST" --port "$PORT"
