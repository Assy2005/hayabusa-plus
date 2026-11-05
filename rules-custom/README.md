# カスタム検知ルール

`rules-custom/` は、Hayabusa 標準ルールを置き換えずに上乗せする DFIR 向けの
Sigma ルール群です。2026 年 11 月時点で **53 本**を収録しています。

## 設計方針

- 攻撃者が目的を達成するために変えにくい特徴を、`Image` / `ParentImage` /
  `CommandLine` / レジストリパス / イベント ID の組み合わせで検知する
- 正常な管理操作やベンダー製品が混ざる箇所は `filter_*` で除外する
- 各ルールに `falsepositives` と `references` を記載する
- 100% のサンプルカバレッジではなく、高シグナルな検知と誤検知抑制のバランスを取る

## 主なカテゴリ

| カテゴリ | 例 |
|---|---|
| ClickFix / 偽 CAPTCHA | `hayfx_clickfix_runmru`, `hayfx_clickfix_pcalua`, `hayfx_clickfix_explorer_child` |
| RMM 悪用 | `hayfx_rmm_suspicious_deployment` |
| 横展開 | `hayfx_5145_*`, `hayfx_winrm_*`, `hayfx_wmiexec_admin_share`, `hayfx_dcom_*` |
| 認証情報窃取 | `hayfx_lsass_*`, `hayfx_browser_credential_copy`, `hayfx_4703_*` |
| 防御回避 | `hayfx_amsi_*`, `hayfx_defender_exclusion_tamper`, `hayfx_cloudflared_svchost` |
| BYOVD | `hayfx_byovd_driver_user_path`, `hayfx_lookup_loldriver_load` |
| 永続化 | `hayfx_service_*`, `hayfx_wmi_persistence_*`, `hayfx_4698_*` |
| 痕跡隠蔽 / ランサム前兆 | `hayfx_af_*`, `hayfx_anti_forensics_*`, `hayfx_4826_*` |
| 外部持ち出し | `hayfx_rclone_exfil`, `hayfx_bits_external_download` |

## 配置

```bash
cp -f rules-custom/*.yml bin/rules/hayabusa/custom/
```

GUI からスキャンする場合は `bin/rules` を参照するため、上記コピーだけで反映されます。

## 単体確認

```bash
./bin/hayabusa-fx-3.10.0.exe json-timeline \
  -f /path/to/sample.evtx \
  -r rules-custom \
  -L -o /tmp/custom.jsonl \
  -m low -q -K -b -C -w
```

ルールの構文エラーは `logs/errorlog-*.log` に出力されます。

## 誤検知の調整

- まず `min-level` を `medium` 以上にして運用を開始する
- 管理ツール由来の検知は `filter_*` を環境に合わせて拡張する
- 個別の正当業務は GUI の抑制（suppression）でホスト / ルール単位に除外する
- 定期的にクリーンな基準ログへ適用し、ルール単位の FP 率を確認する

## 注意

- `correlate:` は使用していません。すべて単一イベントで評価できます。
- ルールは検知の出発点です。アラート単体ではなく、前後のプロセス・認証・
  ネットワークイベントと合わせて判断してください。
