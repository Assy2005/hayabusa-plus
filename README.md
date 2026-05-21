# hayabusa-plus

[Yamato-Security/hayabusa](https://github.com/Yamato-Security/hayabusa) を
ベースにした、**ローカル完結型の DFIR 解析プラットフォーム** です。
Hayabusa 本体 (Rust) を拡張しつつ、その上に **localhost ブラウザ UI** を
被せ、検知ルール開発・スレットハンティング・フォレンジック作業を 1 つの
コンソールから行えるようにします。

オフライン / オンデマンド型。常駐エージェントではなく、EVTX に対して
ジョブベースで解析を回す DFIR ワークベンチです。

## 何ができるか

### 解析・調査
- **EVTX のドロップ & ドロップ** → 即スキャン、検知をリアルタイム表示
- **このパソコンを検査**: System32\winevt\Logs を直接ライブ解析、または
  指定チャネルだけを workspace にスナップショットコピー
- **検知の詳細解説**: ルール定義・誤検知例・ATT&CK 技術 (日本語)・
  推奨される次の調査ステップを 1 クリックで展開
- **プロセスツリー再構築**: 検知発生 ±N 分の Sysmon EID 1 から
  ProcessGuid を辿って親子関係を可視化、focal プロセスをハイライト

### ハンティング・運用
- **スレットハンティング検索**: ホスト (glob)・時間範囲・レベル・ルール・
  ATT&CK タグ・チャネル・EID・自由文字列の多軸検索
- **クイックプリセット**: 「直近 24h の重大」「痕跡隠蔽行為」「認証情報窃取」
  「永続化」「横展開兆候」「最多発火」をワンクリックで適用
- **ピボットビュー**: ルール別 / ホスト別 / 時系列 / 重要度別 集計
- **CSV エクスポート**: SOC レポート添付に使える Excel 互換 (BOM 付き) CSV
- **保存検索** (localStorage)
- **TP / FP フィードバック**: 検知ごとに判定を蓄積、`lookups/fp_history/`
  に書き出してスコアエンジンが将来読み取れる形式で保持
- **抑制ルール**: ホスト × ルールで検知を非表示にできる
  (削除ではなくフラグ、`suppressions/<host>.json` に履歴管理可能な形で保存)

### ダッシュボード
- KPI (検知総数 / Critical+High / 影響ホスト数 / 発火ルール種数)
- 重要度ドーナツ + 時系列スタック棒チャート (SVG、外部ライブラリ依存ゼロ)
- TOP ルール / TOP ホスト水平バー

## エンジン側拡張

upstream Hayabusa に対して以下の機能拡張を加えています (`engine/` 配下):

### `lookup:` Sigma 拡張
ルール YAML に外部 IoC ファイル参照を 1 行で書けるようになりました。

```yaml
lookup:
  - name: lol_drivers
    file: ../../../../lookups/loldrivers_sample.txt
  - name: golden_hashes
    file: ../../../../lookups/golden_image_hashes_sample.txt
detection:
  sel:
    Channel: 'Microsoft-Windows-Sysmon/Operational'
    EventID: 6
    Hashes|lookup: lol_drivers          # ← テーブル内のどれかが含まれていればマッチ
  filter_golden:
    Hashes|lookup: golden_hashes
  condition: sel and not filter_golden
```

LOLDrivers / URLhaus / MalwareBazaar 等のフィードを取り込めば、
ルール本体を変えずに検知を活性化できます。

### Windows-GNU ビルド対応
mimalloc v3 依存を外し、MinGW + rustup の組み合わせで `cargo build` が
通るようにしました (MSVC ツールチェインなしでビルド可能)。

## 同梱ルール

`rules-custom/` に 9 本の高精度ルールを同梱。FY26 セキュリティ態勢成熟度
モデルの「Active Defense」を支える検知:

| ルール | 重要度 | 検知対象 |
|---|---|---|
| `hayfx_lsass_comsvcs_minidump.yml` | critical | LSASS ダンプ (comsvcs.dll, MiniDump) |
| `hayfx_service_install_userwritable_path.yml` | high | ユーザー書込可能パスへのサービス設置 |
| `hayfx_amsi_patch_triad.yml` | high | PowerShell AMSI バイパス (3 トークン一致) |
| `hayfx_certutil_remote_fetch.yml` | critical | certutil LOLBIN によるリモート取得 |
| `hayfx_af_wevtutil_clear.yml` | high | wevtutil でのイベントログ消去 |
| `hayfx_af_eventlog_service_tamper.yml` | critical | EventLog サービス停止 |
| `hayfx_af_vss_shadow_deletion.yml` | critical | VSS / シャドウコピー削除 (ランサム前兆) |
| `hayfx_af_audit_policy_weakened.yml` | high | 監査ポリシ Success/Failure 除去 |
| `hayfx_lookup_loldriver_load.yml` | critical | LOLDriver ロード (lookup 拡張使用) |

`correlate:` 拡張依存の追加ルール 2 本 (`hayfx_wmi_persistence_*.yml`,
`hayfx_anti_forensics_clear_then_change.yml`) も保留として置いています。
こちらは Rust エンジンに `correlate:` 評価器を実装するステップ 4 以降で
活性化します。

詳細と PoC コマンドは [rules-custom/README.md](rules-custom/README.md) 参照。

## ディレクトリ構成

| パス | 役割 |
|---|---|
| [engine/](engine/) | Hayabusa Rust 本体 (fork + `lookup:` 拡張) |
| [gui/](gui/) | Python 製ローカル GUI |
| `gui/server.py` | HTTP サーバ (標準ライブラリのみ、外部依存ゼロ) |
| `gui/store.py` | SQLite 結果ストア (検知一覧・TP/FP・抑制・ハント) |
| `gui/process_tree.py` | プロセスツリー再構築ロジック |
| `gui/rule_index.py` | RuleID から YAML 逆引き |
| `gui/static/` | フロントエンド一式 (HTML / CSS / JS、ビルドステップなし) |
| [rules-custom/](rules-custom/) | 自作 Sigma ルール |
| [lookups/](lookups/) | IoC / 許可リストのサンプル |
| `suppressions/` | 抑制ルールスナップショット (Git で履歴管理可能) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | プラットフォーム設計書 (オフライン版、30 章) |
| [start.ps1](start.ps1) | ランチャ (Windows PowerShell) |

ビルド成果物・実行時データは `.gitignore` で除外:
- `bin/` (Hayabusa 公式 zip の展開先、または自前ビルドの配置先)
- `engine/target/` (Rust ビルド成果物)
- `workspace/` (各スキャンの SQLite / JSONL / アップロード EVTX)
- `logs/`、`lookups/fp_history/` 等

## セットアップ

### 必要なもの
- **Windows 10/11** (Linux/Mac でも GUI は動くが、ライブ解析機能は Windows 限定)
- **Python 3.9+** (`PATH` に通っていること)
- **Hayabusa バイナリ** (どちらか):
  - 公式 release zip (`hayabusa-3.x.x-win-x64.zip`) を `bin/` に展開
  - または `engine/` を `cargo build --release` してビルド (`engine/target/release/hayabusa.exe`)

### 手順

```powershell
# 1. clone
git clone https://github.com/Assy2005/hayabusa-plus.git
cd hayabusa-plus

# 2. Hayabusa バイナリを配置 (どちらか)
#    a) 公式 zip 展開:
#       https://github.com/Yamato-Security/hayabusa/releases から
#       hayabusa-3.x.x-win-x64.zip を取得して bin/ に展開
#       → bin/hayabusa-3.x.x-win-x64.exe, bin/rules/, bin/config/ が並ぶ
#
#    b) 自前ビルド (lookup 拡張を使いたい場合):
#       cd engine
#       cargo build --release
#       Copy-Item target\release\hayabusa.exe ..\bin\hayabusa-fx-3.10.0.exe
#       cd ..

# 3. 自作カスタムルールを Hayabusa の rules ツリーへ反映
mkdir bin\rules\hayabusa\custom -ErrorAction SilentlyContinue
Copy-Item rules-custom\*.yml bin\rules\hayabusa\custom\

# 4. GUI 起動
.\start.ps1
```

ブラウザが `http://127.0.0.1:8787` で開きます。ポートを変えたいときは
`$env:HAYABUSA_GUI_PORT = "9000"` を設定してから起動。

### Rust 自前ビルドが必要なケース

- `lookup:` 拡張を使いたいとき (公式バイナリには未取り込み)
- mimalloc を外した Windows-GNU 対応版を使いたいとき

ビルド済みバイナリは Git リポジトリには含めていません。各自ビルドするか、
将来 GitHub Release で配布される予定です。

## 「このパソコンを検査」機能

Windows でブラウザを **管理者として起動した PowerShell** から立ち上げると、
`System32\winevt\Logs` 配下のログにアクセスできます。スキャンタブの
「このパソコンを検査」カードで以下が可能:

- **このパソコンをスキャン**: Hayabusa の `-l` モードで全 EVTX を直接解析
- **EVTX を取り込む**: 重要 9 チャネル (Security / System / Application /
  Sysmon / PowerShell / Defender / WMI / CodeIntegrity / BITS) を
  `workspace/uploads/system-snapshot/` にコピー (後で何度でも再解析可能)
- **チャネル選択**: 全 ~200 チャネルから個別選択

管理者でない場合は警告表示。読み取り可能なチャネル (Application 等)
だけならスキャン可能です。

## セキュリティに関する注意

- localhost (127.0.0.1) のみで listen。**外部に晒さない**でください
- 認証なし、シングルユーザ前提
- ライブ解析 (`-l`) は管理者権限が必要。GUI は明示的なチェックボックス
  操作を要求し、暗黙では有効化しません
- アップロードされたファイル名は `^[A-Za-z0-9._-]+$` で検証、パスは
  `workspace/` 配下に限定 (パストラバーサル防止)
- Hayabusa CLI 引数は GUI 側のホワイトリストから組み立て。ブラウザから
  任意のフラグを差し込むことは不可能

## upstream との同期

このリポジトリは [Yamato-Security/hayabusa](https://github.com/Yamato-Security/hayabusa) の fork です。
upstream リモートが登録されているので、本家更新を取り込めます:

```bash
git fetch upstream
git log --oneline main..upstream/main -- 'engine/**'   # 差分確認

# エンジン側だけ取り込みたいときは個別ファイル単位で:
git show upstream/main:src/foo.rs > engine/src/foo.rs
```

## 設計思想

詳細は [ARCHITECTURE.md](ARCHITECTURE.md) を参照。要点:

1. **オフライン専用 / 常駐しない** — エンドポイント常駐型 EDR ではなく、
   収集された EVTX に対する DFIR 解析ワークベンチ
2. **収集と解析の責任分離** — ログの集め方は WEC・Sysmon・MDM の責任、
   本プラットフォームは「来たログから最大限を絞り出す」ことに集中
3. **沈黙も読む** — リアルタイム検知ができない代わり、収集されたログの
   **時系列ギャップ** や **EID 比率の異常** を事後解析で検知 (ARCHITECTURE
   §4.1 参照、ステップ 5 で実装予定)
4. **多重化が勝つ** — 攻撃者は自分が触れた場所しか消せない。Sysmon は
   別ドライバ、WEC は別ホスト、ETW は別カーネルセッション
5. **再現性** — 同じ EVTX + 同じルールセット + 同じバージョン = ビットレベル
   同一の出力

## ロードマップ

[Sec態勢成熟度モデル](https://www.example.invalid/) の Active Defense
(FY26 目標) と Intelligence (中長期) を志向します。

| ステータス | 機能 |
|---|---|
| ✅ | ステップ 1: スレットハンティング検索 UI |
| ✅ | ステップ 2: プロセスツリー可視化 |
| ⏳ | ステップ 3: 振舞い検知 (gap / rate analysis) |
| ⏳ | ステップ 4: IoC フィード自動取込 (LOLDrivers / URLhaus / MalwareBazaar) |
| ⏳ | ステップ 5: ホスト資産ビュー |
| ⏳ | ステップ 6: アラート分析の高度化 (週次レポート / ヒートマップ) |
| ⏳ | `correlate:` Sigma 拡張 (Rust 側、シーケンス相関) |
| ⏳ | `behavioral:` Sigma 拡張 (Rust 側、レート異常検知) |

## ライセンス

- `engine/` 配下: 上流 Hayabusa の [GPL-3.0](engine/LICENSE.txt) を継承
- それ以外 (gui / rules-custom / docs): 同じく GPL-3.0 とします

## 謝辞

- [Yamato Security](https://github.com/Yamato-Security/) — Hayabusa 本体
- [SigmaHQ](https://github.com/SigmaHQ/sigma) — Sigma ルール仕様
- [LOLDrivers](https://www.loldrivers.io/) — 脆弱ドライバフィード
- [MITRE ATT&CK](https://attack.mitre.org/) — 戦術・技術分類
