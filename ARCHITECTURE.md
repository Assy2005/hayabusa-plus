# Hayabusa-Forensic — Offline DFIR Detection Platform

> 設計対象を **オフライン／オンデマンド型** に絞った版。常駐ETWエージェント、
> ユーザランドプローブ、サービス常駐は本ドキュメントの設計範囲から除外する。
> Hayabusa の現行モデル（EVTX を後追いで解析する Sigma 互換スキャナ）を出発点に、
> エンタープライズ規模の **DFIR / インシデント調査ワークベンチ** として
> 拡張する。
>
> 想定読者: 上級 Windows 検知エンジニア、DFIR チームリード、SOC アナリスト。

---

## 0. スコープ宣言

### やる
- 収集済み EVTX（業務 PC、メンバーサーバ、DC、AAD-joined 端末から定期/手動で
  集めたもの）を **大量・高速・反復的** に解析する
- Sigma 互換 + 独自拡張（相関、行動、スコア）を用いた **詳細な検知**
- 高品質なルール開発を支える **検知エンジニアリングプレーン**（AI 補助生成、
  リプレイテスト、FP スコアリング、ATT&CK 自動マッピング）
- 既に GUI として動いている **ローカル Web コンソール** を一次成果物とし、
  チーム共有が必要になればコレクタ機能を追加する

### やらない（明示的に除外）
- ETW 実時間セッション
- 常駐 Windows サービス
- ユーザランドプローブ DLL の注入
- カーネルドライバ
- 連続メモリスキャン
- リアルタイムアラート配信

### この絞り込みで得られるもの
- 実装規模が **大幅に縮小**（カーネル/常駐の最も複雑な部分が消える）
- 攻撃者からのテレメトリ妨害は **「収集パイプライン側」の問題** となり、
  本プラットフォームは「集まったログから何を見抜けるか」に集中できる
- 検知品質・ルールカバレッジ・分析体験に投資を集中できる

### 失うもの（正直に明記）
- 攻撃の **進行中** には気付けない（収集と転送のラグぶん）
- ホスト上で完結する改ざん（ETW パッチ、AMSI パッチ）は **痕跡を残してくれた場合にのみ** 検知できる
- 「リアルタイム EDR」とは別カテゴリの製品である。EDR の代替ではない

---

## 1. アーキテクチャ全体

```
┌────────────── 収集側（本設計の範囲外、参考）──────────────┐
│  WEC (Windows Event Collector) / Sysmon → EVTX  もしくは     │
│  既存 SIEM からの定期エクスポート / IR 時のオフライン採取    │
└────────────────────────┬─────────────────────────────────────┘
                         ▼
              ┌───── 共通 EVTX レポジトリ ─────┐
              │  workspace/uploads/             │
              │  共有 NAS, S3, MinIO, 等        │
              └────────────────┬────────────────┘
                               ▼
┌────────── 解析ワークベンチ（本設計の主体）──────────┐
│                                                      │
│  GUI (localhost web)  ──┐                            │
│  CLI (hayabusa-fx)    ──┼──► Detection Core (Hayabusa fork) │
│  CI / バッチ           ──┘    ・Sigma matcher        │
│                                ・Correlate engine    │
│                                ・Score engine        │
│                                ・AI ルール補助       │
│                                                      │
│                          ▼                           │
│         検知結果ストア (SQLite + JSONL 永続)         │
│                          │                           │
│           ┌──────────────┼──────────────┐            │
│           ▼              ▼              ▼            │
│       ブラウザ UI    JSON エクスポート  SIEM 連携    │
└──────────────────────────────────────────────────────┘
```

**重要**: 単一プロセス、バッチ実行モデル。スキャンの起点は常に「人間 or
スケジューラがジョブを投げる」。常駐しない。

---

## 2. 検知哲学（オフライン版）

1. **収集の責任は分離する**。本プラットフォームは「来たログから最大限を絞り
   出す」もの。「ログをいかに集めるか」は別レイヤ（WEC, Sysmon 配布, Defender
   Audit ポリシ）の問題と切り分ける。
2. **「沈黙」も読みに行く**。リアルタイム検知ができない代わり、収集された
   ログの **時系列ギャップ** や **EventID 比率の異常** をオフラインで分析する
   ことで、ETW 改ざんや Sysmon 停止を事後検出する。
