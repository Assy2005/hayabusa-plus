"""
hayabusa-plus 実動作スクリーンキャスト生成
==========================================

スクショの紙芝居ではなく、「実際に動いているところ」を録画する。
Chrome DevTools Protocol (CDP) の Page.startScreencast で、ヘッドレス
Chrome の画面更新フレームをそのまま受け取りながら、同じ CDP 接続から
JS で操作 (タブ切替・スキャン実行・検知の展開) を流す。これにより
進捗バーの伸び・フィードのリアルタイム流入・グラフ描画・解説パネルの
展開といった "動き" がそのまま記録される。

最後に ffmpeg で、フレーム本来のタイミングを保ったまま CFR 30fps の
MP4 にまとめ、各シーンの日本語字幕 (ロワーサード) を時間指定で重ねる。

  python docs/demo/make_screencast.py

依存: websocket-client, Pillow, ffmpeg, Google Chrome
前提: GUI サーバが 8787 (or 53190) で起動済み
"""

from __future__ import annotations

import base64
import itertools
import json
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import websocket  # websocket-client
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
CAST = HERE / "_cast"
if CAST.exists():
    shutil.rmtree(CAST)
CAST.mkdir()
OUT = HERE / "hayabusa-plus-demo.mp4"

W, H = 1600, 900
VW, VH = 1920, 1080
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
FONTS = Path("C:/Windows/Fonts")
F_TITLE = str(FONTS / "BIZ-UDGothicB.ttc")
F_BODY = str(FONTS / "YuGothM.ttc")

NAVY = (15, 23, 42)
ACCENT = (37, 99, 235)
ICE = (202, 220, 252)
WHITE = (255, 255, 255)


def find_base():
    for port in (8787, 53190):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as r:
                if r.status == 200:
                    return f"http://127.0.0.1:{port}"
        except Exception:
            pass
    raise SystemExit("GUI サーバが見つかりません (8787/53190)。")


# ---------------------------------------------------------------------------
# 最小 CDP クライアント (websocket-client + 受信スレッド)
# ---------------------------------------------------------------------------
class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, max_size=None,
                                               suppress_origin=True)
        self._id = itertools.count(1)
        self._lock = threading.Lock()
        self._pending = {}
        self.frames = []          # (timestamp, jpeg_bytes)
        self._capture = False
        self._running = True
        self.t0 = None
        self._reader = threading.Thread(target=self._loop, daemon=True)
        self._reader.start()

    def _loop(self):
        while self._running:
            try:
                msg = self.ws.recv()
            except Exception:
                break
            if not msg:
                continue
            data = json.loads(msg)
            if "id" in data:
                slot = self._pending.get(data["id"])
                if slot is not None:
                    slot[1] = data
                    slot[0].set()
            elif data.get("method") == "Page.screencastFrame":
                p = data["params"]
                if self._capture:
                    ts = (p.get("metadata") or {}).get("timestamp") or time.time()
                    if self.t0 is None:
                        self.t0 = ts
                    self.frames.append((ts, base64.b64decode(p["data"])))
                try:
                    self._raw_send("Page.screencastFrameAck",
                                   {"sessionId": p["sessionId"]})
                except Exception:
                    pass

    def _raw_send(self, method, params=None):
        mid = next(self._id)
        payload = json.dumps({"id": mid, "method": method, "params": params or {}})
        with self._lock:
            self.ws.send(payload)
        return mid

    def call(self, method, params=None, timeout=60):
        mid = next(self._id)
        ev = threading.Event()
        self._pending[mid] = [ev, None]
        payload = json.dumps({"id": mid, "method": method, "params": params or {}})
        with self._lock:
            self.ws.send(payload)
        if not ev.wait(timeout):
            raise TimeoutError(method)
        res = self._pending.pop(mid)[1]
        if "error" in res:
            raise RuntimeError(f"{method}: {res['error']}")
        return res.get("result", {})

    def js(self, expr, timeout=60):
        r = self.call("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True,
                       "awaitPromise": True}, timeout)
        return (r.get("result") or {}).get("value")

    def wait_js(self, expr, timeout=30, poll=0.25):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                if self.js(expr):
                    return True
            except Exception:
                pass
            time.sleep(poll)
        return False

    def start_cast(self):
        self._capture = True
        self.call("Page.startScreencast",
                  {"format": "jpeg", "quality": 80,
                   "maxWidth": W, "maxHeight": H, "everyNthFrame": 1})

    def stop_cast(self):
        self._capture = False
        try:
            self.call("Page.stopScreencast")
        except Exception:
            pass

    def close(self):
        self._running = False
        try:
            self.ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 撮影シナリオ
