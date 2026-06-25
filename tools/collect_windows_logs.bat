@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 932 >nul
title Windows ログ吸い出しツール (hayabusa-plus 用)

REM ============================================================
REM  Windows のイベントログ (EVTX) をまとめて書き出し、ZIP にします。
REM  解析する人 (hayabusa-plus 側) に、出来た ZIP を渡してください。
REM
REM  使い方:  このファイルをダブルクリックするだけ。
REM    - 管理者権限が要ります (Security ログのため)。
REM      UAC のダイアログが出たら「はい」を押してください。
REM    - 既定で「直近 30 日分」だけ書き出します (サイズ削減のため)。
REM      全期間が欲しい場合は下の DAYS を大きくしてください。
REM    - 出力先:  デスクトップ\hayabusa-logs_<PC名>_<日時>.zip
REM ============================================================

set "DAYS=30"

REM ---- 管理者権限へ昇格 (なければ自動で再起動) ----
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo 管理者権限が必要です。UAC のダイアログで「はい」を押してください...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

echo.
echo   Windows ログを収集します (直近 %DAYS% 日)。少し時間がかかります...
echo.

REM ---- タイムスタンプと期間 (ミリ秒) を PowerShell で取得 ----
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"`) do set "STAMP=%%i"
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "[int64]%DAYS%*86400*1000"`) do set "MS=%%i"

set "OUTBASE=%USERPROFILE%\Desktop"
set "NAME=hayabusa-logs_%COMPUTERNAME%_%STAMP%"
set "OUTDIR=%OUTBASE%\%NAME%"
mkdir "%OUTDIR%" 2>nul

set "COUNT=0"

REM ---- 主要チャネルを書き出し (存在しないものは自動スキップ) ----
call :export "Security"                                                           "Security.evtx"
call :export "System"                                                             "System.evtx"
call :export "Application"                                                        "Application.evtx"
call :export "Microsoft-Windows-Sysmon/Operational"                               "Sysmon-Operational.evtx"
call :export "Microsoft-Windows-PowerShell/Operational"                           "PowerShell-Operational.evtx"
call :export "Windows PowerShell"                                                 "WindowsPowerShell.evtx"
call :export "Microsoft-Windows-TaskScheduler/Operational"                        "TaskScheduler-Operational.evtx"
call :export "Microsoft-Windows-WMI-Activity/Operational"                         "WMI-Activity-Operational.evtx"
call :export "Microsoft-Windows-Windows Defender/Operational"                     "Defender-Operational.evtx"
call :export "Microsoft-Windows-TerminalServices-LocalSessionManager/Operational" "RDP-LocalSessionManager.evtx"

echo.
echo   %COUNT% 個のログを書き出しました。ZIP にまとめています...

REM ---- ZIP 化 ----
set "ZIP=%OUTBASE%\%NAME%.zip"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%OUTDIR%\*' -DestinationPath '%ZIP%' -Force"

if exist "%ZIP%" (
  rmdir /s /q "%OUTDIR%" 2>nul
  echo.
  echo   ============================================================
  echo    完了しました。この ZIP を解析担当者に渡してください:
  echo.
  echo      %ZIP%
  echo   ============================================================
) else (
  echo.
  echo   [注意] ZIP 化に失敗しました。このフォルダをそのまま渡してください:
  echo      %OUTDIR%
)

echo.
echo   何かキーを押すと閉じます。
pause >nul
exit /b

REM ============================================================
REM  :export "<チャネル名>" "<出力ファイル名>"
REM   直近 %DAYS% 日に絞って EVTX を書き出す。クエリ非対応の環境では
REM   フィルタ無しで再試行。それでも無いチャネルはスキップ。
REM ============================================================
:export
set "CH=%~1"
set "FN=%~2"
echo   - %CH%
wevtutil epl "%CH%" "%OUTDIR%\%FN%" /ow:true /q:"*[System[TimeCreated[timediff(@SystemTime) <= %MS%]]]" >nul 2>&1
if errorlevel 1 wevtutil epl "%CH%" "%OUTDIR%\%FN%" /ow:true >nul 2>&1
if exist "%OUTDIR%\%FN%" (
  set /a COUNT+=1
) else (
  echo       ^(スキップ: 存在しないかアクセス不可^)
)
goto :eof
