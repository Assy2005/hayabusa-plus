# 発表資料 (Presentation Materials)

このディレクトリには hayabusa-plus を発表するための資料 4 点が入っています。

## 📂 ファイル構成

| ファイル | 用途 | 想定読者 |
|---|---|---|
| [`pptx/hayabusa-plus.pptx`](pptx/hayabusa-plus.pptx) | **簡潔版 PowerPoint** (11 枚、12-15 分) | 投影画面 |
| [`pptx/build_deck.py`](pptx/build_deck.py) | 上記 .pptx を生成する python-pptx スクリプト | 編集する人 |
| [`slides.md`](slides.md) | **Marp 形式スライド** (詳細版、約 30 枚) | 投影画面 (時間 20-25 分版) |
| [`speaker_notes.md`](speaker_notes.md) | 発表者用カンペ + 想定 Q&A | 発表者本人 |
| [`demo_script.md`](demo_script.md) | デモの手順書 + 失敗時対応 | 発表者本人 |
| [`handout.md`](handout.md) | 配布用 1 ページサマリ | 聴衆 |

### どのスライド版を使うか

| 発表時間 | 推奨 |
|---|---|
| **12-15 分** (+ デモ 5 分 + Q&A 5 分) | **`pptx/hayabusa-plus.pptx`** (11 枚、圧縮版) |
| **20-25 分** | `slides.md` を Marp で PDF 化 (30 枚、詳細版) |

両方とも内容は揃えてあり、speaker_notes / demo_script はどちらにも流用可能です。

---

## 🚀 スライドの使い方

### A. **PowerPoint をそのまま使う** (推奨)

`pptx/hayabusa-plus.pptx` をダブルクリックで PowerPoint が開きます。
そのままプレゼンに使えます。色や文字を編集したい場合は通常の PowerPoint 操作で OK。

**スライドを編集して再生成したい時**:
```powershell
cd docs\presentation\pptx
python build_deck.py            # → hayabusa-plus.pptx を再生成
```

`build_deck.py` の上の方にあるカラーパレットや本文を変えれば、何度でも同じ
レイアウトのスライドを再生成できます。

### B. **Marp 詳細版** を使う

`slides.md` を:

1. VSCode に拡張機能「**Marp for VS Code**」をインストール
2. `slides.md` を VSCode で開く
3. プレビューがスライド形式で表示される
4. 右上のメニューから **PDF / PPTX / HTML にエクスポート** 可能

```
File > Export Slide Deck > Choose format
```

### C. **GitHub で Markdown として読む**

`slides.md` は GitHub 上で縦長ドキュメントとしても読めます。
内容の事前確認や、リモート参加者向けの共有用に。

---

## 🎤 当日の進め方

### 30 分前

- [ ] `start.ps1` でサーバ起動、ブラウザで `http://127.0.0.1:8787` を表示
- [ ] **Ctrl+Shift+R** でハードリロード (キャッシュクリア)
- [ ] **ステータスバーが緑**であることを確認
- [ ] 「**このパソコンを検査**」カードが **管理者権限あり** になっているか確認
- [ ] `workspace/uploads/` に **デモ用 EVTX** が 1〜2 個あるか確認
- [ ] スライドを **PDF にエクスポート** してバックアップ

### 5 分前

- [ ] 深呼吸を 3 回
- [ ] 水を演台に置く
- [ ] **`speaker_notes.md`** の Slide 1 を確認 (最初のセリフを丸暗記)

### 発表中

- [ ] スライド進行は `speaker_notes.md` を参照
- [ ] デモ中は `demo_script.md` を参照
- [ ] 想定外の質問は **「持ち帰って後ほどお答えします」** で OK

### Q&A 後

- [ ] **handout.md** を聴衆に渡す or リンクを共有
- [ ] GitHub URL (`https://github.com/Assy2005/hayabusa-plus`) を **チャットに貼る**

---

## ⏱️ 時間配分の目安

| Part | 内容 | スライド | 時間 |
|---|---|---|---|
| Intro | タイトル + アジェンダ | 1-2 | 1 分 |
| Part 1 | 何が困っていたか | 4-7 | 3 分 |
| Part 2 | 主要 6 機能 | 8-17 | 5 分 |
| **Demo** | **ライブデモ** | 18 | **5 分** |
| Part 3 | 技術詳細 | 19-24 | 4 分 |
| Part 4 | 数字と振り返り | 25-29 | 2 分 |
| まとめ | 終わりの挨拶 | 30 | (15 秒) |
| **Q&A** | | | **5 分** |
| **合計** | | | **約 25 分** |

短縮版 (10 分) でやる場合は Part 3 を割愛するとちょうど良いです。

---

## 🎨 スライドのスタイルカスタマイズ

`slides.md` の冒頭 (frontmatter) に `style:` ブロックがあります。
色を変えたい場合はそこを編集:

```yaml
style: |
  h1, h2, h3 { color: #ff5722; }   # ← アクセント色 (オレンジ)
  /* ... */
```

会社カラーに合わせたい場合は `#ff5722` を会社カラーに変えるだけ。

---

## 💡 発表後

聴衆から **GitHub Star** をもらえると嬉しい。
PR や Issue が来たら **24 時間以内に反応** することを目標に。