# ---------------------------------------------------------------------------

def run_demo(cdp, base):
    scenes = []  # (start_offset_sec, title, sub)

    def mark(title, sub):
        # 字幕の表示開始は「録画フレームの時刻」に合わせる。動画は CDP フレーム
        # のタイムスタンプで組むので、同じ時計を使えば字幕と映像がズレない。
        fr = cdp.frames
        off = (fr[-1][0] - fr[0][0]) if fr else 0.0
        scenes.append((off, title, sub))

    def click(sel):
        cdp.js(f"(document.querySelector({json.dumps(sel)})||{{click(){{}}}}).click()")

    def tab(name):
        click(f'button[data-tab="{name}"]')

    # 画面ロード待ち + 録画開始
    cdp.call("Page.enable")
    cdp.wait_js("document.querySelector('nav button[data-tab]')!==null", 20)
    time.sleep(1.0)
    cdp.start_cast()
    time.sleep(0.8)

    # 字幕は「内容が描画されてから」出したいので、タブ切替後に少し待ってから
    # mark() する (mark の時刻 = その時点の録画フレーム時刻)。

    # 1) ホーム
    tab("home"); time.sleep(1.0)
    mark("迷わない入口 — 3 ステップ",
         "「①見つける → ②読む → ③俯瞰」。専門知識がなくても始められる。")
    time.sleep(2.6)

    # 2) スキャン: 対象選択
    tab("scan")
    cdp.wait_js("document.querySelectorAll('.ws-item').length>0", 15)
    time.sleep(0.9)
    mark("① ログをスキャンする",
         "Windows のログ（サンプル EVTX）を選んで実行するだけ。")
    time.sleep(1.3)
    cdp.js("""
      const it=[...document.querySelectorAll('.ws-item')]
        .find(c=>/meterpreter|faxhell|sideloading|portforward|1102/i.test(c.textContent))
        ||document.querySelector('.ws-item');
      if(it) it.click();
    """)
    time.sleep(1.4)

    # 3) 実行 → 進捗バーの動き + フィード流入をそのまま録画
    click("#scan-btn")
    time.sleep(0.8)
    mark("解析中 — 進捗をリアルタイム表示",
         "数万件でも、今どこまで進んだかが % で分かる。")
    cdp.wait_js("document.querySelectorAll('#live-feed .row.clickable').length>0", 60)
    time.sleep(2.6)

    # 4) 検知を 1 件展開 → 日本語の解説 (パネルが出てから字幕)
    cdp.js("var r=document.querySelector('#live-feed .row.clickable'); if(r) r.click();")
    cdp.wait_js("document.querySelector('.explain-row .explain-block')!==null", 15)
    cdp.js("var e=document.querySelector('.explain-row'); if(e) e.scrollIntoView({block:'center'});")
    time.sleep(0.7)
    mark("② 検知の中身を日本語で読む",
         "クリックで「なにを検知／次にすべきこと」を日本語で解説。")
    time.sleep(4.0)

    # 5) 全体ビュー (グラフ描画の動き)
    tab("dashboard"); time.sleep(1.0)
    mark("③ 全体をひと目で把握",
         "重大度の内訳・時間の流れ・多い攻撃をグラフで俯瞰。")
    time.sleep(3.3)

    # 6) パソコン別
    tab("hosts"); time.sleep(1.0)
    mark("パソコン別の危険度ランキング",
         "どの端末から調べるべきかを自動採点して並べ替え。")
    time.sleep(3.0)

    # 7) さがす
    tab("hunt"); time.sleep(1.0)
    mark("横断して『さがす』",
         "ルール名・ホスト・期間で全検知をまとめて検索。")
    time.sleep(3.0)

    # 8) ルール + 外部リスト
    tab("rules"); time.sleep(1.1)
    mark("検出ルールと外部リスト照合",
         "自作 13 ルール ＋ loldrivers.io 等の悪性リストを取り込む。")
    time.sleep(3.6)

    # 後始末用にジョブ ID を回収 (CDP は式評価なので IIFE で返す)
    job = cdp.js("(function(){var e=document.getElementById('live-jobid');"
                 "return e?e.textContent.replace('#','').trim():null;})()")
    return scenes, job


# ---------------------------------------------------------------------------
# 字幕オーバーレイ (透明 PNG)
# ---------------------------------------------------------------------------

