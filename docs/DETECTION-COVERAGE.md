# EVTX 攻撃サンプルによる検知カバレッジ

`sbousseaden/evtx-attack-samples` の EVTX サンプルを使い、Hayabusa の検知ルールが
どの攻撃手順を捉えられるかを継続的に測るための手順です。

## 1. サンプル取得

サンプルはリポジトリにコミットしません。作業用ディレクトリへ取得します。

```bash
git clone --depth 1 https://github.com/sbousseaden/evtx-attack-samples.git \
  ~/evtx-attack-samples
```

## 2. カバレッジ測定

```bash
python3 tools/evtx_sample_coverage.py \
  --dataset ~/evtx-attack-samples \
  --workers 4 \
  --min-level low \
  --json-out ~/hayfx-coverage.json
```

- 1ファイルずつスキャンするため、「どのサンプルが検知されたか」を正確に把握できます。
- ルール読み込みのオーバーヘッドがあるため、全体では数分かかります。
- `--all-rules` を付けると `-A`（チャネルフィルタ解除）で測定できます。
- `--engine` でエンジンを指定できます。

出力例:

```text
covered: 269/278 (96.8%)
missed : 9
  MISS ...
```

`coverage.json` にはファイルごとの検知件数、レベル、ルール名、実行時間が入ります。

## 3. 注意点

このサンプル群は「攻撃の再現ログ」であり、すべてが本番環境で検知すべき
高シグナルなイベントとは限りません。たとえば BITS の正常な更新ジョブや
OS の管理イベントも含まれます。

そのため、カバレッジ 100% を目標にするのではなく、次の2つを目指して評価します。

1. **攻撃に関係するサンプルを検知できるか**
2. **正常な管理イベントを誤検知しないか**

`rules-custom/` に追加したルールは、サンプルに合わせた過剰なファイル名依存を避け、
イベント ID・チャネル・フィールドの組み合わせで判定します。

## 4. ルール追加の流れ

1. 未検知サンプルを選ぶ
2. `hayabusa search` で対象イベントのチャネル・EventID・主要フィールドを確認
3. `rules-custom/` に Sigma ルールを追加
4. `bin/rules/hayabusa/custom/` にコピー

```bash
cp rules-custom/*.yml bin/rules/hayabusa/custom/
```

5. 単体サンプルで検知を確認

```bash
./bin/hayabusa-fx-3.10.0.exe json-timeline \
  -f /path/to/sample.evtx -r rules-custom \
  -L -o /tmp/result.jsonl -m low -q -K -b -C -w
```

6. カバレッジを再測定
7. クリーンな基準ログで誤検知を確認

## 5. 現在の結果（2026-11-05）

| 項目 | 値 |
|---|---|
| カスタムルール | 53 本 |
| サンプル数 | 278 |
| ベースライン | 213 / 278（76.6%） |
| カスタムルール適用後 | **269 / 278（96.8%）** |
| 未検知 | 9 |

未検知の主なサンプル:

- `CA_PetiPotam_etw_rpc_efsr_5_6.evtx`
- `DFIR_RDP_Client_TimeZone_RdpCoreTs_104_example.evtx`
- `dfir_rdpsharp_target_RdpCoreTs_168_68_131.evtx`
- `etw_rpc_zerologon.evtx`
- `Exec_via_cpl_Application_Experience_EventID_17_ControlPanelApplet.evtx`
- `LM_WMI_4624_4688_TargetHost.evtx`
- `Persistence_Shime_Microsoft-Windows-Application-Experience_Program-Telemetry_500.evtx`
- `Persistence_Winsock_Catalog Change EventId_1.evtx`
- `rdpcorets_148_mst120_bluekeep_rpdscan_full.evtx`

これらは RDP クライアントの痕跡、ETW/RPC、Application-Experience、Winsock カタログ、
WMI のターゲット側など、単一の Windows イベントだけでは攻撃意図を確定しにくい
ものが中心です。無理にノイズの多い包括ルールを追加せず、必要に応じて
個別の調査ルールとして追加します。

## 6. 2026年の重点ルール

- ClickFix: `hayfx_clickfix_runmru`, `hayfx_clickfix_pcalua`, `hayfx_clickfix_explorer_child`
- RMM 悪用: `hayfx_rmm_suspicious_deployment`
- Defender 改ざん: `hayfx_defender_exclusion_tamper`
- 横展開: `hayfx_wmiexec_admin_share`, `hayfx_winrm_remote_management`
- 持ち出し: `hayfx_rclone_exfil`
- 認証情報: `hayfx_browser_credential_copy`
- 防御回避: `hayfx_cloudflared_svchost`, `hayfx_amsi_patch_triad`
- BYOVD: `hayfx_byovd_driver_user_path`, `hayfx_lookup_loldriver_load`

追加ルールは誤検知とのトレードオフがあります。運用環境では `min-level` と
抑制ルールを調整し、クリーンな基準ログで定期的に FP を確認してください。

## 7. 動作確認用サンプル

`samples/rule-tests/` に、新しい検知ルール専用の合成 EVTX を同梱しています。

- `hayfx-2026-detections.evtx`: 12イベント / 12検知（positive）
- `hayfx-negative-control.evtx`: 新規ルール 0検知（negative control）
- `expected.json`: EventRecordID と期待ルールの対応
- `source/*.xml`: 生成元の Event XML

```bash
python tools/check_rule_samples.py
```

このスクリプトはローカルの Hayabusa エンジンで両方の EVTX をスキャンし、
positive の全ルール発火と negative の非発火を自動確認します。
