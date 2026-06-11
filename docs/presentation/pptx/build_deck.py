"""
hayabusa-plus 発表用 PowerPoint (.pptx) 生成スクリプト — 一般向け版
==================================================================

13 枚構成。発表時間 10-12 分 (+ デモ 5 分 + Q&A 5 分) を想定。

このスクリプトは **専門知識がない人** にも伝わるよう用語を絞った版を
作ります。技術者向けの詳細版は build_deck_advanced.py を参照。

実行:
    python build_deck.py

出力:
    hayabusa-plus.pptx  (このスクリプトと同じディレクトリ)

設計方針:
    - 専門用語 (EVTX, Sigma, ATT&CK 等) は最小限、出すときは必ず 1 行解説
    - 機能は「これがあると何が便利か」のストーリーで紹介
    - 各スライドはひとつだけ伝える
    - GUI と同じ明るいテーマ (白 + #2563EB ブルー)、表紙・締めは紺
    - モックではなく docs/images/ の実スクリーンショットを埋め込む
    - 16:9 ワイドスクリーン
"""

from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

try:
    from PIL import Image
except ImportError:  # 画像サイズ取得に使う。無ければ固定比率で配置。
    Image = None


# ---------------------------------------------------------------------------
# カラーパレット (新しい明るい GUI と統一)
# ---------------------------------------------------------------------------
# コンテンツスライド = 明るい (GUI と同じ)
BG_LIGHT    = RGBColor(0xF4, 0xF6, 0xFA)   # GUI --bg
PANEL       = RGBColor(0xFF, 0xFF, 0xFF)   # GUI --panel
PANEL_SOFT  = RGBColor(0xE8, 0xF0, 0xFE)   # GUI --accent-soft
LINE        = RGBColor(0xDD, 0xE3, 0xEE)
ACCENT      = RGBColor(0x25, 0x63, 0xEB)   # GUI --accent (ブルー)
ACCENT_DK   = RGBColor(0x1D, 0x4E, 0xD8)
TEXT        = RGBColor(0x1F, 0x29, 0x37)
MUTED       = RGBColor(0x5B, 0x64, 0x72)

# 表紙・デモ・締め = 紺 (サンドイッチ構成)
NAVY        = RGBColor(0x1B, 0x25, 0x4F)
NAVY_PANEL  = RGBColor(0x27, 0x33, 0x66)
ICE         = RGBColor(0xCA, 0xDC, 0xFC)
WHITE       = RGBColor(0xFF, 0xFF, 0xFF)

# 重要度 (GUI のセマンティックカラー)
CRIT        = RGBColor(0xDC, 0x26, 0x26)
HIGH        = RGBColor(0xEA, 0x58, 0x0C)
MED         = RGBColor(0xCA, 0x8A, 0x04)
OK          = RGBColor(0x16, 0xA3, 0x4A)

FONT_HEAD = "Cambria"
FONT_BODY = "Calibri"
FONT_MONO = "Consolas"

IMG_DIR = Path(__file__).resolve().parents[2] / "images"   # docs/images


# ---------------------------------------------------------------------------
# ヘルパ
# ---------------------------------------------------------------------------

def new_pres():
    prs = Presentation()
    prs.slide_width  = Inches(13.333)
    prs.slide_height = Inches(7.5)
    return prs


def add_slide(prs, bg):
    blank = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank)
    bg_shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg_shape.fill.solid()
    bg_shape.fill.fore_color.rgb = bg
    bg_shape.line.fill.background()
    bg_shape.shadow.inherit = False
    return slide


def add_text(slide, text, *, x, y, w, h, size=18, color=TEXT,
             font=FONT_BODY, bold=False, italic=False,
             align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
             line_spacing=1.3):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Pt(0)
    tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = align
    p.line_spacing = line_spacing
    run = p.add_run()
    run.text = text
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    return tb


def add_card(slide, x, y, w, h, *, fill=PANEL, accent_left=None, line=LINE):
    card = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    card.fill.solid()
    card.fill.fore_color.rgb = fill
    card.line.color.rgb = line
    card.line.width = Pt(0.75)
    card.shadow.inherit = False
    if accent_left:
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(0.08), Inches(h))
        bar.fill.solid()
        bar.fill.fore_color.rgb = accent_left
        bar.line.fill.background()
        bar.shadow.inherit = False
    return card