def make_caption(path, title, sub):
    img = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    band_h = 200
    y0 = VH - band_h
    d.rectangle([0, y0, VW, VH], fill=(15, 23, 42, 225))
    d.rectangle([0, y0, VW, y0 + 6], fill=ACCENT + (255,))
    d.text((70, y0 + 38), title, font=ImageFont.truetype(F_TITLE, 50), fill=WHITE)
    d.text((70, y0 + 116), sub, font=ImageFont.truetype(F_BODY, 32), fill=ICE)
    img.save(path)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    base = find_base()
    print(f"GUI: {base}")

    profile = tempfile.mkdtemp(prefix="hayabusa_cast_")
    proc = subprocess.Popen([
        CHROME, "--headless=new", "--remote-debugging-port=9222",
        "--hide-scrollbars", "--disable-gpu", "--force-device-scale-factor=1",
        f"--window-size={W},{H}", "--no-first-run", "--no-default-browser-check",
        f"--user-data-dir={profile}", base + "/",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # devtools の page ターゲットを探す
    ws_url = None
    for _ in range(40):
        try:
            with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=1) as r:
                for t in json.load(r):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        ws_url = t["webSocketDebuggerUrl"]; break
        except Exception:
            pass
        if ws_url:
            break
        time.sleep(0.25)
    if not ws_url:
        proc.terminate(); raise SystemExit("Chrome devtools に接続できません。")

    cdp = CDP(ws_url)
    scenes, job = [], None
    try:
        scenes, job = run_demo(cdp, base)
    finally:
        cdp.stop_cast()
        time.sleep(0.4)
        frames = list(cdp.frames)
        cdp.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)

    print(f"captured {len(frames)} frames, {len(scenes)} scenes, job={job}")
    if len(frames) < 5:
        raise SystemExit("フレームが取得できませんでした。")

    # デモで作った一時ジョブを削除
    if job:
        try:
            req = urllib.request.Request(f"{base}/api/jobs/{job}", method="DELETE",
                                         headers={"Origin": base})
            urllib.request.urlopen(req, timeout=10)
            print(f"  cleanup -> deleted demo job {job}")
        except Exception as e:
            print(f"  [warn] cleanup: {e}")

    # フレーム書き出し + 本来のタイミングで concat リスト生成
    t0 = frames[0][0]
    rel = [(ts - t0, jpg) for ts, jpg in frames]
    total = rel[-1][0]
    listing = CAST / "frames.txt"
    with open(listing, "w") as f:
        for i, (t, jpg) in enumerate(rel):
            (CAST / f"{i:05d}.jpg").write_bytes(jpg)
            dur = (rel[i + 1][0] - t) if i + 1 < len(rel) else 0.15
            dur = max(dur, 0.001)
            f.write(f"file '{i:05d}.jpg'\nduration {dur:.4f}\n")
        f.write(f"file '{len(rel) - 1:05d}.jpg'\n")
    print(f"  total ~{total:.1f}s")

    # 字幕 PNG (シーンごと) と表示時間帯。
    # クリック直後はまだ前タブの内容が残る (取得+描画に ~1 秒) ので、字幕は
    # SETTLE 秒ぶん遅らせて、新しい内容が出てから出す。
    SETTLE = 0.15
    caps = []
    for idx, (start, title, sub) in enumerate(scenes):
        p = CAST / f"cap_{idx:02d}.png"
        make_caption(p, title, sub)
        s = start + SETTLE
        end = (scenes[idx + 1][0] + SETTLE) if idx + 1 < len(scenes) else total + 1
        caps.append((p, s, end))

    # ffmpeg: concat (real timing) → 30fps、字幕を時間指定でオーバーレイ
    inputs = ["-f", "concat", "-safe", "0", "-i", str(listing)]
    for p, _, _ in caps:
        inputs += ["-i", str(p)]
    fc = [f"[0:v]scale={VW}:{VH}:flags=lanczos,fps=30[bg]"]
    cur = "bg"
    for i, (_, s, e) in enumerate(caps):
        nxt = f"v{i}"
        fc.append(f"[{cur}][{i + 1}:v]overlay=0:0:enable='between(t,{s:.2f},{e:.2f})'[{nxt}]")
        cur = nxt
    fadeout = max(total - 0.6, 0.1)
    fc.append(f"[{cur}]fade=t=in:st=0:d=0.5,"
              f"fade=t=out:st={fadeout:.2f}:d=0.6,format=yuv420p[outv]")
    cmd = ["ffmpeg", "-y", *inputs,
           "-filter_complex", ";".join(fc),
           "-map", "[outv]", "-t", f"{total:.2f}",
           "-c:v", "libx264", "-crf", "21", "-preset", "medium",
           "-movflags", "+faststart", str(OUT)]
    print("  ffmpeg ...")
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        print(r.stdout.decode("utf-8", "ignore")[-2000:])
        raise SystemExit("ffmpeg 失敗")
    print(f"OK -> {OUT}  ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
