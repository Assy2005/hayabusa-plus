#!/usr/bin/env bash
# hayabusa-plus launcher for WSL2 / Linux (Windows is compatibility-only).
#
#   ./start.sh                 analysis host, localhost only (default)
#   ./start.sh --open          same, then open the browser
#   ./start.sh --shared        bind 0.0.0.0 (requires explicit opt-in)
#   PORT=9000 ./start.sh       change the preferred port
#   DATA_ROOT=/srv/dfir ./start.sh
#
# Enterprise posture
# ------------------
# This console has no authentication. It is designed to run on a dedicated
# analysis host or WSL2 VM with the UI reachable only from localhost. Network
# exposure is an explicit, guarded decision — not a side effect of a flag.
#
#   HAYABUSA_ALLOW_UNAUTHENTICATED=1 ./start.sh --shared
#
# Never run this on the endpoint being investigated. Collect EVTX with your
# existing EDR/collection tooling, verify the hash, then analyse here.

set -euo pipefail
cd "$(dirname "$0")"
umask 077

usage() {
  sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'
}

OPEN_BROWSER=0
SHARED=0
for arg in "$@"; do
  case "$arg" in
    --open) OPEN_BROWSER=1 ;;
    --shared|--public) SHARED=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[hayabusa-plus] unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

PORT="${PORT:-8787}"
case "$PORT" in
  ''|*[!0-9]*) echo "[hayabusa-plus] PORT must be a number (1-65535)." >&2; exit 2 ;;
esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "[hayabusa-plus] PORT out of range: $PORT" >&2
  exit 2
fi

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "[hayabusa-plus] Python 3.10+ was not found on PATH." >&2
  exit 1
fi
if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)'; then
  echo "[hayabusa-plus] Python 3.10+ is required (found $("$PY" --version 2>&1))." >&2
  exit 1
fi

# ---- analysis-host detection ------------------------------------------------
RUNTIME="linux"
if [ "$(uname -s 2>/dev/null || true)" = "Darwin" ]; then
  RUNTIME="macos"
elif grep -qi microsoft /proc/version 2>/dev/null; then
  RUNTIME="wsl"
fi

if [ "$(id -u 2>/dev/null || echo 0)" = "0" ]; then
  echo "[hayabusa-plus] warning: running as root. Prefer a dedicated analyst account." >&2
fi

# ---- data root --------------------------------------------------------------
DATA_ROOT="${HAYABUSA_DATA_ROOT:-${HAYABUSA_WORKSPACE:-$PWD/workspace}}"
export HAYABUSA_DATA_ROOT="$DATA_ROOT"
export HAYABUSA_WORKSPACE="$DATA_ROOT"
mkdir -p "$DATA_ROOT/uploads" "$DATA_ROOT/results" "$DATA_ROOT/jobs" "$DATA_ROOT/audit"

if [ ! -w "$DATA_ROOT" ]; then
  echo "[hayabusa-plus] data root is not writable: $DATA_ROOT" >&2
  exit 1
fi
case "$DATA_ROOT" in
  /mnt/[a-z]/*)
    echo "[hayabusa-plus] note: data root is on a Windows drive via /mnt/." >&2
    echo "                For large evidence sets, use an ext4 path (for example" >&2
    echo "                ~/dfir-data or a dedicated ext4 VHD) for speed and custody." >&2
    ;;
esac

# ---- engine -----------------------------------------------------------------
ENGINE=""
for cand in bin/hayabusa bin/hayabusa-fx; do
  if [ -x "$cand" ]; then ENGINE="$cand"; break; fi
done
if [ -z "$ENGINE" ]; then
  ENGINE="$(find bin -maxdepth 1 -type f -name 'hayabusa*' ! -name '*.exe' -perm -u+x 2>/dev/null | head -n 1 || true)"
fi
if [ -z "$ENGINE" ]; then
  echo "[hayabusa-plus] no Linux Hayabusa engine found in bin/." >&2
  echo "                Build it with: tools/build_engine_linux.sh" >&2
  exit 1
fi

# ---- network posture --------------------------------------------------------
export HAYABUSA_GUI_PORT="$PORT"
export HAYABUSA_ACTOR="${HAYABUSA_ACTOR:-$(id -un 2>/dev/null || echo local-analyst)}"
if [ "$SHARED" = "1" ]; then
  if [ "${HAYABUSA_ALLOW_UNAUTHENTICATED:-0}" != "1" ]; then
    cat >&2 <<'EOM'
[hayabusa-plus] refusing to bind 0.0.0.0 without an explicit opt-in.

This console has no authentication. --shared publishes the upload, scan and
ranking surface to the LAN. Case, evidence, audit, job and detection APIs stay
loopback-only, but this is still a trusted-LAN-only mode.

For a trusted, isolated lab VLAN only:

  HAYABUSA_ALLOW_UNAUTHENTICATED=1 ./start.sh --shared

For enterprise use, keep the default localhost bind and put authentication
and TLS in front of it (reverse proxy / VPN / bastion), or use an isolated
analysis host.
EOM
    exit 3
  fi
  export HAYABUSA_GUI_HOST="0.0.0.0"
  export HAYABUSA_ALLOW_UNAUTHENTICATED=1
  BIND_LABEL="0.0.0.0 (shared, authentication disabled)"
else
  export HAYABUSA_GUI_HOST="127.0.0.1"
  BIND_LABEL="127.0.0.1 (localhost only)"
fi

echo
echo "  hayabusa-plus / DFIR console"
echo "  Runtime    : $RUNTIME"
echo "  Engine     : $ENGINE"
echo "  Data root  : $DATA_ROOT"
echo "  Audit log  : $DATA_ROOT/audit/audit.jsonl"
echo "  Bind       : $BIND_LABEL"
echo "  Actor      : $HAYABUSA_ACTOR (local label, not authentication)"
echo
if [ "$SHARED" = "1" ]; then
  echo "  Open       : http://<analysis-host>:$PORT (LAN ranking) / http://127.0.0.1:$PORT (operator)"
else
  echo "  Open       : http://127.0.0.1:$PORT"
fi
echo

if [ "$OPEN_BROWSER" = "1" ]; then
  ( sleep 1
    if command -v xdg-open >/dev/null 2>&1; then xdg-open "http://127.0.0.1:$PORT" >/dev/null 2>&1 || true
    elif command -v open >/dev/null 2>&1; then open "http://127.0.0.1:$PORT" >/dev/null 2>&1 || true
    elif command -v wslview >/dev/null 2>&1; then wslview "http://127.0.0.1:$PORT" >/dev/null 2>&1 || true
    fi
  ) &
fi

exec "$PY" gui/server.py