3. **Sigma は共通語**。すべての検知は Sigma 形式で記述。独自拡張は Sigma の
   後方互換を壊さない形でフィールド追加する。
4. **再現性が最優先**。同じ EVTX + 同じルールセット + 同じバージョンで、いつ
   回しても同じ結果。AI 補助で生成したルールも乱数を入れない。
5. **攻撃者目線のバイパス節を必ず付ける**。各ルールに「これはどう回避できるか」
   を必須メタデータとして書く。回避コストが低いルールはスコア減点。

---

## 3. テレメトリ設計（収集側に対する要件のまとめ）

本プラットフォームは収集しないが、**何が解析できるか** はソースの構成に依存
するので「収集側へ要求する EVTX チャネル」を明文化する。

| チャネル | 取れる検知 | 攻撃者からの妨害 | 重要度 |
|---|---|---|---|
| Security | 4624/4625 logon, 4688 process, 4672 priv, 4697 service, 4698/4702 task, 4720 account, 1102 clear | Audit Policy 改竄（要管理者権限） | 必須 |
| Sysmon/Operational | プロセス系統+ハッシュ、EID 8/10/22/25, パイプ、レジストリ、画像ロード | サービス停止/ドライバアンロード | 必須 |
| PowerShell/Operational (4103/4104) | スクリプトブロック内容、モジュールロード | ScriptBlockLogging 無効化、v2 ダウングレード | 必須 |
| WMI-Activity/Operational (5857-5861) | フィルタ/コンシューマ作成 | 直接WMI/COM 経由でログ抜け | 強推奨 |
| Microsoft-Windows-Eventlog (104/1102) | ログクリア検知 | サービス kill | 必須 |
| TaskScheduler/Operational | スケジュールタスク作成/変更 | TS イベントログ無効化 | 強推奨 |
| CodeIntegrity (3023/3033) | 未署名ドライバロード | HVCI 無効環境では出ない | 推奨 |
| AppLocker/MSI/Script | ブロック/許可、スクリプトホスト挙動 | AppLocker 未デプロイ | 推奨（あれば強力） |

**EID と Channel のホワイトリストは `bin/rules/config/target_event_IDs.txt` を
そのまま継承**。Hayabusa の高速化ロジックがそのまま効く。

### 補助: メモリダンプ・ハッシュリスト

EVTX 以外で受け取れる入力:

- **メモリダンプ（任意）**: IR 時に採取された `.dmp` / `.raw`。volatility3 や
  MemProcFS を外部実行し、結果（プロセス一覧、注入痕、SSDT 差分）を JSON 化
  して取り込む。本プラットフォーム自体はダンプ解析しない。
- **既知良/悪ハッシュリスト**: 自社の golden image SHA-256 や脅威インテル
  ハッシュ。Sigma 拡張の `lookup:` から参照する（§8 参照）。
- **LOLDrivers / LOLBAS フィード**: 既知の脆弱ドライバ・LOLBIN リストの定期
  取り込み。

---

## 4. アンチエヴェイジョン設計（オフライン版）

ライブ検知でないため、攻撃側がローカルでログを消した結果は「我々から見える
範囲」では既に手遅れ。代わりに **収集された EVTX 群の中で、攻撃者が消し残し
た／消せなかった証跡** を最大化する戦略を取る。

### 4.1 沈黙の検出（ギャップ分析）

オフライン解析の強みを活かし、各ホストの各チャネルにおける **時系列 EID
レート** をプロファイルし、平常値からの逸脱を検知する。

- 例: ホスト H が稼働している（Security 4624 ログオンあり）にもかかわらず、
  Sysmon EID 1 が窓 W で **平常 mean − 3σ** より少ない → `silent_host_sysmon`
- 例: 連続 5 分間 EID 4688 がゼロだが、ネットワーク関連ログ（DNS/3）は
  存在 → `audit_disabled_window`

これは Hayabusa 本体には無い機能で、§8 の `behavioral:` ブロックで定義する。

### 4.2 改ざん行為そのもの

- `eventlog_cleared` (Security 1102 / System 104)
- `audit_policy_changed` (Security 4719)
- `sysmon_service_stopped` (System 7036 with name="Sysmon64")
- `driver_unloaded_security_relevant` (System 7045 + Sysmon EID 6)