def crop_top(name, frac):
    """docs/images/<name>.png の上から frac (0..1) を切り出した一時画像を
    作り、その名前を返す。空白の多いスクショをスライド向けに詰める用。"""
    if Image is None:
        return name
    src = IMG_DIR / f"{name}.png"
    if not src.exists():
        return name
    out_dir = Path(__file__).parent / "_assets"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{name}_top.png"
    im = Image.open(src)
    im.crop((0, 0, im.size[0], int(im.size[1] * frac))).save(out)
    return f"_assets/{name}_top"


def add_screenshot(slide, name, *, x, y, w, h):
    """docs/images/<name>.png をボックス (x,y,w,h) に収めて中央配置。
    枠線を付けて「画面の切り抜き」感を出す。name は crop_top() が返す
    "_assets/..." 形式も受け付ける。"""
    if name.startswith("_assets/"):
        path = Path(__file__).parent / "_assets" / f"{name.split('/', 1)[1]}.png"
    else:
        path = IMG_DIR / f"{name}.png"
    if not path.exists():
        # 画像がないときはプレースホルダ (ビルドは止めない)
        add_card(slide, x, y, w, h, fill=PANEL_SOFT)
        add_text(slide, f"(screenshot: {name})", x=x, y=y + h / 2 - 0.2, w=w,
                 h=0.4, size=12, color=MUTED, align=PP_ALIGN.CENTER)
        return None
    if Image is not None:
        iw, ih = Image.open(path).size
        ratio = iw / ih
    else:
        ratio = 1.4
    box_ratio = w / h
    if ratio >= box_ratio:   # 横長 → 幅で合わせる
        pw, ph = w, w / ratio
    else:                    # 縦長 → 高さで合わせる
        pw, ph = h * ratio, h
    px = x + (w - pw) / 2
    py = y + (h - ph) / 2
    pic = slide.shapes.add_picture(str(path), Inches(px), Inches(py),
                                   Inches(pw), Inches(ph))
    pic.line.color.rgb = LINE
    pic.line.width = Pt(1.0)
    pic.shadow.inherit = False
    return pic


def page_no(slide, n, total, *, dark=False):
    add_text(slide, f"{n} / {total}", x=12.3, y=7.1, w=1.0, h=0.3,
             size=9, color=(ICE if dark else MUTED), align=PP_ALIGN.RIGHT)


def header(slide, title, *, kicker=None):
    if kicker:
        add_text(slide, kicker, x=0.6, y=0.38, w=12, h=0.3,
                 size=11, color=ACCENT, font=FONT_BODY, bold=True)
    add_text(slide, title, x=0.6, y=0.68, w=12.2, h=0.7,
             size=28, color=TEXT, font=FONT_HEAD, bold=True)


# ===========================================================================
# スライド定義 — 一般向け版
# ===========================================================================

