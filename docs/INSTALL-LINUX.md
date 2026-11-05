# Linux 本番インストール手順

対象: Ubuntu 24.04 LTS / Debian 12 以降の解析用 Linux ミニ PC。
WSL2 は開発・検証用です。本番はネイティブ Linux を推奨します。

この手順では、アプリを `127.0.0.1:8787` に閉じ込め、必要に応じて
Nginx + OIDC リバースプロキシの内側に置きます。アプリ自体に認証はありません。

---

## 0. 前提

| 項目 | 推奨 |
|---|---|
| OS | Ubuntu 24.04 LTS / Debian 12 |
| Python | 3.10 以上（標準ライブラリのみ） |
| CPU / RAM | 4コア / 8GB 以上（大規模ログは 16GB 推奨） |
| データ領域 | ext4 または LUKS 暗号化ボリューム |
| 公開範囲 | localhost。チーム利用は認証付きリバースプロキシの内側 |

**解析対象端末では実行しないでください。**
収集は EDR / Velociraptor / KAPE などで行い、収集済みの EVTX / ZIP を取り込みます。

---

## 1. OS と依存パッケージ

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y \
  python3 python3-venv \
  git curl ca-certificates \
  build-essential gcc make perl pkg-config libssl-dev cmake \
  sqlite3 jq
```

Rust はエンジンをビルドする場合だけ必要です。専用ユーザー作成後に実行します。

---

## 2. 専用ユーザーとディレクトリ

```bash
sudo useradd --system --create-home \
  --home-dir /var/lib/hayabusa-plus \
  --shell /bin/bash dfir

sudo mkdir -p /opt/hayabusa-plus /var/lib/hayabusa-plus /etc/hayabusa-plus
sudo chown -R dfir:dfir /opt/hayabusa-plus /var/lib/hayabusa-plus
sudo chmod 700 /var/lib/hayabusa-plus
```

`/var/lib/hayabusa-plus` がデータ領域です。
本番では、このディレクトリを LUKS 暗号化ボリューム上に置くことを推奨します。

---

## 3. コード配置とエンジンビルド

```bash
sudo -u dfir -H git clone \
  https://github.com/Assy2005/hayabusa-plus.git \
  /opt/hayabusa-plus

# Rust が未導入の場合のみ
sudo -u dfir -H bash -lc '
  curl --proto "=https" --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  source "$HOME/.cargo/env"
  rustup update stable
  cargo --version
'

sudo -u dfir -H bash -lc '
  cd /opt/hayabusa-plus
  bash tools/build_engine_linux.sh
