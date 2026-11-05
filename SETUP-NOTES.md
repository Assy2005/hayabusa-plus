# セットアップノート（WSL2 / Linux 優先）

最終更新: 2026-10-22

> Windows は互換ターゲットです。標準の解析ホストは **WSL2** または **Linux ミニ PC** です。
> 解析対象の端末上で、このコンソールを実行しないでください。
>
> 本番 Linux の systemd・TLS/OIDC・バックアップ手順は
> [docs/INSTALL-LINUX.md](docs/INSTALL-LINUX.md) を参照してください。

---

## 1. 前提

| 項目 | 要件 |
|---|---|
| OS | Linux / WSL2（推奨）、Windows 10/11（互換） |
| Python | 3.10 以上（標準ライブラリのみ） |
| エンジン | `bin/hayabusa` または `bin/hayabusa-fx`（Linux） |
| ルール | `bin/rules/` |
| 空き容量 | 証跡 + 解析結果 + SQLite。案件ごとに数 GB を見込む |
| ネットワーク | 既定は localhost。外部公開しない |

Rust ビルドはエンジンを差し替える場合だけ必要です。同梱エンジンがある場合は不要です。

---

## 2. 最短手順（WSL2 / Linux）

```bash
git clone https://github.com/Assy2005/hayabusa-plus.git
cd hayabusa-plus

# Linux 用エンジン（lookup 拡張入り）
bash tools/build_engine_linux.sh

# ルール取得（未取得の場合）
./bin/hayabusa-fx update-rules -r ./bin/rules
bash tools/build_engine_linux.sh

# カスタムルール
mkdir -p bin/rules/hayabusa/custom
cp rules-custom/*.yml bin/rules/hayabusa/custom/

# 任意: IoC フィード（外向き通信を許可した場合のみ）
python3 tools/fetch_feeds.py

# 起動（証跡はリポジトリ外の ext4 へ）
DATA_ROOT="$HOME/dfir-data" ./start.sh --open
```

ブラウザで `http://127.0.0.1:8787` を開きます。

### WSL2 のデータ領域

`/mnt/c/...` は遅く、Windows 側からも見えます。証跡は次のいずれかへ置いてください。

- WSL2 の ext4 ホーム（例 `~/dfir-data`）
- 専用の ext4 VHD（BitLocker / LUKS 相当の保護を検討）
- Linux ミニ PC の暗号化ディスク

```bash
export HAYABUSA_DATA_ROOT="$HOME/dfir-data"
./start.sh
```

`start.sh` はデータ領域を作成し、`umask 077` を適用します。

---

## 3. 画面構成（5 + 公開モード）

| 番号 | 画面 | 内容 |
|---|---|---|
| 01 | ホーム | 実行環境・待受・証跡・認証の姿勢、3 ステップ |
| 02 | スキャン | EVTX / ZIP 取込、案件名、プリセット、実行 |
| 03 | 結果 | 検知一覧、サマリ、ホスト、**ケース / 証跡** |
| 04 | 調査 | ハント、ログ検索、Elastic |
| 05 | 設定 | ルール、抑制 / 安全リスト、用語、このツール |
| 06 | ランキング | 公開（共有）モードのみ |

「ケース / 証跡」は結果グループのサブ画面です。ケースごとに証跡台帳、ジョブ、
監査履歴を表示し、監査ログのハッシュチェーンを検証できます。

---

## 4. 運用の基本

### 4.1 証跡の取込

1. スキャン画面で案件名を入力（例 `IR-2026-042 横展開調査`）。
2. EVTX または ZIP をドロップ。
3. アップロード完了時に SHA-256 の先頭が表示される。
4. 対象を選び、スキャン実行。

同じ案件名を再入力すると、同じオープンケースにまとまります。

### 4.2 スキャン前のハッシュ

- ファイル: ファイル全体の SHA-256
- ディレクトリ: ソート済みの `<sha256> <size> <relative-path>` 行に対する manifest ハッシュ

直接読取は行わないため、すべてのスキャン対象に証跡ハッシュが付きます。