### 4.3 ログのつじつま合わせ

- プロセス開始イベントが欠落しているのに「子プロセス」だけ存在
  → 4688/Sysmon 1 抑止の痕跡として meta-rule で検知
- ファイル削除（Sysmon EID 23）が無いのに不在のファイルへの参照が残る

---

## 5. パフォーマンス設計（バッチスキャン版）

予算は **「常駐の CPU/RSS」** ではなく **「スキャンスループット」** で取る。

| メトリック | 目標 |
|---|---|
| 単一ホスト 1 日分（~200 MB EVTX）の解析時間 | < 8 秒（8 コア機） |
| 100 ホスト × 7 日（~140 GB EVTX）並列スキャン時間 | < 30 分 |
| ピーク RSS（4 並列 worker 時） | < 1.5 GB |
| ルール読み込み時間（cold） | < 600 ms |
| ルール読み込み時間（warm; bincode キャッシュ） | < 40 ms |

最適化方針:

- Hayabusa の **aho-corasick トークンプリフィルタ** と
  **(Channel, EID) → ルール集合** ディスパッチをそのまま活用
- ルールセットをコンパイル後 `bincode` でディスクキャッシュ
- EVTX 並列度は `min(cores, file_count)`。1ファイル内はシングルスレッド
  （evtx クレートの設計上の制約）
- 検知結果は **JSONL ストリーミング書き込み** + SQLite インデックス併用。
  GB 級結果でもプロセス RSS は線形に増えない設計

---

## 6. 検知パイプライン

```
[EVTX ファイル群]
       │
       ▼
[Job Scheduler]   ─── ジョブ単位 = (target, ruleset_version, params)
       │
       ▼
[並列 EVTX Worker × N]
       │   各 worker: evtx 読込 → normalize → token prefilter → rule eval
       ▼
[Detection Stream] (JSONL)
       │
       ├──► Correlation Pass  ─── ジョブ完了後 or 並行で時系列を後追い
       ├──► Score Pass        ─── §14
       ├──► ATT&CK Enrichment
       ▼
[Result Store: SQLite (index) + JSONL (raw)]
       │
       ▼
[GUI / CLI / Export]
```

**相関は 2 パスモデル**: 1 パス目で個別検知を JSONL に書き出し、2 パス目で
時系列ソート済みの検知ストリームに対して相関ルールを評価。ライブで取りこ
ぼし無く相関を取れるので、設計が単純化される（常駐モデルの状態機械が不要）。

---

## 7. Hayabusa 改造方針

### そのまま使う
- `src/detections/rule/` — ルール読込／マッチング
- `src/yaml.rs`, `src/yaml_expand.rs` — Sigma パーサ + expand プレースホルダ
- `src/timeline/` — 既存タイムライン生成
- `src/detections/configs.rs` — チャネル・EID マップ
- 既存サブコマンド `csv-timeline`, `json-timeline`, `search`, `eid-metrics`,
  `logon-summary`, `pivot-keywords-list`

### 追加する
- `src/correlate/` — オフライン 2 パス相関（§10）
- `src/score/` — スコアリングエンジン（§14）
- `src/store/` — SQLite + JSONL の結果ストア
- `src/jobs/` — ジョブキュー（ローカル）
- `src/api/` — HTTP API（現状は Python 製の薄いラッパ。最終形は Rust 内蔵）
- `src/extensions/` — Sigma の `correlate:` / `behavioral:` / `score:` /
  `lookup:` 拡張ブロックの読込

### フォークだが慎重に変える
- `src/afterfact.rs` — 出力シンクをプラガブル化（既存 CSV/JSON/HTML に加え
  SQLite + JSONL）
- `src/detections/detection.rs` — 単発イベント評価を **ライブラリ関数** として
  切り出し、相関 2 パス目から再利用可能に

### 触らない（常駐モードを設計から外したため不要）
- ETW プロバイダ統合、サービス制御、ウォッチドッグ、ユーザランドプローブの
  全コード。これらは本ドキュメントでは扱わない。

---

## 8. Sigma 拡張

オフラインだからこそ書ける拡張に絞る。

### 8.1 `correlate:` ブロック（時系列相関）