def slide_title(prs, total):
    """1: タイトル (紺) — フックを副題でしっかり言い切る."""
    s = add_slide(prs, NAVY)

    add_text(s, "🦅", x=0.7, y=1.0, w=2, h=1.2,
             size=80, color=ICE, align=PP_ALIGN.LEFT)
    add_text(s, "hayabusa-plus",
             x=2.1, y=1.05, w=10.5, h=1.3,
             size=68, color=WHITE, font=FONT_HEAD, bold=True)

    # 副タイトル — 専門知識ゼロでも刺さる一文に
    add_text(s, "サイバー攻撃の痕跡を、誰でも読めるように",
             x=0.6, y=3.3, w=12, h=0.7, size=30,
             color=ICE, font=FONT_HEAD, italic=True,
             align=PP_ALIGN.CENTER)

    add_text(s, "Windows のログから「何が起きたのか」を、ブラウザの画面で見える形にしました。",
             x=0.6, y=4.5, w=12, h=0.5, size=17, color=ICE,
             align=PP_ALIGN.CENTER)

    # ダウンロードしてすぐ使える、をタイトルから言う
    add_card(s, 3.65, 5.5, 6.0, 0.85, fill=NAVY_PANEL, accent_left=None,
             line=NAVY_PANEL)
    add_text(s, "📦 ダウンロードして展開するだけで、すぐ使えます",
             x=3.65, y=5.5, w=6.0, h=0.85, size=15, color=WHITE, bold=True,
             align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

    add_text(s, "github.com/Assy2005/hayabusa-plus",
             x=0.6, y=6.8, w=12, h=0.4, size=14, color=ICE,
             font=FONT_MONO, align=PP_ALIGN.CENTER)


def slide_question(prs, n, total):
    """2: 問いかけ (紺) — 自分事に変える."""
    s = add_slide(prs, NAVY)

    add_text(s, "もし、あなたの会社が",
             x=0.6, y=1.3, w=12, h=0.8, size=30, color=ICE,
             align=PP_ALIGN.CENTER)
    add_text(s, "サイバー攻撃を受けたら",
             x=0.6, y=2.0, w=12, h=0.9, size=44, color=WHITE,
             font=FONT_HEAD, bold=True, align=PP_ALIGN.CENTER)
    add_text(s, "...どうしますか?",
             x=0.6, y=3.0, w=12, h=0.8, size=30, color=ICE,
             align=PP_ALIGN.CENTER)

    questions = [
        ("どこから", "侵入された?"),
        ("誰が", "何をされた?"),
        ("被害は", "どこまで広がった?"),
    ]
    card_w = 3.5
    for i, (top, bot) in enumerate(questions):
        x = 1.4 + i * (card_w + 0.4)
        y = 4.45
        add_card(s, x, y, card_w, 1.8, fill=NAVY_PANEL, line=NAVY_PANEL)
        add_text(s, top, x=x, y=y + 0.25, w=card_w, h=0.55,
                 size=18, color=ICE, font=FONT_HEAD, bold=True,
                 align=PP_ALIGN.CENTER)
        add_text(s, bot, x=x, y=y + 0.85, w=card_w, h=0.6,
                 size=22, color=WHITE, font=FONT_HEAD, bold=True,
                 align=PP_ALIGN.CENTER)

    add_text(s, "これを 素早く 知る必要があります",
             x=0.6, y=6.7, w=12, h=0.4, size=14, color=ICE,
             italic=True, align=PP_ALIGN.CENTER)
    page_no(s, n, total, dark=True)


def slide_problem(prs, n, total):
    """3: 課題 — Windows ログの圧倒される感を伝える."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "答えは Windows のログの中にある", kicker="01  でも...")

    # 左側: ログの「文字の壁」感を出す疑似コード (ここだけ暗い = ログの威圧感)
    add_card(s, 0.6, 1.75, 6.4, 5.1, fill=RGBColor(0x0F, 0x17, 0x2A),
             line=RGBColor(0x0F, 0x17, 0x2A))
    add_text(s, "Windows のログ (実例)", x=1.0, y=2.0, w=5.8, h=0.3,
             size=10, color=RGBColor(0x94, 0xA3, 0xB8), font=FONT_MONO)

    log_lines = [
        '2026-05-21 13:42:15  EID 4624  Logon Type 3  user=alice',
        '2026-05-21 13:42:16  EID 4688  rundll32.exe  comsvcs.dll, ...',
        '2026-05-21 13:42:17  EID 1     ProcessGuid {6BBF237A-CAFB...',
        '2026-05-21 13:42:17  EID 10    TargetImage lsass.exe  Acc...',
        '2026-05-21 13:42:18  EID 4104  $ScriptBlockText FromBase6...',
        '2026-05-21 13:42:18  EID 7045  ServiceName UpdaterSvc  Img...',
        '2026-05-21 13:42:19  EID 22    QueryName malicious-site.c...',
        '2026-05-21 13:42:20  EID 3     DestinationIp 185.220.101....',
        '2026-05-21 13:42:21  EID 8     CreateRemoteThread  source...',
        '...                          (このあと数万件続く)',
    ]
    ly = 2.45
    for line in log_lines:
        add_text(s, line, x=1.0, y=ly, w=5.8, h=0.32,
                 size=10, color=RGBColor(0xCB, 0xD5, 0xE1), font=FONT_MONO)
        ly += 0.41

    # 右側: 結論
    add_text(s, "1 台の PC で", x=7.4, y=2.05, w=5.5, h=0.5,
             size=22, color=TEXT)
    add_text(s, "数万件", x=7.4, y=2.6, w=5.5, h=1.0,
             size=68, color=ACCENT, font=FONT_HEAD, bold=True)
    add_text(s, "のログが残っています", x=7.4, y=3.95, w=5.5, h=0.5,
             size=22, color=TEXT)

    add_card(s, 7.4, 4.9, 5.5, 1.95, fill=PANEL, accent_left=CRIT)
    add_text(s, "これを 1 件ずつ読むのは",
             x=7.65, y=5.1, w=5.1, h=0.45, size=15, color=TEXT)
    add_text(s, "現実的に不可能。",
             x=7.65, y=5.6, w=5.1, h=0.6, size=24, color=CRIT,
             font=FONT_HEAD, bold=True)
    add_text(s, "→ 専門家が時間をかけても見落とす。",
             x=7.65, y=6.3, w=5.1, h=0.4, size=12, color=MUTED, italic=True)

    page_no(s, n, total)


def slide_solution(prs, n, total):
    """4: 解決策 — 実際のダッシュボード画面を見せる."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "それを、ブラウザで見える形にしました",
           kicker="02  hayabusa-plus とは")

    # 左: 3 つの key value (縦積み)
    keys = [
        ("🖥️", "ブラウザだけで完結",
         "データは外部に送りません。\n手元の PC の中だけで動きます。"),
        ("📦", "ダウンロードしてすぐ",
         "zip を展開してダブルクリック。\n難しいインストールは不要。"),
        ("🆓", "無料・公開ソフト",
         "GitHub で公開中。\n誰でも自由に使えます。"),
    ]
    cy = 1.85
    for icon, title, body in keys:
        add_card(s, 0.6, cy, 5.3, 1.55, fill=PANEL, accent_left=ACCENT)
        add_text(s, icon, x=0.85, y=cy + 0.18, w=0.8, h=0.7,
                 size=28, color=ACCENT)
        add_text(s, title, x=1.7, y=cy + 0.18, w=4.0, h=0.45,
                 size=17, color=TEXT, font=FONT_HEAD, bold=True)
        add_text(s, body, x=1.7, y=cy + 0.65, w=4.0, h=0.8,
                 size=11, color=MUTED, line_spacing=1.35)
        cy += 1.75

    # 右: 実際のダッシュボード画面
    add_screenshot(s, "dashboard", x=6.3, y=1.8, w=6.45, h=5.0)
    add_text(s, "▲ 実際の画面 — 検出結果の全体像が一目で分かります",
             x=6.3, y=6.88, w=6.45, h=0.35, size=11, color=MUTED,
             align=PP_ALIGN.CENTER)

    page_no(s, n, total)