結果画面の検知一覧の上に、案件名・証跡ハッシュ・ファイル数・サイズが表示されます。

### 4.3 監査ログ

`<data-root>/audit/audit.jsonl` に追記されます。
「ケース / 証跡」画面の「ハッシュチェーンを検証」で整合性を確認できます。

記録例:

- `case.open`
- `evidence.upload`
- `evidence.hash`
- `scan.requested` / `scan.start` / `scan.finish`
- `suppression.create` / `suppression.delete`
- `job.delete` / `jobs.clear`

`HAYABUSA_ACTOR` で監査上の表示名を指定できます（認証ではありません）。

```bash
HAYABUSA_ACTOR="analyst-a" ./start.sh
```

### 4.4 ジョブ削除と証跡

ジョブを削除しても、証跡台帳と監査ログは残ります。ジョブとの紐付けだけが外れます。
「すべて消去」も同様です。証跡そのものを削除する運用は、保持期限と手順を別途定めてください。

---

## 5. 共有モード（認証なし）

勉強会・閉域ラボでランキングを共有する場合だけ使用します。

```bash
HAYABUSA_ALLOW_UNAUTHENTICATED=1 ./start.sh --shared
```

- 既定では `0.0.0.0` バインドを拒否します。サーバ本体も opt-in なしの非 loopback バインドを拒否します。
- 認証はありません。LAN から可能なのは **アップロード・スキャン・ランキング閲覧** のみです。
- ケース、証跡台帳、監査ログ、ジョブ一覧、検知詳細、ホスト情報は loopback 限定です。
- インターネットに公開しないでください。
- 企業運用では localhost のまま、VPN / 認証付きリバースプロキシ / 踏み台の内側に置きます。

Windows 互換:

```powershell
$env:HAYABUSA_ALLOW_UNAUTHENTICATED='1'
.\start.ps1 -Public -DataRoot D:\dfir-data
```

### WSL2 の LAN 公開

WSL2 は NAT です。別 PC から接続するには Windows 側のポート転送が必要です。
セキュリティ上、**WSL2 の LAN 公開は推奨しません**。共有が必要なら Linux ネイティブで
起動するか、認証付きプロキシを前段に置いてください。

---

## 6. 環境変数

| 変数 | 既定 | 意味 |
|---|---|---|
| `HAYABUSA_DATA_ROOT` | `./workspace` | DB・uploads・jobs・audit のルート |
| `HAYABUSA_WORKSPACE` | 同上 | 旧名。`HAYABUSA_DATA_ROOT` を優先 |
| `HAYABUSA_GUI_HOST` | `127.0.0.1` | 待受アドレス |
| `HAYABUSA_GUI_PORT` / `PORT` | `8787` | 待受ポート |
| `HAYABUSA_ACTOR` | OS ユーザー | 監査ログの表示名 |
| `HAYABUSA_ALLOW_UNAUTHENTICATED` | 未設定 | `1` のときだけ共有モードを許可 |

---

## 7. 動作確認

```bash
python3 -m py_compile gui/audit.py gui/store.py gui/server.py
DATA_ROOT="$HOME/dfir-data" ./start.sh
```

確認ポイント:

1. ホームに実行環境・待受・認証の姿勢が出る。
2. スキャンで案件名を入力すると、結果一覧の「案件」列に出る。
3. アップロード後に SHA-256 が表示される。
4. スキャン後の検知一覧に証跡ハッシュが出る。
5. 「ケース / 証跡」でケース、証跡、監査履歴が見える。
6. 監査ログの検証が「正常」になる。
7. ジョブ削除後もケースの証跡台帳が残る。

---

## 8. 既知の制約

- 認証・RBAC・SSO は未実装。前段で補う。
- 監査ログはローカルのハッシュチェーン。WORM ではない。
- 遠隔収集エージェントは持たない。Velociraptor / EDR / KAPE と組み合わせる。
- Elasticsearch / Kibana 連携は任意。実環境での検証は別途必要。
- Windows でも直接読取は行わず、収集済み EVTX / ZIP の取込のみ。