```yaml
title: Process injection followed by LSASS access
id: 7b5a4c3d-hayfx
correlate:
  window: 5m
  by: [Computer]
  steps:
    - id: inject
      detection:
        selection:
          Channel: 'Microsoft-Windows-Sysmon/Operational'
          EventID: 8
        condition: selection
    - id: lsass
      detection:
        selection:
          Channel: 'Microsoft-Windows-Sysmon/Operational'
          EventID: 10
          TargetImage|endswith: 'lsass.exe'
          GrantedAccess|contains: ['0x1010','0x1410','0x143A']
        condition: selection
  sequence: [inject, lsass]
tags: [attack.credential_access, attack.t1003_001]
level: critical
```

オフライン 2 パスモデルなら、ソート済みの検知ストリームに対し
`O(events × rules)` で評価可能。常駐版に必要だった状態機械プールは不要。

### 8.2 `behavioral:` ブロック（ギャップ・比率検知）

オフライン解析専用。1 ジョブ内の **時系列統計** に対して評価:

```yaml
title: Sysmon silenced while host active
id: 4a3b2c1d-hayfx
behavioral:
  type: provider_gap
  source: Microsoft-Windows-Sysmon/Operational
  observed_rate: "<1/min"
  conditioned_on:
    Security.EventID 4688: ">5/min"
  window: 10m
tags: [attack.defense_evasion, attack.t1562_001]
level: high
```

実装は SQLite 上で 1 分粒度のレート集計を作り、しきい値判定をかけるだけで
よい。常駐版で必要だった「平常値の継続学習」も、IR 用途では「対象期間内の
分布から極端な偏り」を見るだけで十分なケースが多い。

### 8.3 `score:` モディファイア

```yaml
score:
  base: 75
  modifiers:
    - if: User contains 'SYSTEM' then +10
    - if: parent.Image endswith 'explorer.exe' then -5
    - if: corroborated_within(30s, ['inject_rule_id']) then +15
```

`corroborated_within` は 2 パスモデルで安価に評価できる（隣接イベントが既に
JSONL に書かれているため、SQLite で同 Computer ＋時間窓のクエリ）。

### 8.4 `lookup:` ブロック（外部リスト参照）

```yaml
lookup:
  - name: golden_image_hashes
    file: lookups/golden_hashes.txt
  - name: lol_drivers
    file: lookups/loldrivers.csv
    column: Sha256
detection:
  selection:
    Channel: 'Microsoft-Windows-Sysmon/Operational'
    EventID: 6
    Hashes|sha256|not_in: golden_image_hashes
    Hashes|sha256|in: lol_drivers
```

LOLDrivers, ハッシュリスト、IP/ドメイン IOC を Sigma にハードコードせず、
**ルールパックとは別に署名された Lookup パック** から供給する。

---

## 9. 相関エンジン（オフライン 2 パス）

```
PASS 1: per-EVTX 単発イベント検知 → JSONL (時刻昇順でソート)
        │
        ▼
PASS 2: 検知ストリームを線形走査
        ├ correlate ルール: 各ルールごとに固定サイズの sliding window で
        │  ステップ照合
        └ 結果は 新たな meta-detection として同じ JSONL に追記
```

利点:
- 状態は **ジョブの寿命だけ** 保つ。OS プロセスを跨いだ永続状態が無い
- 巨大コーパスでも メモリ使用量は `O(window × rules)` で線形外
- 並列化容易（ホスト単位、または時間範囲スライス単位で分割）

実装は `crates/hyrd-correlate/`（仮称）に隔離。Hayabusa 本体には触らない。

---

## 10. AI 補助ルール生成パイプライン

オフライン専用ワークベンチなので、ルール生成パイプラインも **完全にオフライン
で完結する** よう設計する。LLM 呼び出しは分析者のワークステーションで実行。

```
脅威レポート (PDF/HTML/MD)
   │
   ▼
[Claude / オンプレ LLM]  ← 構造化出力スキーマを強制
   │
   ▼
TTP ドラフト JSON
   {tactic, technique, observables[], required_telemetry[]}
   │
   ▼
テンプレートエンジン     ← 観測量 → field/operator/value のみ LLM 任せ
   │
   ▼
Sigma 候補 YAML
   │
   ▼
[Linter]                  ← Sigma スキーマ + 自社拡張 + 必須メタデータ
   │
   ▼
[Replay Tester]           ← 自社ベースライン EVTX コーパス × 14 日
   │
   ▼
FP レート / TP レート
   │
   ▼
[ATT&CK Mapper]           ← Mitre enterprise yaml + LLM クリーンアップ
   │
   ▼
PR / レビュー / マージ
```

