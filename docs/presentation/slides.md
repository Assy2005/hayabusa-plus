---
marp: true
theme: default
size: 16:9
paginate: true
backgroundColor: #0b0d12
color: #d8def0
style: |
  section {
    font-family: -apple-system, "Segoe UI", "Hiragino Kaku Gothic ProN", sans-serif;
    background: #0b0d12;
    color: #d8def0;
  }
  h1, h2, h3 { color: #ff5722; }
  code { background: #1a1f2c; color: #ffab40; padding: 1px 6px; border-radius: 3px; }
  pre { background: #080a10; border: 1px solid #1f2533; padding: 12px; border-radius: 6px; }
  pre code { background: transparent; color: #d8def0; }
  blockquote { border-left: 3px solid #ff5722; padding-left: 12px; color: #b8c1d9; }
  strong { color: #ffab40; }
  table { border-collapse: collapse; margin: 0 auto; }
  th, td { border: 1px solid #1f2533; padding: 6px 12px; }
  th { background: #161b26; color: #b8c1d9; font-weight: 600; }
  section.title { text-align: center; }
  section.title h1 { font-size: 64px; margin-bottom: 0; }
  section.title h2 { color: #ffab40; font-weight: normal; margin-top: 8px; }
  section.section { text-align: center; }
  section.section h1 { font-size: 48px; }
  .small { font-size: 0.8em; color: #7d869c; }
  .accent { color: #ff5722; font-weight: bold; }
---

<!-- _class: title -->

# 🦅 hayabusa-plus

## Hayabusa を拡張した、ブラウザで使う DFIR 解析プラットフォーム

<br/>

Sigma 検知 + IoC フィード + 攻撃系統再構築 + 振舞い異常検知 を**一画面で**

<br/>

<span class="small">Made with detection engineering depth, not marketing fluff.</span>

---

## 今日話すこと

1. **何が困っていたか** (5 分)
   - 既存のセキュリティログ解析の現状
   - DFIR チームが抱える課題

2. **hayabusa-plus でどう解決したか** (8 分)
   - 主要 6 機能の概要
   - **ライブデモ**

3. **技術的に何が新しいか** (5 分)
   - エンジン拡張 / 振舞い検知 / IoC 取込

4. **これから / Q&A** (2 分)

---

<!-- _class: section -->

# Part 1: 何が困っていたか

---

## まず、用語を 30 秒で

| 用語 | これは何? |
|---|---|
| **EVTX** | Windows のイベントログファイル。`.evtx` 拡張子 |
| **Sigma** | 検知ルールの **共通記法**。YAML で書く |
| **Hayabusa** | EVTX に Sigma を当てる **CLI ツール** (Rust 製、Yamato Security 製) |
| **DFIR** | **D**igital **F**orensics & **I**ncident **R**esponse。"侵害された後" の調査 |
| **IoC** | Indicator of Compromise。ハッシュ・IP・URL 等の **既知悪リスト** |

---

## 既存ツール (Hayabusa CLI 単体) でやろうとすると…

```powershell
hayabusa.exe json-timeline -d evtx_dir -o result.jsonl
```

これで **JSONL ファイル** が手元に残るが…

- **結果が CSV/JSON の山。何が何やら**
- 「**このホストはやばいの?**」と聞かれても即答できない
- 「**この検知って何が起きてるの?**」を毎回 ATT&CK サイトで調べる
- IoC フィードを取り込みたいけど **ルールを書き換える運用**
- 攻撃の **親子関係 (誰が誰を生んだか)** が分からない
- 「**いつもと違う**」(バースト・拡散) が見えない
- 攻撃者が **ログを消した** ことに気付けない

---

## 端的に言うと

> 「**強力な検知エンジン**はあるけど、**運用のための皮**が足りてない」

検知エンジンと SOC / DFIR アナリストの間には大きなギャップがあります。

<br/>

**今回の目標**: そのギャップを Web UI 1 枚で埋める。

---

<!-- _class: section -->

# Part 2: hayabusa-plus

---

## 一行で言うと

> EVTX を投げ込むだけで、Sigma 検知 + IoC フィード照合 + 攻撃の系統再構築 + 異常パターン抽出を行う **ローカル DFIR コンソール**

<br/>

特徴:

- **ローカル完結**: ブラウザだけ、外部にデータが出ない
- **外部依存ゼロ**: Python が入ってれば動く、`pip install` 不要
- **エンジンを拡張**: Rust 側に `lookup:` Sigma 拡張を追加
- **GitHub 公開**: https://github.com/Assy2005/hayabusa-plus

---

## 主な機能 (6 つ)

| # | 機能 | 何ができる |
|---|---|---|
| 1 | 🔎 **EVTX ブラウザ解析** | ドロップ&ドロップ → リアルタイム検知ストリーム |
| 2 | 🎯 **スレットハンティング** | 多軸絞り込み + 6 個の仮説プリセット |
| 3 | 🧬 **プロセスツリー再構築** | Sysmon EID 1 から親子関係を可視化 |
| 4 | 📊 **振舞い異常検知** | バースト・拡散・沈黙・時間外 |
| 5 | 🛡️ **IoC 自動取込** | LOLDrivers / abuse.ch から自動更新 |
| 6 | 🖥️ **ホスト資産ビュー** | リスクスコア順で「危ない順」一覧 |

---

## アーキテクチャ

```
┌─────────────────────┐    ┌──────────────────────┐    ┌────────────────┐
│  ブラウザ           │    │   hayabusa-plus      │    │  外部          │
│  localhost:8787    │◄──►│                      │    │                │
│                    │    │  ┌────────────────┐  │    │                │
│  Python製 GUI が    │    │  │ Hayabusa Engine│◄─┼───►│  EVTX ファイル │
│  HTTP/SSE で接続   │    │  │ (Rust + lookup) │  │    │                │
│                    │    │  └────────┬───────┘  │    │                │
│                    │    │           │          │    │                │
│                    │    │  ┌────────▼───────┐  │    │  ┌──────────┐  │
│                    │    │  │ SQLite 検知    │  │    │  │ LOLDrivers│  │
│                    │    │  │ ストア          │  │    │  │ abuse.ch  │◄─┘
│                    │    │  └────────────────┘  │    │  │ MITRE     │
│                    │    │                      │    │  └──────────┘
└─────────────────────┘    └──────────────────────┘    └────────────────┘
```

- **Engine (Rust)**: 検知本体、私たちが `lookup:` 拡張を追加
- **Store (SQLite)**: 検知結果の正規化 DB
- **GUI (Python)**: HTTP + SSE で UI に配信

---

## 機能 1: EVTX ブラウザ解析

```
┌─── スキャンタブ ────────────────────────────────────┐
│  ┌──────────────────┐  ┌──────────────────────────┐ │
│  │ 対象 (Step 1)    │  │ 設定 (Step 2)            │ │
│  │ [↓ ドロップ]     │  │ [標準][軽量][徹底]      │ │
│  │ ファイル一覧     │  │ 最小レベル: medium ▼     │ │
│  └──────────────────┘  └──────────────────────────┘ │
│  ┌──────────────────────────────────────────────────┐│
│  │ [Step 3] スキャン開始                          ││
│  └──────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

- 3 ステップ縦フロー: 対象選択 → 設定 → 実行
- 「**このパソコンを検査**」ボタン → System32\winevt\Logs を直接スキャン
- 検知は **リアルタイム** で流れる (SSE)
- 各行クリックで **解説パネル展開** (後述)

---

## 機能 2: スレットハンティング

```
プリセット: [直近24h重大] [痕跡隠蔽] [認証情報窃取] [永続化] [横展開] [最多発火]

条件:
  ホスト: WS-*           時間: 24h ▼      レベル: 🔴🟠🟡
  チャネル: System ▼    EID: 4624        自由文字列: lsass

結果: 14,244 件
  [一覧] [ルール別] [ホスト別] [時系列] [重要度別]   ← ピボット切替
```

- **6 個の仮説プリセット** (痕跡隠蔽行為・横展開兆候 等) で 1 クリック分析
- 多軸 AND 絞り込み (ホスト glob / 時間 / レベル / ルール / 自由テキスト)
- **5 種類のピボットビュー** (一覧 / ルール別 / ホスト別 / 時系列 / 重要度別)
- 結果は **CSV エクスポート** で SOC レポートに直結

---

## 機能 3: プロセスツリー再構築

```
🔴 critical  Suspicious LSASS Access via comsvcs.dll  ← 検知発生
└─ プロセスツリー (±10 分以内)
   └─ explorer.exe (focal)
       └─ powershell.exe -enc ...
           └─ rundll32.exe comsvcs.dll, MiniDump 1234   ← ハイライト
               └─ (子プロセス無し、ここで止まる)
```

- 検知時刻 **±N 分の Sysmon EID 1** を集めて親子ツリー化
- 検知のプロセスは **オレンジ枠でハイライト + 自動スクロール**
- 親 → 子 → 孫 を辿って「誰がこれを実行させたか」が即座に分かる
- 「**rundll32 で comsvcs を叩いた親は誰?**」が一目で見える

---

## 機能 4: 振舞い異常検知

Sigma が「**1 イベントを見て yes/no を出す**」のに対し、振舞い検知は「**いつもと違う**」を出す:

| 種別 | 検知条件 | 攻撃シナリオ |
|---|---|---|
| **バースト** | ルールが平常比 8 倍以上発火 | 大量 PowerShell・スキャン・brute force |
| **拡散** | 同じルールが 3 ホスト以上 | 横展開・配布スクリプト |
| **沈黙** | 通常活動するホストが 6 時間以上検知ゼロ | ログ抑止・攻撃者がログを消した |
| **時間外** | 深夜帯 (0-6時) の high/critical | 業務時間外を狙った攻撃活動 |

**実データで検出例**:
- `Potentially Malicious PwSh` が **平常の 2,492 倍** バースト → 攻撃進行のシグナル

---

## 機能 5: IoC フィード自動取込

```yaml
lookup:
  - name: loldrivers
    file: ../../../../lookups/loldrivers.txt  ← 1,924 件の悪性ハッシュ
detection:
  sel:
    Hashes|lookup: loldrivers   ← 1 行で全件照合
```

- 我々が作った **`lookup:` Sigma 拡張** で外部 IoC を 1 行参照
- **4 フィード × 82,679 件** の IoC を自動取得:
  - LOLDrivers (脆弱ドライバ SHA256)
  - MalwareBazaar (直近 24h の malware SHA256)
  - URLhaus (活動中 C2 URL)
  - Feodo Tracker (botnet C2 IP)
- GUI ボタン or `tools/fetch_feeds.py` で更新
- 取得失敗時は **既存ファイル温存** で検知継続

---

## 機能 6: ホスト資産ビュー

```
ホスト              リスク                   検知 Crit Hi
LAPTOP-CGE8F31F     [██████████████  87.7]  14,774  0  40   ← 最優先
MSEDGEWIN10         [██████          28.9]      70  0   2
WS-ALICE-01         [████            21.2]       2  1   1
WS-BOB-02           [███             18.1]       2  0   2
```

**リスクスコア** = `critical×10 + high×5 + medium×2 + low×1` を:
- TP/FP フィードバックで補正 (FP 確定で減点)
- 直近度補正 (24h 以内 ×1.5, 60 日超 ×0.7)
- log 圧縮で 0-100 に正規化

→ 「**どのホストから手をつけるべきか**」が**一目**で分かる

---

<!-- _class: section -->

# ライブデモ

(画面切替: ブラウザ → http://127.0.0.1:8787)

---

## デモの流れ (5 分)

1. **スキャンタブ**: EVTX をドロップ → ライブフィードを見せる (1 分)
2. **検知をクリック**: 解説パネル展開、ATT&CK 日本語表示 (1 分)
3. **プロセスツリー**: 親子関係を遡る (30 秒)
4. **ハントタブ**: プリセット「痕跡隠蔽」→ ピボット (1 分)
5. **ダッシュボード**: 振舞い異常カード、バースト検出 (1 分)
6. **ホストタブ**: リスクスコア順、詳細展開 (30 秒)

---

<!-- _class: section -->

# Part 3: 技術的に何が新しいか

---

## (1) `lookup:` Sigma 拡張

upstream Hayabusa に **新しい Sigma 構文** を追加:

```yaml
lookup:                       # ← 新ブロック
  - name: lol_drivers
    file: ../../../lookups/loldrivers.txt
detection:
  sel:
    Channel: 'Microsoft-Windows-Sysmon/Operational'
    EventID: 6
    Hashes|lookup: lol_drivers   # ← 新パイプ修飾子
  condition: sel
```

**実装**:
- `engine/src/detections/rule/lookup.rs` (新規)
- `engine/src/detections/rule/matchers.rs` に `PipeElement::Lookup` 追加
- 起動時に lookup ファイルを `RwLock<HashMap>` にロード、O(1) 検索

将来 upstream に PR 投稿予定。

---

## (2) 振舞い異常検知 (Python 製)

```python
# gui/behavioral.py
def _burst(conn):
    # 平常レート (fires / time-span hours) を計算
    baseline = total_fires / span_hours
    # 1 時間バケットで集計
    for bucket in hourly_buckets:
        if bucket.count >= 8 * baseline:
            yield anomaly(kind="burst", ratio=bucket.count / baseline)
```

**4 種類のアナライザ** が SQL 集計だけで動作:
- pure-Python、外部依存なし
- 既存検知データだけで完結 (raw EVTX 再パース不要)
- 実データで **2,492 倍バースト** 等を検出済み

---

## (3) ホストリスクスコア

```
weighted = critical×10 + high×5 + medium×2 + low×1
scaled   = weighted × tp_factor × recency_factor
display  = clip(0..100, 20 × log10(1 + scaled))
```

**補正の意味**:
- `tp_factor`: TP 確定で +5%, FP 確定で -5% → アナリストの判断を反映
- `recency_factor`: 24h 以内なら ×1.5 → 活動中の脅威を優先
- log 圧縮: 1000 件と 10 件のホストを **視覚的に比較可能**にする

「**完璧ではないが、十分に意味のある優先順位**」を狙った設計。

---

## (4) セキュリティ自己防衛

ローカル DFIR ツールとはいえ、**ブラウザ経由攻撃**の余地は塞ぐ:

| 防御 | 効果 |
|---|---|
| **DNS リバインド** ガード | `Host` ヘッダ検証、外部ドメイン経由攻撃を 421 拒否 |
| **CSRF** ガード | POST/DELETE は `Origin`/`Referer` localhost 必須、403 拒否 |
| **クリックジャッキング** | `X-Frame-Options: DENY` |
| **MIME sniffing** | `X-Content-Type-Options: nosniff` |
| **CSP** | `default-src 'self'`, 外部リソースロード禁止 |
| **パストラバーサル** | アップロード/参照パスを `workspace/` 配下に限定 |

ローカルツールでも「**他タブが localhost を悪用**」のシナリオを潰した。

---

<!-- _class: section -->

# Part 4: 数字と振り返り

---

## 数字で見る hayabusa-plus

| メトリック | 値 |
|---|---|
| 自作 Sigma ルール | **11 本** (critical 5, high 5, experimental 1) |
| エンジン拡張 LoC (Rust) | 約 **400 行** |
| GUI コード LoC (Python+JS+CSS) | 約 **3,300 行** |
| 外部 pip / npm 依存 | **0** |
| 統合 IoC フィード | **4** (合計 **82,679 件** の IoC) |
| 検知データの保管 | SQLite + 元 JSONL の二重保管 |
| 対応した攻撃手法 (ATT&CK 技術) | **30+ 種類** を日本語解説辞書化 |
| 設計書 (ARCHITECTURE.md) | **30 章 / 約 2,400 行** |

---

## Before / After

| 観点 | Hayabusa CLI 単体 | hayabusa-plus |
|---|---|---|
| 結果の見方 | 巨大な CSV/JSON を Excel で開く | ブラウザで多軸絞り込み + ピボット |
| 検知の理解 | 自分で ATT&CK を調べる | クリックで日本語解説 + 次手 |
| 親子関係 | 手で grep して並べる | プロセスツリー自動構築 |
| いつもと違う | 検出不可 | バースト/拡散/沈黙 を自動抽出 |
| IoC 照合 | 都度ルール書き換え | 1 行で参照 + フィード自動更新 |
| ホスト優先順位 | 自分で集計 | リスクスコア順で一覧 |
| 攻撃者がログを消した | 気付かない | 「沈黙」検知 + 痕跡隠蔽ルール 5 本 |

---

## セキュリティ態勢成熟度モデルとの対応

```
                                    │
④ Intelligence  (中長期目標)        │  ✅ IV. OSINT / IoC (lookup + 4 feeds)
                                    │
                                    │
③ Active Defense (FY26 目標)        │  ✅ I. 振舞い検知 (バースト/拡散/沈黙/時間外)
                                    │  ✅ I. スレットハンティング
                                    │  ✅ I. 検知ルール最適化 (TP/FP/抑制)
                                    │  ✅ II. 詳細ログ解析 (検知解説パネル)
                                    │  ✅ II. フォレンジック (プロセスツリー)
                                    │  ✅ III. マネジメント (ホスト資産ビュー)
                                    │
                                    │
② Passive Defense                   │  (既存 Sigma で対応)
                                    │
① Architecture                      │  (対象外)
```

**FY26 Active Defense はほぼ全領域カバー**、中長期 Intelligence にも踏み込み済み。

---

## 開発の振り返り

**意識したこと**:

- **外部依存ゼロ**: Python 標準ライブラリのみ。`pip install` 不要、誰でも `git clone` で動かせる
- **UI は壊れにくく**: 標準ライブラリの SVG / vanilla JS、フレームワーク無し
- **エンジン側は最小改造**: upstream に PR できる粒度の変更だけ
- **設計書を先に書く**: ARCHITECTURE.md 30 章を **コード書く前に** 書いた
- **誤検知の前提**: TP/FP / 抑制 / リスクスコア補正で**運用ノイズ**に立ち向かう

**学んだこと**:

- 「**画面を作る → 業務がはじめて意味を持つ**」
- DFIR ツールは「**沈黙を読める**」ことが本質的に重要
- Sigma は強力だが、**集合の異常**を見る層はもう一つ必要

---

## これから

| 状態 | 機能 |
|---|---|
| ✅ | 10 ステップ完了 (基本ハンティング → ホスト資産まで) |
| ⏳ | アラート分析の高度化 (週次レポート / ヒートマップ) |
| ⏳ | `correlate:` Sigma 拡張 (時系列相関、Rust) |
| ⏳ | `behavioral:` Sigma 拡張 (ルートレベルでレート異常を書ける) |
| ⏳ | AI 補助ルール生成 (脅威レポート → Sigma 半自動) |
| ⏳ | 集合ホスト比較ビュー |
| ⏳ | 真のギャップ分析 (`hayabusa eid-metrics` 統合) |

---

<!-- _class: title -->

# ありがとうございました

<br/>

**GitHub**: https://github.com/Assy2005/hayabusa-plus

**設計書**: `ARCHITECTURE.md` (30 章)

<br/>

質問・フィードバック・PR お待ちしています 🦅

---

## 参考: 起動の仕方 (おまけ)

```powershell
# 1. clone
git clone https://github.com/Assy2005/hayabusa-plus.git
cd hayabusa-plus

# 2. Hayabusa バイナリ取得 (公式 release zip を bin/ に展開)
# または engine/ で cargo build --release

# 3. IoC フィードを取得
python tools/fetch_feeds.py

# 4. 起動
.\start.ps1
```

→ ブラウザが `http://127.0.0.1:8787` で開く。
