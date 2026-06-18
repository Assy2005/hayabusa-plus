# デモ動画

`hayabusa-plus-demo.mp4` — 実際に動作している GUI を録画した、説明字幕つき
デモ (1920×1080 / 約 38 秒 / 音声なし)。スクショの紙芝居ではなく、進捗バーの
伸び・検知のリアルタイム流入・グラフ描画・解説パネルの展開といった "動き" が
そのまま記録されている。

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
python gui/server.py                  # → http://127.0.0.1:8787

# 2) 録画 + 字幕合成までを一括実行
python docs/demo/make_screencast.py   # → docs/demo/hayabusa-plus-demo.mp4
```

`make_screencast.py` は Chrome DevTools Protocol (CDP) の
`Page.startScreencast` でヘッドレス Chrome の画面更新フレームをそのまま
受け取りつつ、同じ CDP 接続から JS で操作 (タブ切替・スキャン実行・検知の
展開) を流す。これで "動いている" 様子が録れる。最後に ffmpeg で、フレーム
本来のタイミングを保ったまま 30fps の MP4 にまとめ、各シーンの日本語字幕を
時間指定で重ねる。

撮影は実データ (workspace の DB) を使う。途中でサンプル EVTX を 1 本
スキャンするが、その一時ジョブは撮影後に自動削除される。中間生成物の
`_cast/` と `frames/` は git 管理対象外 (.gitignore)。

依存: `websocket-client`, `Pillow`, `ffmpeg`, Google Chrome。