### Linter 検証項目
- `level` は `informational..critical`
- `level >= medium` のルールは `falsepositives:` 必須
- `Channel`/`EventID` が §3 のホワイトリストに存在
- `tags:` に少なくとも 1 つの `attack.*` を含む
- 自社拡張（`correlate:`, `behavioral:`, `score:`, `lookup:`）の文法・参照
  整合性チェック

### Replay Tester
- 入力: 自社 golden corpus（日常業務 EVTX × 14 日 × ホスト多様性）+
  Atomic Red Team 実行記録
- 出力: 検知数 / FP 推定 / TP カバレッジ / 平均評価時間
- 閾値: 新規ルールは **0.1 alert/host/day を超えない** こと（`noisy` タグ
  付きを除く）

### ATT&CK 自動マッピング
1. 観測量からのキーワード一致（高速）
2. LLM による文脈確認
3. アナリスト最終承認

すべて offline / reproducible。乱数や温度パラメータは固定。

---

## 11. テレメトリ冗長性（オフライン版）

リアルタイム冗長化（同時並行 ETW）はもう持たない。代わりに **「収集側に
何を集めさせるか」** の冗長要求として定義する:

| 検知対象 | 一次 | 二次（沈黙時のフォールバック） |
|---|---|---|
| プロセス作成 | Sysmon EID 1 | Security 4688 |
| プロセス停止 | Sysmon EID 5 | Security 4689（要監査）|
| LSASS アクセス | Sysmon EID 10 | （直接の代替なし — `behavioral` で代替）|
| WMI 永続化 | WMI-Activity 5861 | Sysmon 19/20/21 |
| サービス作成 | System 7045 | Sysmon EID 1 + cmdline |
| スケジュールタスク | TaskScheduler/Operational | Security 4698 |
| ログクリア | Security 1102 | System 104（後追い）|

「両方が沈黙したホストは要調査」という meta-rule を §4.1 のギャップ検知で
自動的に作る。

---

## 12. 検知スコアリング（§8.3 と連動）

```
score = base
      + Σ modifiers
      + provider_confidence    # 一次ソースが存在 +5, 二次のみ -5
      + corroboration_bonus    # 同窓内の関連検知に応じて
      - fp_history             # 同ルールの FP/TP 比から
```

[0,100] にクランプ。バケット:

- 80–100: 重大、アナリスト即対応
- 50–79: 要確認、UI のキューへ
- < 50: 情報、JSONL のみ

FP 履歴は GUI から各検知に対し `TP` / `FP` ボタンで蓄積。ルールごとの履歴
ファイルとして `lookups/fp_history/<rule_id>.json` に保存。次回スキャン
時に自動で反映。

---

## 13. 信頼度モデル

3 軸を別個に持つ:

- **テレメトリ忠実度**: その検知が依拠したソースの収集状況。ジョブ単位で
  「対象ホストの該当チャネルが存在したか」を SQLite に記録し、欠落していた
  ら低スコア
- **行動特異性**: 同ルールがコーパス上で何件マッチするか（事前計算）。
  ありふれたパターンは低
- **回避コスト**: ルール作者が付けるタグ（`evasion: low|med|high`）

GUI 側で「スコア高 = ルールが優秀」なのか「スコア高 = ホストが壊れている
（沈黙系）」なのかを並列に表示する。

---

## 14. 偽陽性削減

オフラインで反復可能なので、**リプレイ駆動の FP 削減** が強い:

1. **golden corpus に対する事前 FP 推定**: 各 PR で算出、しきい値超過は
   マージブロック
2. **ホストごとの抑制リスト**: アナリストが GUI 上で「このホストの
   X ルールは抑制」をマーク → `suppressions/<host>.yml`。次回スキャン時に
   反映
3. **業務コンテキストフィルタ**: 勤務時間外、ビルドサーバ、SRE 踏み台等
   の例外を `filters/` パックで管理。ルール本体とは分離して署名