def slide_steps(prs, n, total):
    """5: 使い方 3 ステップ — ホーム画面そのまま."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "使い方は、たった 3 ステップ", kicker="03  かんたん")

    steps = [
        ("1", "ログを選ぶ", "「このパソコンを検査」を\n押すだけでも OK"),
        ("2", "スキャンする", "ボタン 1 つで自動チェック。\n進み具合も % で見えます"),
        ("3", "結果を見る", "気になる項目をクリックすると\n意味と対応方法が日本語で"),
    ]
    cy = 1.85
    for num, title, body in steps:
        add_card(s, 0.6, cy, 4.6, 1.55, fill=PANEL, accent_left=ACCENT)
        # 番号サークル
        circ = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(0.85), Inches(cy + 0.45),
                                  Inches(0.62), Inches(0.62))
        circ.fill.solid(); circ.fill.fore_color.rgb = ACCENT
        circ.line.fill.background(); circ.shadow.inherit = False
        tf = circ.text_frame; tf.word_wrap = False
        p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
        r = p.add_run(); r.text = num
        r.font.size = Pt(22); r.font.bold = True
        r.font.color.rgb = WHITE; r.font.name = FONT_HEAD
        add_text(s, title, x=1.7, y=cy + 0.18, w=3.3, h=0.45,
                 size=17, color=TEXT, font=FONT_HEAD, bold=True)
        add_text(s, body, x=1.7, y=cy + 0.65, w=3.3, h=0.8,
                 size=11, color=MUTED, line_spacing=1.35)
        cy += 1.75

    # 右: 実際のホーム画面
    add_screenshot(s, "home", x=5.6, y=1.95, w=7.15, h=4.85)
    add_text(s, "▲ 起動するとこの画面。専門用語も画面の中で説明します",
             x=5.6, y=6.88, w=7.15, h=0.35, size=11, color=MUTED,
             align=PP_ALIGN.CENTER)

    page_no(s, n, total)


def slide_feature_priority(prs, n, total):
    """6: 機能 ① ホスト危険度ランキング — 実画面."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "①  「どこから調べるべきか」が分かる",
           kicker="04  機能 1 / 4")

    add_text(s, "会社のすべての PC を",
             x=0.6, y=1.95, w=5.7, h=0.5, size=18, color=TEXT)
    add_text(s, "「危険度」順に並べます",
             x=0.6, y=2.5, w=6.0, h=0.6, size=26, color=TEXT,
             font=FONT_HEAD, bold=True)

    add_text(s, "「どの PC から手を付ければいいか」が、",
             x=0.6, y=3.6, w=5.9, h=0.5, size=14, color=TEXT,
             line_spacing=1.5)
    add_text(s, "一目で分かります。",
             x=0.6, y=4.05, w=5.9, h=0.5, size=15, color=ACCENT,
             bold=True, line_spacing=1.5)

    add_card(s, 0.6, 5.0, 5.7, 1.7, fill=PANEL_SOFT, line=PANEL_SOFT)
    add_text(s, "💡 危険度は過去の検出履歴から自動計算",
             x=0.85, y=5.2, w=5.3, h=0.4, size=12, color=TEXT, bold=True)
    add_text(s, "重大なものほど高く、最近のものほど高く。\n「誤検知だった」という判定は引き下げます。",
             x=0.85, y=5.65, w=5.3, h=0.85, size=11, color=MUTED,
             line_spacing=1.4)

    # 右: 実際のパソコン別画面 (下半分は空の詳細パネルなので表部分だけ使う)
    add_screenshot(s, crop_top("hosts", 0.55), x=6.6, y=1.85, w=6.15, h=5.0)
    add_text(s, "▲ 実際の画面 — 危険度バー付きでランキング表示",
             x=6.6, y=6.88, w=6.15, h=0.35, size=11, color=MUTED,
             align=PP_ALIGN.CENTER)

    page_no(s, n, total)


