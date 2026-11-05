# 新しい検知ルールの動作確認用 EVTX

2026年に追加した検知ルールを確認するための合成 EVTX です。
実端末のログではなく、イベント構造だけを再現したテストフィクスチャです。

## ファイル

| ファイル | 用途 |
|---|---|
| `hayfx-2026-detections.evtx` | 12個の検知対象イベントを収録。新しいルールがすべて発火することを確認する |
| `hayfx-negative-control.evtx` | 正常系のイベントのみ。新しいルールが発火しないことを確認する |
| `source/*.xml` | EVTX の元になった Event XML（再生成・レビュー用） |

## GUI での確認

1. 「スキャン」タブを開く
2. `hayfx-2026-detections.evtx` をドロップ
3. プリセット「標準」のままスキャン
4. 「結果」タブで以下が表示されることを確認

期待値: **12イベント / 12検知**

| EventRecordID | ルール | レベル |
|---:|---|---|
| 1001 | ClickFix Run Dialog Command With Remote Retrieval | high |
| 1002 | ClickFix-style pcalua Proxy Execution | high |
| 1003 | Explorer Or Terminal Spawns Network-Capable Interpreter | high |
| 1004 | Conhost Headless Shell Launch | medium |
| 1005 | Suspicious RMM Deployment Or Execution | high |
| 1006 | Windows Defender Exclusion Or Tamper Registry Change | high |
| 1007 | WMI Remote Command Execution Output To ADMIN Share | high |
| 1008 | Rclone Copy Or Sync To Remote Storage | medium |
| 1009 | Browser Credential Database Copy Via Esentutl | medium |
| 1010 | Cloudflared Masquerading As Svchost | high |
| 1011 | Kernel Driver Loaded From User-Writable Path | medium |
| 1012 | Audit Policy Cleared Or Removed Via Auditpol | high |

`hayfx-negative-control.evtx` は **0検知** が期待値です。
通常の notepad、svchost、NTFS ドライバ、ローカル rclone、通常の auditpol などを含みます。

## CLI での確認

```powershell
.\bin\hayabusa-fx-3.10.0.exe json-timeline `
  -f .\samples\rule-tests\hayfx-2026-detections.evtx `
  -r .\rules-custom `
  -L -o .\samples\rule-tests\result.jsonl `
  -m low -q -K -b -C -w
```

`result.jsonl` の `RuleTitle` が上表と一致することを確認します。

## 注意

- イベントはすべて合成です。マルウェアは含まれていません。
- 生成にはテスト用に [JPCERTCC/xml2evtx](https://github.com/JPCERTCC/xml2evtx) を使用しました。アプリ本体の依存関係には追加していません。
- `hayfx-negative-control.evtx` は新規ルールの negative control です。Hayabusa 標準ルールを含めた全体スキャンでは、環境やルールセットによって別の検知が出る場合があります。
