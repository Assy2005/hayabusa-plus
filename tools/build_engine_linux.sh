#!/usr/bin/env bash
# フォーク版 Hayabusa (lookup 拡張入り) を Linux 向けにビルドして bin/ に置く。
#
#   bash tools/build_engine_linux.sh
#
# 前提: Rust ツールチェイン (cargo)。無ければ rustup で入れる:
#   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
#
# 注意: 初回ビルドは依存のコンパイルで数分〜十数分かかります。

set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

if ! command -v cargo >/dev/null 2>&1; then
  echo "[build] Rust (cargo) が見つかりません。下記でインストールしてください:" >&2
  echo "        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh" >&2
  echo "        その後  source \$HOME/.cargo/env  して再実行。" >&2
  exit 1
fi

echo "[build] cargo build --release  (engine/) ..."
( cd engine && cargo build --release )

# 生成バイナリを探す (.d などのメタファイルは除外)
BIN="$(find engine/target/release -maxdepth 1 -type f -name 'hayabusa*' ! -name '*.*' | head -n1)"
if [ -z "$BIN" ]; then
  echo "[build] 成果物が見つかりません (engine/target/release)。ビルド出力を確認してください。" >&2
  exit 1
fi

mkdir -p bin
cp -f "$BIN" bin/hayabusa-fx
chmod +x bin/hayabusa-fx
echo "[build] OK -> bin/hayabusa-fx"
./bin/hayabusa-fx --version 2>/dev/null || true

# --- Sigma ルール + カスタムルールの配置 ---
if [ -d bin/rules/hayabusa ]; then
  mkdir -p bin/rules/hayabusa/custom
  cp -f rules-custom/*.yml bin/rules/hayabusa/custom/
  echo "[build] custom rules -> bin/rules/hayabusa/custom/ ($(ls rules-custom/*.yml | wc -l) 本)"
else
  echo "[build] 注意: bin/rules がありません。Sigma ルールを取得してください:"
  echo "          ./bin/hayabusa-fx update-rules ./bin/rules"
  echo "        取得後にこのスクリプトを再実行すると custom ルールも配置されます。"
fi

echo
echo "[build] (任意) IoC フィード取得:  python3 tools/fetch_feeds.py"
echo "[build] 完了。起動:  ./start.sh           (ローカル)"
echo "                     ./start.sh --public  (LAN 公開・認証なし)"