def slide_feature_explain(prs, n, total):
    """7: 機能 ② 検知をクリックで説明."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "②  「何が起きているか」が分かる",
           kicker="05  機能 2 / 4")

    add_text(s, "怪しい動きが見つかったら、",
             x=0.6, y=1.95, w=6, h=0.5, size=18, color=TEXT)
    add_text(s, "クリックするだけで",
             x=0.6, y=2.5, w=6.5, h=0.6, size=26, color=TEXT,
             font=FONT_HEAD, bold=True)
    add_text(s, "意味と対応方法を表示します",
             x=0.6, y=3.15, w=6.5, h=0.6, size=26, color=ACCENT,
             font=FONT_HEAD, bold=True)

    add_text(s, "従来は専門家が翻訳していた情報を、",
             x=0.6, y=4.35, w=6.5, h=0.5, size=14, color=TEXT)
    add_text(s, "日本語の解説でその場で表示します。",
             x=0.6, y=4.8, w=6.5, h=0.5, size=14, color=TEXT)

    add_text(s, "💡 「次にすべきこと」も提示するので、",
             x=0.6, y=5.8, w=6.5, h=0.4, size=12, color=MUTED)
    add_text(s, "    初心者でも調査の進め方が分かります。",
             x=0.6, y=6.15, w=6.5, h=0.4, size=12, color=MUTED)

    # 右: 解説パネル風 (白カード)
    add_card(s, 7.3, 1.9, 5.45, 5.0, fill=PANEL, accent_left=CRIT)
    add_text(s, "[重大]", x=7.55, y=2.08, w=1.0, h=0.4,
             size=11, color=CRIT, bold=True, font=FONT_MONO)
    add_text(s, "ID 情報の不正取得を検知",
             x=8.3, y=2.02, w=4.3, h=0.5, size=15, color=TEXT,
             font=FONT_HEAD, bold=True)

    sections = [
        ("📋 何を検知?",
         "本来アクセスしてはいけない、パスワード情報の\nメモリ領域へのアクセスが行われた"),
        ("⚠ 重要度の意味",
         "今すぐ確認が必要なレベル。\n攻撃が成功している可能性大"),
        ("→ 次にすべきこと",
         "1. 該当 PC をネットから切断\n2. 直前の操作履歴を確認\n3. パスワードの一斉変更"),
    ]
    sy = 2.65
    for h, body in sections:
        add_text(s, h, x=7.55, y=sy, w=5.0, h=0.35,
                 size=12, color=ACCENT_DK, bold=True)
        add_text(s, body, x=7.7, y=sy + 0.4, w=4.9, h=1.0,
                 size=11, color=TEXT, line_spacing=1.35)
        sy += 1.45

    page_no(s, n, total)


def slide_feature_anomaly(prs, n, total):
    """8: 機能 ③ いつもと違うを見つける."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "③  「いつもと違う」を見つける",
           kicker="06  機能 3 / 4")

    add_text(s,
             "個別のログが普通でも、全体の傾向で「おかしさ」を検出します。",
             x=0.6, y=1.75, w=12, h=0.5, size=15, color=MUTED, italic=True)

    types = [
        ("🔥", "急増している", "平常の数十〜数千倍の\n動きが急に発生",
         "大量のパスワード試行"),
        ("🌐", "広がっている", "同じ動きが\n複数の PC で同時発生",
         "ウイルスが社内に拡大"),
        ("🤫", "急に静かに", "普段活動している PC が\n急にログを残さなくなる",
         "攻撃者がログを消した"),
        ("🌙", "時間外の活動", "深夜などの業務時間外に\n重要な動きが発生",
         "業務外を狙った侵入"),
    ]
    card_w = 2.95
    for i, (icon, name, cond, story) in enumerate(types):
        x = 0.6 + i * (card_w + 0.2)
        y = 2.45
        add_card(s, x, y, card_w, 3.35, fill=PANEL, accent_left=ACCENT)
        add_text(s, icon, x=x + 0.2, y=y + 0.2, w=1.0, h=0.7,
                 size=30, color=ACCENT)
        add_text(s, name, x=x + 0.2, y=y + 0.95, w=card_w - 0.3, h=0.5,
                 size=18, color=TEXT, font=FONT_HEAD, bold=True)
        add_text(s, cond, x=x + 0.2, y=y + 1.55, w=card_w - 0.4, h=0.9,
                 size=11, color=TEXT, line_spacing=1.4)
        add_text(s, "例: " + story, x=x + 0.2, y=y + 2.6, w=card_w - 0.4,
                 h=0.6, size=10, color=MUTED, italic=True, line_spacing=1.3)

    # 実例 highlight
    add_card(s, 0.6, 6.15, 12.1, 0.95, fill=PANEL_SOFT, line=PANEL_SOFT)
    add_text(s, "💡 実例:  ある PC で疑わしい動きが",
             x=1.7, y=6.15, w=3.9, h=0.95, size=14,
             color=TEXT, anchor=MSO_ANCHOR.MIDDLE)
    add_text(s, "いつもの 2,492 倍",
             x=5.65, y=6.15, w=2.5, h=0.95, size=19,
             color=ACCENT_DK, font=FONT_HEAD, bold=True,
             anchor=MSO_ANCHOR.MIDDLE)
    add_text(s, "発生していたのを自動検出。",
             x=8.15, y=6.15, w=4.2, h=0.95, size=14,
             color=TEXT, anchor=MSO_ANCHOR.MIDDLE)
    page_no(s, n, total)