4. **再評価ジョブ**: ルール更新時、過去 30 日の検知を新ルールで再評価
   して、増減を GUI に表示

---

## 15. メモリオンリー攻撃の事後検知

オフラインでも「収集された Sysmon / ETW チャネル」に痕跡があれば検知可能:

| 手法 | 拾える痕跡 | チャネル |
|---|---|---|
| Reflective DLL | RWX 割当 + プロセスへのスレッド注入 | Sysmon 8 + 10、ETW Kernel-Memory（収集されていれば） |
| Process Hollowing | プロセス改変イベント | Sysmon 25 (`ProcessTampering`) |
| .NET in-memory load | 画像なしモジュール JIT | DotNETRuntimeRundown（収集されていれば）|
| In-memory PowerShell | 未知スクリプトブロックハッシュ | PS 4104 + 自社既知ハッシュキャッシュ |
| Memory-only malware | 自社で初見の image hash | Sysmon 1 + 自社 hash cache |

§4.1 のギャップ検知と組み合わせ、「上記チャネルが沈黙していたホスト」を
別途調査対象に挙げる。

---

## 16. ETW / AMSI 改ざんの事後検知

リアルタイムには見えないが、**「攻撃後に EVTX が手元に残れば」** 痕跡を
見つけられる:

- ETW プロバイダパッチ後は、当該プロバイダの **イベントが急に途切れる**。
  §4.1 のギャップ検知で「該当プロバイダが沈黙し、その他は活動」を抽出
- AMSI バイパスは PS 4104 内のスクリプト文字列（`AmsiUtils`,
  `amsiInitFailed`, Reflection 経由）を Sigma で拾う
- どちらも一次検知が無くても、**ETW 沈黙＋PS 4104 上での疑わしいリフレ
  クション利用** の組合せをスコア加算する `correlate:` ルールを置く

---

## 17. ダイレクトシスコール検知（ヒューリスティック）

オフライン限定での割り切り:

- ETW Kernel-Memory が **収集されているなら** RWX → 実行 → 解放の連続
  パターンを検知
- 収集されていない場合: Sysmon EID 10（LSASS アクセス）が出ているのに
  対応する CreateRemoteThread / API 呼び出しが PS / cmdline ログに
  痕跡を残していない場合に **「API 通らずに到達した」可能性をフラグ**
- いずれも `medium` 止まり。`evasion: high` タグを付けてランキング上は
  尊重する

---

## 18. カーネル攻撃の可視範囲（明示）

- ドライバ非搭載 + 常駐なし。**ライブ検知は明示的に対象外**
- 収集された **CodeIntegrity (3023/3033)** と **System 7045 (service install)**
  と **Sysmon EID 6 (driver load)** を組み合わせ、未署名/LOLDrivers ヒット
  のみ事後検知
- HVCI / CI 無効環境では大きく可視性が落ちる。GUI の「データ品質」
  パネルで明示

---

## 19. Rust クレート構成（オフライン版）

```
hayabusa-fx/
├── Cargo.toml          (workspace)
├── crates/
│   ├── fx-core/        # Hayabusa から派生したルール評価コア
│   ├── fx-extensions/  # correlate / behavioral / score / lookup パーサ
│   ├── fx-correlate/   # 2-pass 相関
│   ├── fx-store/       # SQLite + JSONL 出力
│   ├── fx-jobs/        # ローカルジョブキュー
│   ├── fx-api/         # ローカル HTTP（Python ラッパの後継）
│   ├── fx-ai-cli/      # オフライン LLM 補助
│   └── fx-bin/         # 実行ファイル
```

常駐版で必要だった `fx-sources` / `fx-runtime` / `fx-egress` は不要。

---

## 20. 検知ワークフロー例

### 20.1 LSASS ダンプ（comsvcs.dll 経由）
1. Sysmon EID 1 が `rundll32.exe comsvcs.dll, MiniDump …` を起動
2. token prefilter が `comsvcs.dll` + `MiniDump` にヒット
3. `proc_creation_win_susp_lsass_dump_comsvcs` がマッチ
4. 2 パス目: 5 秒以内に同 Computer の Sysmon EID 10 → lsass を発見
   → 相関ボーナス +15
5. スコア = 75 + 15 + provider_confidence 5 = 95 → 最優先キュー

