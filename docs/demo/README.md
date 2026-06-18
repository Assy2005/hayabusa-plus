# デモ動画

`hayabusa-plus-demo.mp4` — 実際の GUI を操作して撮影した説明字幕つきデモ
(1920×1080 / 約 38 秒 / 音声なし)。

発表の「デモ」枠で流す保険、README や配布用の紹介に使う。

## 流れ (字幕つき)

1. ホーム — 3 ステップ案内
2. STEP1 スキャン — サンプル EVTX を選んで実行
3. 解析中 — 進捗を % で表示
4. STEP2 全体ビュー — ダッシュボードで俯瞰
5. STEP3 中身を日本語で読む — 検知の「なにを検知/次にすべきこと」
6. パソコン別の危険度ランキング
7. さがす (横断検索)
8. 検出ルールと外部リスト照合 (loldrivers.io 等)

## 作り直し方

```bash
# 1) GUI サーバを起動 (別ターミナル)
python gui/server.py            # → http://127.0.0.1:8787

# 2) フレーム撮影 + 字幕焼き込み (Selenium + Pillow)
python docs/demo/make_demo.py   # → docs/demo/frames/*.png

# 3) MP4 へ合成 (ffmpeg)
#    ※ 各シーンの尺は make_demo.py / 下記コマンドで調整
```

撮影は実データ (workspace の DB) を使う。手順 2 ではサンプル EVTX を
1 本スキャンするが、その一時ジョブは撮影後に自動削除される。
`frames/` は中間生成物なので git 管理対象外 (.gitignore)。
