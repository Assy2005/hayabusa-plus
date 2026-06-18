"""
hayabusa-plus デモ動画フレーム生成スクリプト
============================================

実際に動いている GUI を Selenium で操作してスクリーンショットを撮り、
各シーンに日本語の説明字幕 (ロワーサード) を焼き込んだ PNG を
docs/demo/frames/ に書き出す。動画への合成は ffmpeg (別ステップ)。

前提:
  * GUI サーバが localhost:8787 (or 53190) で起動済み
  * selenium 4.6+ (Selenium Manager で chromedriver 自動取得)
  * Pillow + Windows 同梱の日本語フォント

使い方:
  python docs/demo/make_demo.py
"""

from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
FRAMES = HERE / "frames"
FRAMES.mkdir(exist_ok=True)
RAW = FRAMES / "_raw"
RAW.mkdir(exist_ok=True)

W, H = 1600, 900            # 16:9 撮影サイズ (100vh アプリ = 1 画面)
FONTS = Path("C:/Windows/Fonts")
F_TITLE = str(FONTS / "BIZ-UDGothicB.ttc")
F_BODY  = str(FONTS / "YuGothM.ttc")

# 配色 (発表スライドと統一)
NAVY   = (27, 37, 79)
ACCENT = (37, 99, 235)
ICE    = (202, 220, 252)
WHITE  = (255, 255, 255)


def find_base() -> str:
    for port in (8787, 53190):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as r:
                if r.status == 200:
                    return f"http://127.0.0.1:{port}"
        except Exception:
            continue
    sys.exit("GUI サーバが見つかりません (8787 / 53190)。先に起動してください。")


def font(path, size):
    return ImageFont.truetype(path, size)


# ---------------------------------------------------------------------------
# 字幕の焼き込み
# ---------------------------------------------------------------------------

def add_caption(raw_path: Path, out_path: Path, title: str, sub: str, *,
                step: str | None = None):
    base = Image.open(raw_path).convert("RGB")
    if base.size != (W, H):
        base = base.resize((W, H))
    draw = ImageDraw.Draw(base, "RGBA")

    band_h = 165
    y0 = H - band_h
    # 半透明の暗い帯 + 上にアクセントの細線
    draw.rectangle([0, y0, W, H], fill=(15, 23, 42, 222))
    draw.rectangle([0, y0, W, y0 + 5], fill=ACCENT + (255,))

    x = 56
    ty = y0 + 30
    if step:
        # 左肩のステップバッジ
        bf = font(F_TITLE, 22)
        tw = draw.textlength(step, font=bf)
        draw.rounded_rectangle([x, ty + 4, x + tw + 28, ty + 44], radius=8,
                               fill=ACCENT + (255,))
        draw.text((x + 14, ty + 9), step, font=bf, fill=WHITE)
        x += tw + 28 + 22

    draw.text((x, ty), title, font=font(F_TITLE, 40), fill=WHITE)
    draw.text((56, y0 + 92), sub, font=font(F_BODY, 26), fill=ICE)

    base.save(out_path)
    print(f"  caption -> {out_path.name}")