### 20.2 WMI 永続化
1. WMI-Activity 5861（フィルタ→コンシューマ）
2. `correlate.sequence` で同 Computer 30 秒以内の 5860（サブスクリプション）
   とペア化
3. `wmi_persistence_eventfilter_to_consumer` ヒット

### 20.3 PowerShell AMSI バイパス
1. PS 4104 に `AmsiUtils` トークン
2. `hayfx_amsi_patch_signal` がマッチ
3. behavioral: 同ホスト同窓内で AMSI ETW スキャンイベントが **収集されて
   いない**（収集側構成上）または **激減** → 警報ランクアップ

---

## 21. ルール配布

オフラインで完結する。ライブ更新が不要なので構成が単純:

```
内部 hayabusa-fx-rules リポジトリ (Git)
   │
   ▼
CI (lint + replay + ATT&CK 検証 + 署名)
   │
   ▼
ルールパック tarball (`fx-rules-2026.05.18.tar.gz` + `.sig`)
   │
   ▼
社内アーティファクトストア
   │
   ▼
分析者ワークステーション (`hayabusa-fx update-rules`)
```

エンドポイントへの自動配信は不要（オフラインプラットフォームなので）。
分析者は GUI または CLI から手動更新。

---

## 22. テスト戦略

### Unit
- ルール読込ラウンドトリップ、Sigma 拡張パーサ、condition AST 評価

### Property
- `proptest` で任意イベントに対する非 panic 性

### Replay
- 200 GB 規模の golden corpus + Atomic Red Team 録画を `cargo test
  --features replay-corpus` で実行
- PR ごとに「TP 増加 / FP 増加」差分を表示

### 一貫性
- 同じ EVTX + 同じルールセット + 同じバージョン → ビットレベル同一の出力
  （タイムスタンプを含む再現性）

リアルタイム性能の継続計測（常駐版で必要だった `--detect-only` シャドー
モード）は不要。

---

## 23. 配布形態

- **GUI 版**（現状）: Python 製ラッパ + Hayabusa バイナリ + 静的 SPA。
  単一フォルダ展開で動作。社内 IR チーム員のラップトップに配布
- **CLI 版**: 既存 `hayabusa.exe` をそのまま使う。CI / バッチに統合
- **コレクタ拡張**（任意・後日）: 共有結果ストア（PostgreSQL or 単一
  サーバ上の SQLite）を持ち、複数アナリストが結果を共有

エンドポイント常駐ソフトウェアは存在しない。

---

## 24. ロードマップ（オフライン版に絞った後の現実的順序）

1. **済**: GUI ラッパ（このリポジトリ）
2. **次**: SQLite ベースの結果ストアと検知一覧の永続化、TP/FP ボタン
3. **次**: `correlate:` ブロックの最小実装（2 パスモデル、`sequence` のみ）
4. **次**: `behavioral.provider_gap` の最小実装
5. **次**: `lookup:` ブロック（外部 CSV/TXT 参照）
6. **次**: 抑制リスト + フィルタパック
7. **次**: AI 補助ルール生成パイプライン（オフライン LLM 連携）
8. **後**: 共有コレクタ（必要であれば）

各ステップは独立に出荷可能。常駐エージェントを諦めたぶん、検知エンジニア
リング機能の充実に投資できる。

---

## 25. 失ったものを取り戻すための補助策

リアルタイム検知を捨てた以上、「収集とアラートの遅延」をどう許容するかを
明記する:

- 収集間隔の **目標 SLA**: WEC で 5 分未満、IR 採取で「事後」と割り切る
- 重大検知（critical）が出た場合の **手動エスカレーションパス** を SOC
  ランブックに明記
- **定期スキャンジョブ** を `schedule` 機能で 1 時間ごとに走らせ、「最新
  EVTX を引いてきて自動スキャン」を運用ワークフローに組み込む
- それでも見えないリアルタイム侵害については、別系統の EDR / NDR と
  併用する前提を **公式に文書化**（責任範囲を曖昧にしない）

---

*以上が、常駐動作を除外した本プラットフォームの設計範囲。実装ロードマップ
の詳細マイルストン・CI 構成・スプリント計画は `docs/roadmap.md` に分離して
記述する（実装着手時に作成）。*