def slide_feature_iocheck(prs, n, total):
    """9: 機能 ④ 既知の悪との照合."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "④  世界中の「悪いものリスト」と自動照合",
           kicker="07  機能 4 / 4")

    add_text(s, "セキュリティ研究者が日々まとめている",
             x=0.6, y=1.95, w=6.5, h=0.5, size=15, color=TEXT)
    add_text(s, "「既知の悪いもの」",
             x=0.6, y=2.5, w=6.5, h=0.6, size=26, color=TEXT,
             font=FONT_HEAD, bold=True)
    add_text(s, "を 自動で取り込みます。",
             x=0.6, y=3.15, w=6.5, h=0.5, size=18, color=ACCENT_DK)

    add_text(s, "もしあなたの PC でそれらに該当する動きがあれば、",
             x=0.6, y=4.2, w=6.5, h=0.4, size=14, color=TEXT)
    add_text(s, "即座に警告します。",
             x=0.6, y=4.7, w=6.5, h=0.5, size=18, color=CRIT, bold=True)

    add_text(s, "💡 リストはボタン一発、または自動で更新。",
             x=0.6, y=5.9, w=6.5, h=0.4, size=12, color=MUTED)
    add_text(s, "    常に最新の脅威情報で守られます。",
             x=0.6, y=6.25, w=6.5, h=0.4, size=12, color=MUTED)

    # 右: 数字の callout
    add_card(s, 7.3, 1.9, 5.45, 5.0, fill=PANEL, accent_left=ACCENT)
    add_text(s, "現在の取り込み実績",
             x=7.55, y=2.1, w=5.0, h=0.4, size=11, color=MUTED)

    add_text(s, "約 8 万",
             x=7.45, y=2.55, w=5.2, h=1.6,
             size=88, color=ACCENT_DK, font=FONT_HEAD, bold=True,
             align=PP_ALIGN.CENTER)
    add_text(s, "件の「既知の悪」を保持",
             x=7.45, y=4.2, w=5.2, h=0.5, size=15, color=TEXT,
             align=PP_ALIGN.CENTER)

    sources = [
        ("攻撃に使われる URL",            "約 78,000 件"),
        ("悪性プログラムの指紋 (ハッシュ)", "約 2,500 件"),
        ("乗っ取りに悪用されるドライバ",     "約 1,900 件"),
    ]
    sy = 5.0
    for name, count in sources:
        add_text(s, "• " + name, x=7.55, y=sy, w=3.9, h=0.35,
                 size=11, color=TEXT)
        add_text(s, count, x=11.0, y=sy, w=1.6, h=0.35,
                 size=11, color=ACCENT_DK, bold=True, align=PP_ALIGN.RIGHT)
        sy += 0.42
    page_no(s, n, total)


def slide_updates(prs, n, total):
    """10: 最新アップデート — 「使いやすさ」を磨いた 4 点."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "最近のアップデート — もっと「誰でも使える」へ",
           kicker="08  new!")

    updates = [
        ("🎨", "画面を全面リニューアル",
         "明るく親しみやすいデザインに一新。\nホーム画面の 3 ステップガイドと\n用語のその場解説で、初めてでも迷いません。"),
        ("⏳", "スキャンの進み具合が見える",
         "「あと何 %・残り何秒」を表示。\n長いスキャンも安心して待てます。\n途中でやめる「中止」ボタンも付きました。"),
        ("🗑", "履歴のお掃除機能",
         "要らなくなったスキャン結果を\nワンクリックで削除。\n「すべて消去」でまっさらにもできます。"),
        ("📦", "ダウンロードしてすぐ使える",
         "必要なもの全部入りの zip を配布開始。\n展開して start.ps1 を実行するだけ。\n難しい準備は一切不要になりました。"),
    ]
    card_w, card_h = 6.0, 2.3
    for i, (icon, title, body) in enumerate(updates):
        x = 0.6 + (i % 2) * (card_w + 0.25)
        y = 1.85 + (i // 2) * (card_h + 0.25)
        add_card(s, x, y, card_w, card_h, fill=PANEL, accent_left=ACCENT)
        add_text(s, icon, x=x + 0.25, y=y + 0.22, w=0.8, h=0.7,
                 size=28, color=ACCENT)
        add_text(s, title, x=x + 1.05, y=y + 0.25, w=card_w - 1.3, h=0.5,
                 size=17, color=TEXT, font=FONT_HEAD, bold=True)
        add_text(s, body, x=x + 1.05, y=y + 0.8, w=card_w - 1.35, h=1.4,
                 size=11.5, color=MUTED, line_spacing=1.4)

    add_text(s, "最新版 v0.1.1 を GitHub の Releases で公開中",
             x=0.6, y=6.75, w=12.1, h=0.4, size=12, color=ACCENT_DK,
             bold=True, align=PP_ALIGN.CENTER)
    page_no(s, n, total)


def slide_demo(prs, n, total):
    """11: デモ — フルブリードのセクション扉 (紺)."""
    s = add_slide(prs, NAVY)
    add_text(s, "DEMO", x=0.6, y=1.9, w=12, h=1.6,
             size=110, color=WHITE, font=FONT_HEAD, bold=True,
             align=PP_ALIGN.CENTER)
    add_text(s, "実際の画面で動かしてみます",
             x=0.6, y=4.35, w=12, h=0.6, size=24, color=ICE,
             italic=True, align=PP_ALIGN.CENTER)
    add_text(s, "サンプルログを読み込み、調査の流れを見ていただきます。",
             x=0.6, y=5.15, w=12, h=0.5, size=15, color=ICE,
             align=PP_ALIGN.CENTER)
    page_no(s, n, total, dark=True)


def slide_numbers(prs, n, total):
    """12: 規模感 — 親しみやすい 4 つの数字."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "数字で見ると", kicker="09  規模感")

    stats = [
        ("約5,000", "本",  "検知ルールを同梱",     ACCENT_DK),
        ("約8万",   "件",  "既知の悪いものリスト",  HIGH),
        ("30+",     "種類", "対応する攻撃の手口",   MED),
        ("0",       "個",  "追加で必要なソフト",    OK),
    ]
    card_w = 2.95
    for i, (num, unit, label, color) in enumerate(stats):
        x = 0.6 + i * (card_w + 0.2)
        y = 2.4
        add_card(s, x, y, card_w, 4.0, fill=PANEL, accent_left=color)
        add_text(s, num, x=x + 0.18, y=y + 0.55, w=card_w - 0.36, h=1.5,
                 size=44, color=color, font=FONT_HEAD, bold=True,
                 align=PP_ALIGN.CENTER)
        add_text(s, unit, x=x, y=y + 2.0, w=card_w, h=0.5,
                 size=24, color=TEXT, font=FONT_HEAD,
                 align=PP_ALIGN.CENTER)
        add_text(s, label, x=x + 0.2, y=y + 2.95, w=card_w - 0.4, h=0.9,
                 size=14, color=MUTED, align=PP_ALIGN.CENTER,
                 line_spacing=1.4)

    add_text(s, "個人で開発、すべて公開しています。",
             x=0.6, y=6.8, w=12, h=0.4, size=13, color=MUTED,
             italic=True, align=PP_ALIGN.CENTER)
    page_no(s, n, total)


def slide_thanks(prs, n, total):
    """13: 締め (紺) — 持ち帰りアクションを 1 つだけ."""
    s = add_slide(prs, NAVY)
    add_text(s, "ありがとうございました",
             x=0.6, y=1.5, w=12, h=1.2,
             size=56, color=WHITE, font=FONT_HEAD, bold=True,
             align=PP_ALIGN.CENTER)
    add_text(s, "ご質問・フィードバックをお願いします",
             x=0.6, y=2.7, w=12, h=0.6, size=22, color=ICE,
             italic=True, align=PP_ALIGN.CENTER)

    add_card(s, 2.8, 3.9, 7.7, 2.2, fill=NAVY_PANEL, line=NAVY_PANEL)
    add_text(s, "GitHub で公開中 — 今日から試せます", x=3.1, y=4.1, w=7.1,
             h=0.4, size=13, color=ICE)
    add_text(s, "github.com/Assy2005/hayabusa-plus",
             x=3.1, y=4.5, w=7.1, h=0.6, size=24,
             color=WHITE, font=FONT_MONO, bold=True)
    add_text(s, "Releases から zip をダウンロード → 展開 → start.ps1 を実行するだけ。",
             x=3.1, y=5.2, w=7.1, h=0.4, size=13, color=ICE)
    add_text(s, "どなたでも自由にお使いいただけます (OSS)",
             x=3.1, y=5.6, w=7.1, h=0.4, size=12, color=ICE, italic=True)

    add_text(s, "お手元の Windows PC のログで、ぜひ一度。",
             x=0.6, y=6.8, w=12, h=0.4, size=12, color=ICE,
             italic=True, align=PP_ALIGN.CENTER)


# ===========================================================================
# main
# ===========================================================================

def main():
    prs = new_pres()
    prs.title  = "hayabusa-plus (一般向け)"
    prs.author = "hayabusa-plus"

    total = 13
    slide_title(prs, total)                 # 1  — タイトル (番号なし)
    slide_question(prs, 2, total)           # 2  — 問いかけ
    slide_problem(prs, 3, total)            # 3  — 課題
    slide_solution(prs, 4, total)           # 4  — 解決策 (実画面)
    slide_steps(prs, 5, total)              # 5  — 使い方 3 ステップ (実画面)
    slide_feature_priority(prs, 6, total)   # 6  — 機能 ① (実画面)
    slide_feature_explain(prs, 7, total)    # 7  — 機能 ②
    slide_feature_anomaly(prs, 8, total)    # 8  — 機能 ③
    slide_feature_iocheck(prs, 9, total)    # 9  — 機能 ④
    slide_updates(prs, 10, total)           # 10 — 最新アップデート
    slide_demo(prs, 11, total)              # 11 — デモ
    slide_numbers(prs, 12, total)           # 12 — 数字
    slide_thanks(prs, total, total)         # 13 — ありがとう

    # PowerPoint で開いていると上書きが失敗するので、その場合は別ファイルに退避。
    out = Path(__file__).parent / "hayabusa-plus.pptx"
    try:
        prs.save(str(out))
        print(f"OK -> {out}")
    except PermissionError:
        alt = Path(__file__).parent / "hayabusa-plus.new.pptx"
        prs.save(str(alt))
        print(f"(target was locked) -> {alt}")
        print("→ PowerPoint を閉じてから build_deck.py を再実行するか、")
        print("   hayabusa-plus.new.pptx を hayabusa-plus.pptx に上書きしてください。")
    print(f"   slides: {len(prs.slides)}")


if __name__ == "__main__":
    main()