def make_card(out_path: Path, lines, *, bg=NAVY):
    """全画面のタイトル/エンドカードを生成 (撮影なし)。
    lines = [(text, font_path, size, color, dy), ...] を中央寄せで縦に積む。"""
    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)
    # アクセントの帯
    draw.rectangle([0, 0, W, 8], fill=ACCENT)
    draw.rectangle([0, H - 8, W, H], fill=ACCENT)
    total = sum(dy for *_, dy in lines)
    y = (H - total) // 2
    for text, fpath, size, color, dy in lines:
        f = font(fpath, size)
        tw = draw.textlength(text, font=f)
        draw.text(((W - tw) // 2, y), text, font=f, fill=color)
        y += dy
    img.save(out_path)
    print(f"  card    -> {out_path.name}")


# ---------------------------------------------------------------------------
# 撮影
# ---------------------------------------------------------------------------

def main():
    base = find_base()
    print(f"GUI: {base}")

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--hide-scrollbars")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--force-device-scale-factor=1")
    opts.add_argument(f"--window-size={W},{H}")
    drv = webdriver.Chrome(options=opts)
    drv.set_window_size(W, H)
    wait = WebDriverWait(drv, 12)

    def goto(tab):
        drv.find_element(By.CSS_SELECTOR, f'button[data-tab="{tab}"]').click()
        time.sleep(1.4)

    def shot(name):
        p = RAW / f"{name}.png"
        drv.save_screenshot(str(p))
        print(f"  shot    -> {p.name}")
        return p

    try:
        drv.get(base + "/")
        time.sleep(2.0)

        demo_job = None
        goto("home"); shot("home")

        # ---- 実際にスキャンを 1 本流す (サンプル EVTX) ----
        goto("scan")
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".ws-item")))
            time.sleep(0.5)
            shot("scan")  # 対象選択前のスキャン画面
            # 攻撃サンプルを 1 つ選ぶ (なければ先頭の EVTX)
            drv.execute_script("""
              const items=[...document.querySelectorAll('.ws-item')];
              const pref=items.find(c=>/meterpreter|faxhell|sideloading|portforward|1102/i
                          .test(c.textContent)) || items[0];
              if(pref) pref.click();
            """)
            time.sleep(0.7)
            drv.find_element(By.ID, "scan-btn").click()
            # 進捗 (%) が出ている瞬間を撮る
            time.sleep(1.1)
            shot("scan_progress")
            # 検知がフィードに出るまで待つ
            WebDriverWait(drv, 60).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, "#live-feed .row.clickable"))
            time.sleep(2.2)  # スキャン完了 + フィード安定待ち
            demo_job = drv.execute_script(
                "var e=document.getElementById('live-jobid');"
                "return e?e.textContent.replace('#','').trim():null;")
            # 検知行をクリック → 日本語の解説パネルを開く
            rows = drv.find_elements(By.CSS_SELECTOR, "#live-feed .row.clickable")
            if rows:
                rows[0].click()
                wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, ".explain-row .explain-block")))
                time.sleep(0.8)
                drv.execute_script(
                    "document.querySelector('.explain-row').scrollIntoView({block:'center'});")
                time.sleep(0.5)
                shot("explain")
        except Exception as e:
            print(f"  [warn] scan/explain scene: {e}")

        goto("dashboard"); time.sleep(1.8); shot("dashboard")  # グラフ描画待ち
        goto("hosts"); time.sleep(1.0); shot("hosts")
        goto("hunt");  shot("hunt")
        goto("rules"); time.sleep(1.4); shot("rules")
    finally:
        drv.quit()

    # デモで作った一時ジョブは消しておく (元データを汚さない)
    if demo_job:
        try:
            req = urllib.request.Request(
                f"{base}/api/jobs/{demo_job}", method="DELETE",
                headers={"Origin": base})
            urllib.request.urlopen(req, timeout=10)
            print(f"  cleanup -> deleted demo job {demo_job}")
        except Exception as e:
            print(f"  [warn] cleanup demo job: {e}")

    # ---- カード + 字幕の合成 ----
    print("compose:")
    make_card(FRAMES / "00_title.png", [
        ("hayabusa-plus", F_TITLE, 96, WHITE, 132),
        ("Windows のログから攻撃の痕跡を、誰でも読めるように", F_BODY, 34, ICE, 70),
        ("― 実際の画面によるデモ ―", F_BODY, 24, ICE, 0),
    ])

    scenes = [
        ("home",          "01_home",     "ホーム", "迷わない入口 — 3 ステップ",
         "「①スキャン → ②全体ビュー → ③深掘り」。専門知識がなくても始められる。"),
        ("scan",          "02_scan",     "STEP 1", "ログをスキャンする",
         "Windows のログ（または自分の PC）を選んで実行するだけ。"),
        ("scan_progress", "03_progress", None,     "解析中 — 進捗を % で表示",
         "数万件のログでも、今どこまで進んだかが一目で分かる。"),
        ("dashboard",     "04_dashboard","STEP 2", "全体をひと目で把握",
         "重大度の内訳・時間の流れ・多い攻撃をダッシュボードで俯瞰。"),
        ("explain",       "05_explain",  "STEP 3", "中身を日本語で読む",
         "検知をクリックすると「なにを検知／次にすべきこと」を日本語で解説。"),
        ("hosts",         "06_hosts",    None,     "パソコン別の危険度ランキング",
         "どの端末から調べるべきかを自動で採点して並べ替え。"),
        ("hunt",          "07_hunt",     None,     "横断して『さがす』",
         "ルール名・ホスト・期間で、すべての検知をまとめて検索。"),
        ("rules",         "08_rules",    None,     "検出ルールと外部リスト照合",
         "自作 13 ルール ＋ loldrivers.io 等の悪性リストを取り込んで照合。"),
    ]
    for raw_name, out_name, step, title, sub in scenes:
        rp = RAW / f"{raw_name}.png"
        if not rp.exists():
            print(f"  [skip] {raw_name} (撮影なし)")
            continue
        add_caption(rp, FRAMES / f"{out_name}.png", title, sub, step=step)

    make_card(FRAMES / "09_end.png", [
        ("すべてブラウザで動作 ・ データは外部に送りません", F_BODY, 34, WHITE, 90),
        ("github.com/Assy2005/hayabusa-plus", F_TITLE, 40, ICE, 0),
    ])
    print("done.")


if __name__ == "__main__":
    main()
