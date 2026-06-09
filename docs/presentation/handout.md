# 🦅 hayabusa-plus — 配布用 1 ページサマリ

> **Hayabusa を拡張した、ブラウザで使う DFIR 解析プラットフォーム**
> EVTX を投げ込むだけで Sigma 検知 + IoC 照合 + 攻撃の系統再構築 + 異常パターン抽出。
>
> 🔗 https://github.com/Assy2005/hayabusa-plus

---

## 何の道具?

Windows のイベントログ (EVTX) を解析して攻撃の痕跡を見つけ、その意味と次にすべきことを
**ブラウザで見られる** ようにしたツールです。**ローカル完結** (外部送信なし)、
**外部依存ゼロ** (Python があれば動く)、**OSS** (GPL-3.0)。

---

## 6 つの主要機能

| # | 機能 | 一言で |
|---|---|---|
| 1 | **EVTX ブラウザ解析** | ドロップ&ドロップ、リアルタイム検知ストリーム |
| 2 | **スレットハンティング** | 多軸絞り込み、6 個の仮説プリセット、5 種のピボット |
| 3 | **プロセスツリー再構築** | Sysmon EID 1 から親子関係を可視化、focal をハイライト |
| 4 | **振舞い異常検知** | バースト・拡散・沈黙・時間外 — Sigma が苦手な領域 |
| 5 | **IoC フィード自動取込** | LOLDrivers / abuse.ch、8 万件超を 1 行 YAML で参照 |
| 6 | **ホスト資産ビュー** | リスクスコア順、TP/FP 補正、直近度補正 |

---

## なぜ作ったか

- 既存の Hayabusa CLI は強力だが、結果が **巨大な CSV/JSON** で運用が辛い
- 「**このホスト、危ないの?**」「**この検知、何が起きてるの?**」の即答が難しい
- 攻撃者が **ログを消した** ことに気付ける layer が必要
- IoC フィードを取り込むのに毎回ルールを書き換える運用は **持続しない**

→ Hayabusa の上に **DFIR 運用層** を被せる、という発想。

---

## 技術的な要点

| 項目 | 内容 |
|---|---|
| エンジン拡張 | **`lookup:` Sigma 拡張** (Rust 約 400 行)。外部 IoC を 1 行参照 |
| GUI | **Python 標準ライブラリのみ**。HTTP + SSE + SQLite で外部依存ゼロ |
| フロント | **Vanilla JS / SVG / 純 CSS**、ビルドステップなし |
| セキュリティ | DNS リバインド防御 / CSRF 防御 / CSP / パストラバーサル防御 |
| 同梱ルール | **11 本** (LSASS dump / 痕跡隠蔽 / lookup ベース 3 本) |
| 設計書 | ARCHITECTURE.md (**30 章 / 2,400 行**) |

---

## 数字で見る

| メトリック | 値 |
|---|---|
| 自作 Sigma ルール | **11 本** |
| 統合 IoC | **82,679 件** (4 フィード) |
| Rust 拡張 | 約 400 行 |
| Python+JS+CSS | 約 3,300 行 |
| 外部 pip / npm 依存 | **0** |
| ATT&CK 技術日本語辞書 | **30+ 種類** |

---

## 30 秒で試す

```powershell
git clone https://github.com/Assy2005/hayabusa-plus.git
cd hayabusa-plus

# Hayabusa バイナリを bin/ に展開 (公式 release zip でも自前ビルドでも OK)

python tools\fetch_feeds.py   # IoC を取得
.\start.ps1                    # ブラウザが http://127.0.0.1:8787 で開く
```

---

## 成熟度モデル対応

セキュリティ態勢成熟度モデルにおける位置づけ:

| 層 | 領域 | 状態 |
|---|---|---|
| ③ Active Defense | I. ログ監視 / 振舞い検知 / ハンティング / 検知最適化 | ✅ |
| ③ Active Defense | II. 詳細ログ解析 / フォレンジック | ✅ |
| ③ Active Defense | III. マネジメント (資産管理) | ✅ |
| ④ Intelligence | IV. OSINT / IoC | ✅ |
| ④ Intelligence | IV. 外部流出把握 | ⏳ 未着手 |

FY26 目標 **Active Defense** はほぼ全領域カバー、中長期 **Intelligence** にも踏み込み済み。

---

## 連絡先 / 貢献

- **GitHub Issues**: https://github.com/Assy2005/hayabusa-plus/issues
- **Pull Requests** 歓迎
- ライセンス: **GPL-3.0** (upstream Hayabusa を継承)

---

<sub>※ 本ツールは Yamato-Security/hayabusa の fork です。Hayabusa の素晴らしい基盤に感謝します。</sub>