'
```

エンジンが `bin/hayabusa-fx` に配置されます。
`--version` はこの Hayabusa では使えないため、確認は `help` を使います。

```bash
sudo -u dfir -H /opt/hayabusa-plus/bin/hayabusa-fx help | head
```

### ルール取得

```bash
sudo -u dfir -H bash -lc '
  cd /opt/hayabusa-plus
  ./bin/hayabusa-fx update-rules -r ./bin/rules
  mkdir -p bin/rules/hayabusa/custom
  cp -f rules-custom/*.yml bin/rules/hayabusa/custom/
'
```

IoC フィード取得は外向き通信を許可した場合のみ実行します。

```bash
sudo -u dfir -H bash -lc '
  cd /opt/hayabusa-plus
  python3 tools/fetch_feeds.py
'
```

---

## 4. 環境変数

テンプレートは `deploy/hayabusa-plus.env.example` にあります。

```bash
sudo cp /opt/hayabusa-plus/deploy/hayabusa-plus.env.example \
  /etc/hayabusa-plus/hayabusa.env
sudo chown root:dfir /etc/hayabusa-plus/hayabusa.env
sudo chmod 640 /etc/hayabusa-plus/hayabusa.env
```

既定値:

```text
HAYABUSA_DATA_ROOT=/var/lib/hayabusa-plus
HAYABUSA_GUI_HOST=127.0.0.1
HAYABUSA_GUI_PORT=8787
HAYABUSA_ACTOR=dfir-console
PYTHONUNBUFFERED=1
```

**`HAYABUSA_GUI_HOST=0.0.0.0` にしないでください。**
LAN 公開が必要な場合も、Nginx などの認証付きプロキシを同じホストに置き、
アプリは `127.0.0.1` のままにします。

---

## 5. systemd サービス

テンプレートは `deploy/hayabusa-plus.service` にもあります。

```bash
sudo cp /opt/hayabusa-plus/deploy/hayabusa-plus.service /etc/systemd/system/hayabusa-plus.service
sudo mkdir -p /opt/hayabusa-plus/bin/logs /opt/hayabusa-plus/lookups /opt/hayabusa-plus/suppressions
sudo chown -R dfir:dfir /opt/hayabusa-plus/bin/logs /opt/hayabusa-plus/lookups /opt/hayabusa-plus/suppressions
sudo systemctl daemon-reload
sudo systemctl enable --now hayabusa-plus
```

サービス定義の内容は `deploy/hayabusa-plus.service` を参照してください。

確認:

```bash
systemctl status hayabusa-plus --no-pager
curl -fsS http://127.0.0.1:8787/api/health | jq .
journalctl -u hayabusa-plus -n 50 --no-pager
```

---

## 6. 操作端末からの接続

もっとも安全な方法は SSH ポート転送です。

```bash
ssh -N -L 8787:127.0.0.1:8787 dfir@analysis-host
```

Windows のブラウザから `http://127.0.0.1:8787` を開きます。
この構成では、アプリのポートを LAN に公開する必要はありません。

---

## 7. チーム利用: Nginx + OIDC

アプリは `127.0.0.1:8787` のまま、Nginx と OIDC プロキシ
（oauth2-proxy / Authentik / Keycloak など）を前段に置きます。

```nginx
server {
    listen 443 ssl;
    server_name dfir.example.internal;

    ssl_certificate     /etc/ssl/certs/dfir.crt;
    ssl_certificate_key /etc/ssl/private/dfir.key;

    client_max_body_size 1g;

    location /oauth2/ {
        proxy_pass http://127.0.0.1:4180;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        auth_request /oauth2/auth;
        error_page 401 = /oauth2/sign_in;

        proxy_pass http://127.0.0.1:8787;
        proxy_http_version 1.1;
        # The app enforces loopback Host and same-origin POSTs. The proxy is
        # the trusted boundary, so it rewrites these to the app origin.
        proxy_set_header Host 127.0.0.1:8787;
        proxy_set_header Origin http://127.0.0.1:8787;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        # SSE (scan progress) をバッファリングしない
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
```

- OIDC で認証された利用者だけがアプリに到達できます
- アプリ側の `HAYABUSA_GUI_HOST` は必ず `127.0.0.1`
- `X-Forwarded-*` はアプリの認証には使っていません
- 公開範囲は社内 VLAN / VPN に限定してください

---

## 8. ファイアウォール

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
# Nginx を使う場合のみ
sudo ufw allow 443/tcp
sudo ufw enable
```

`8787` は開けないでください。

---

## 9. データ領域とバックアップ

データ領域:

```text
/var/lib/hayabusa-plus/
├── uploads/
├── jobs/
├── audit/audit.jsonl
└── hayabusa-gui.sqlite
```

バックアップ例:

```bash
sudo systemctl stop hayabusa-plus
sudo sqlite3 /var/lib/hayabusa-plus/hayabusa-gui.sqlite \
  ".backup '/var/backups/hayabusa-gui-$(date +%F).sqlite'"
sudo tar -C /var/lib -czf /var/backups/hayabusa-data-$(date +%F).tgz hayabusa-plus
sudo systemctl start hayabusa-plus
```

- 監査ログは外部 SIEM / WORM へエクスポートしてください
- 証跡そのものの保持期限・削除手順を別途定めてください
- バックアップ先も暗号化してください

---

## 10. アップグレード

```bash
sudo systemctl stop hayabusa-plus
sudo tar -C /var/lib -czf /var/backups/hayabusa-pre-upgrade-$(date +%F).tgz hayabusa-plus

cd /opt/hayabusa-plus
sudo -u dfir -H git pull --ff-only
sudo -u dfir -H bash tools/build_engine_linux.sh
sudo -u dfir -H bash -lc '
  ./bin/hayabusa-fx update-rules -r ./bin/rules
  cp -f rules-custom/*.yml bin/rules/hayabusa/custom/
'
sudo systemctl start hayabusa-plus
curl -fsS http://127.0.0.1:8787/api/health
```

---

## 11. トラブルシュート

### 起動しない

```bash
journalctl -u hayabusa-plus -n 100 --no-pager
curl -v http://127.0.0.1:8787/api/health
```

### `no Linux Hayabusa engine found`

```bash
ls -l /opt/hayabusa-plus/bin/hayabusa-fx
sudo -u dfir -H /opt/hayabusa-plus/bin/hayabusa-fx help | head
```

### ポートが使用中

```bash
ss -ltnp | grep 8787
```

`HAYABUSA_GUI_PORT` を変更するか、既存プロセスを停止します。

### アップロードが失敗する

- Nginx の `client_max_body_size` を確認
- データ領域の空き容量と所有者を確認
- `ReadWritePaths` にデータ領域が含まれているか確認

---

## 12. 本番前チェックリスト

- [ ] 解析対象端末と解析ホストが分離されている
- [ ] アプリは `127.0.0.1` のみで待受
- [ ] データ領域は ext4 / LUKS 上
- [ ] `dfir` 以外のユーザーがデータ領域を読めない
- [ ] systemd の hardening が有効
- [ ] SSH ポート転送または OIDC プロキシ経由で接続
- [ ] 8787 を LAN / インターネットに公開していない
- [ ] バックアップとリストアを一度テストした
- [ ] 監査ログを外部へエクスポートしている
- [ ] 検知ルールの更新手順を決めている
