#!/usr/bin/env bash
# hayabusa-plus launcher (Linux / macOS / WSL)
#
#   ./start.sh            ローカル専用で起動  (http://127.0.0.1:8787)
#   ./start.sh --public   LAN に公開して起動  (0.0.0.0 / 認証なし)
#   PORT=9000 ./start.sh  ポートを変更
#
# --public は研究室の PC を「誰でもログを調べられる」共有機にする用途。
# 認証が無いので、信頼できる LAN 内でのみ使うこと (インターネットに晒さない)。

set -euo pipefail
cd "$(dirname "$0")"

export HAYABUSA_GUI_PORT="${PORT:-8787}"

if [ "${1:-}" = "--public" ]; then
  export HAYABUSA_GUI_HOST="0.0.0.0"
fi

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "[hayabusa-plus] python3 が見つかりません。Python 3 を入れてください。" >&2
  exit 1
fi

# Linux 版エンジン (拡張子なし) が bin/ にあるか軽くチェック
if ! ls bin/hayabusa* 2>/dev/null | grep -qv '\.exe$'; then
  echo "[hayabusa-plus] bin/ に Linux 版エンジンがありません。"
  echo "                先に  tools/build_engine_linux.sh  を実行してビルドしてください。"
fi

exec "$PY" gui/server.py
