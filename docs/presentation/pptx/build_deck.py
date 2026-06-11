"""
hayabusa-plus 研究発表用 PowerPoint (.pptx) 生成スクリプト — 一般向け版
======================================================================

13 枚構成。発表時間 10-12 分 (+ デモ 5 分 + Q&A 5 分) を想定。

「自分が Hayabusa の何をいじって、何の目的だったのか」を、専門知識の
ない聴衆にも伝わるストーリーで構成した研究発表向けの版です。
技術者向けの詳細版は build_deck_advanced.py を参照。

実行:
    python build_deck.py

出力:
    hayabusa-plus.pptx  (このスクリプトと同じディレクトリ)

構成 (研究発表の型):
    1. タイトル
    2-3. 背景   — 攻撃を受けたら? / 答えはログにあるが読めない
    4.   既存技術 — Hayabusa とは何か・何が課題か
    5.   目的   — 「専門家の道具」を「誰でも使える」に
    6.   全体像 — どこが既存で、どこを自分が開発したか
    7-10. 開発内容 — ①エンジン改造 ②ルール自作 ③GUI ④異常検知
    11.  デモ
    12.  まとめ — 成果の数字と今後
    13.  おわり
"""

from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

try:
    from PIL import Image
except ImportError:  # 画像サイズ取得に使う。無ければ固定比率で配置。
    Image = None


# ---------------------------------------------------------------------------
# カラーパレット (GUI と統一した明るい青基調)
# ---------------------------------------------------------------------------
BG_LIGHT    = RGBColor(0xF4, 0xF6, 0xFA)
PANEL       = RGBColor(0xFF, 0xFF, 0xFF)
PANEL_SOFT  = RGBColor(0xE8, 0xF0, 0xFE)
PANEL_GRAY  = RGBColor(0xE9, 0xEC, 0xF2)   # 「既存 OSS」を表すグレー
LINE        = RGBColor(0xDD, 0xE3, 0xEE)
ACCENT      = RGBColor(0x25, 0x63, 0xEB)   # 「自分が開発した部分」のブルー
ACCENT_DK   = RGBColor(0x1D, 0x4E, 0xD8)
TEXT        = RGBColor(0x1F, 0x29, 0x37)
MUTED       = RGBColor(0x5B, 0x64, 0x72)

NAVY        = RGBColor(0x1B, 0x25, 0x4F)
NAVY_PANEL  = RGBColor(0x27, 0x33, 0x66)
ICE         = RGBColor(0xCA, 0xDC, 0xFC)
WHITE       = RGBColor(0xFF, 0xFF, 0xFF)

CRIT        = RGBColor(0xDC, 0x26, 0x26)
HIGH        = RGBColor(0xEA, 0x58, 0x0C)
MED         = RGBColor(0xCA, 0x8A, 0x04)
OK          = RGBColor(0x16, 0xA3, 0x4A)

CODE_BG     = RGBColor(0x0F, 0x17, 0x2A)
CODE_DIM    = RGBColor(0x94, 0xA3, 0xB8)
CODE_TEXT   = RGBColor(0xCB, 0xD5, 0xE1)
CODE_HL     = RGBColor(0x7D, 0xD3, 0xFC)

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


def add_arrow_right(slide, x, y, w=0.55, h=0.4, color=MUTED):
    ar = slide.shapes.add_shape(
        MSO_SHAPE.RIGHT_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    ar.fill.solid(); ar.fill.fore_color.rgb = color
    ar.line.fill.background(); ar.shadow.inherit = False
    return ar


def add_arrow_up(slide, x, y, w=0.4, h=0.5, color=ACCENT):
    ar = slide.shapes.add_shape(
        MSO_SHAPE.UP_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    ar.fill.solid(); ar.fill.fore_color.rgb = color
    ar.line.fill.background(); ar.shadow.inherit = False
    return ar


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
    if ratio >= box_ratio:
        pw, ph = w, w / ratio
    else:
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
    add_text(slide, f"{n} / {total}", x=12.0, y=7.05, w=1.0, h=0.3,
             size=9, color=(ICE if dark else MUTED), align=PP_ALIGN.RIGHT)


def header(slide, title, *, kicker=None):
    if kicker:
        add_text(slide, kicker, x=0.6, y=0.38, w=12, h=0.3,
                 size=11, color=ACCENT, font=FONT_BODY, bold=True)
    add_text(slide, title, x=0.6, y=0.68, w=12.2, h=0.7,
             size=28, color=TEXT, font=FONT_HEAD, bold=True)


# ===========================================================================
# スライド定義
# ===========================================================================

def slide_title(prs, total):
    """1: タイトル (紺) — 研究発表らしいタイトルで「何をしたか」を言い切る."""
    s = add_slide(prs, NAVY)

    add_text(s, "OSS 解析エンジン「Hayabusa」の拡張による",
             x=0.6, y=1.5, w=12, h=0.6, size=26, color=ICE,
             font=FONT_HEAD, align=PP_ALIGN.CENTER)
    add_text(s, "誰でも使えるサイバー攻撃調査ツールの開発",
             x=0.6, y=2.15, w=12, h=1.0, size=40, color=WHITE,
             font=FONT_HEAD, bold=True, align=PP_ALIGN.CENTER)

    add_text(s, "— サイバー攻撃の痕跡を、誰でも読めるように —",
             x=0.6, y=3.55, w=12, h=0.6, size=20, color=ICE,
             italic=True, align=PP_ALIGN.CENTER)

    # 3 行サマリ: 何をいじったか
    add_card(s, 2.9, 4.6, 7.5, 1.7, fill=NAVY_PANEL, line=NAVY_PANEL)
    lines = [
        "🦀 エンジン本体 (Rust) に新しい検知機能を追加",
        "📜 攻撃を見抜く検知ルールを 13 本自作",
        "🖥️ 結果を読み解ける GUI をゼロから開発 (約 8,000 行)",
    ]
    ly = 4.78
    for line in lines:
        add_text(s, line, x=3.35, y=ly, w=6.8, h=0.45, size=14, color=WHITE)
        ly += 0.46

    add_text(s, "プロジェクト名: hayabusa-plus   /   github.com/Assy2005/hayabusa-plus",
             x=0.6, y=6.8, w=12, h=0.4, size=13, color=ICE,
             font=FONT_MONO, align=PP_ALIGN.CENTER)


def slide_question(prs, n, total):
    """2: 背景 (紺) — 自分事に変える問いかけ."""
    s = add_slide(prs, NAVY)

    add_text(s, "背景", x=0.6, y=0.45, w=3, h=0.45, size=15, color=ICE, bold=True)

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
    """3: 背景 — 答えはログにあるが、量が多すぎて読めない."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "答えは Windows のログの中にある", kicker="背景")

    add_card(s, 0.6, 1.75, 6.4, 5.1, fill=CODE_BG, line=CODE_BG)
    add_text(s, "Windows のログ (実例)", x=1.0, y=2.0, w=5.8, h=0.3,
             size=10, color=CODE_DIM, font=FONT_MONO)

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
                 size=10, color=CODE_TEXT, font=FONT_MONO)
        ly += 0.41

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


def slide_hayabusa(prs, n, total):
    """4: 既存技術 — Hayabusa とは何か、何が課題か."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "土台にした既存ツール: Hayabusa", kicker="既存技術")

    add_text(s, "日本のセキュリティチーム Yamato Security が公開している無料ツール (OSS)。",
             x=0.6, y=1.7, w=12.1, h=0.45, size=15, color=MUTED, italic=True)

    # 左: できること
    add_card(s, 0.6, 2.3, 6.0, 4.4, fill=PANEL, accent_left=OK)
    add_text(s, "✅ Hayabusa ができること", x=0.9, y=2.55, w=5.5, h=0.45,
             size=17, color=TEXT, font=FONT_HEAD, bold=True)
    haya_can = [
        ("世界中の研究者が作った「攻撃の特徴パターン」",
         "(Sigma ルール・約 5,000 本) と照合"),
        ("数万件のログを数十秒〜数分で全チェック",
         "(Rust 製で高速)"),
        ("世界中の調査現場で使われている実績",
         ""),
    ]
    cy = 3.2
    for main, sub in haya_can:
        add_text(s, "• " + main, x=0.9, y=cy, w=5.4, h=0.45,
                 size=13, color=TEXT, line_spacing=1.3)
        if sub:
            add_text(s, "   " + sub, x=0.9, y=cy + 0.42, w=5.4, h=0.4,
                     size=11.5, color=MUTED)
            cy += 0.95
        else:
            cy += 0.55

    # 右: 課題
    add_card(s, 6.85, 2.3, 6.0, 4.4, fill=PANEL, accent_left=HIGH)
    add_text(s, "⚠ そのままでは専門家にしか使えない", x=7.15, y=2.55, w=5.6,
             h=0.45, size=17, color=TEXT, font=FONT_HEAD, bold=True)
    issues = [
        "黒い画面でコマンドを打つ必要がある",
        "結果は CSV ファイル数万行 — 結局「読めない」",
        "出力は英語 + 専門用語だらけ",
        "「で、次にどうすれば?」を教えてくれない",
    ]
    cy = 3.2
    for it in issues:
        add_text(s, "• " + it, x=7.15, y=cy, w=5.5, h=0.5,
                 size=13, color=TEXT, line_spacing=1.3)
        cy += 0.62

    add_text(s, "→ この「強力だが使いにくい」を出発点にしました",
             x=0.6, y=6.85, w=12.1, h=0.4, size=14, color=ACCENT_DK,
             bold=True, align=PP_ALIGN.CENTER)
    page_no(s, n, total)


def slide_goal(prs, n, total):
    """5: 目的 — 専門家の道具を、誰でも使えるプラットフォームに."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "目的", kicker="この開発で目指したこと")

    add_text(s, "「専門家の道具」を",
             x=0.6, y=1.9, w=12, h=0.6, size=24, color=MUTED,
             align=PP_ALIGN.CENTER)
    add_text(s, "「誰でも使える調査プラットフォーム」に",
             x=0.6, y=2.5, w=12, h=0.8, size=32, color=TEXT,
             font=FONT_HEAD, bold=True, align=PP_ALIGN.CENTER)

    # 3 つの開発方針 = そのまま「やったこと」の章立て
    plans = [
        ("①", "見つける力を強くする",
         "エンジン本体を改造して\n新しい検知機能を追加 +\n検知ルールを自作"),
        ("②", "結果を読めるようにする",
         "ブラウザで見られる GUI を\nゼロから開発。日本語解説と\n「次にすべきこと」を表示"),
        ("③", "手元だけで完結させる",
         "データを外部に送らない。\n追加ソフト無しで動く\n(オフライン・依存ゼロ)"),
    ]
    card_w = 3.9
    for i, (num, title, body) in enumerate(plans):
        x = 0.6 + i * (card_w + 0.25)
        y = 3.8
        add_card(s, x, y, card_w, 2.7, fill=PANEL, accent_left=ACCENT)
        add_text(s, num, x=x + 0.25, y=y + 0.2, w=0.7, h=0.6,
                 size=28, color=ACCENT, font=FONT_HEAD, bold=True)
        add_text(s, title, x=x + 0.9, y=y + 0.28, w=card_w - 1.1, h=0.5,
                 size=16, color=TEXT, font=FONT_HEAD, bold=True)
        add_text(s, body, x=x + 0.3, y=y + 0.95, w=card_w - 0.55, h=1.6,
                 size=12, color=MUTED, line_spacing=1.45)

    page_no(s, n, total)


def slide_overview(prs, n, total):
    """6: 全体像 — どこが既存 OSS で、どこを自分が開発したか."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "作ったものの全体像", kicker="どこを開発したか")

    # 凡例
    lg1 = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(8.4), Inches(0.5),
                             Inches(0.28), Inches(0.28))
    lg1.fill.solid(); lg1.fill.fore_color.rgb = PANEL_GRAY
    lg1.line.color.rgb = LINE; lg1.shadow.inherit = False
    add_text(s, "= 既存 OSS (土台)", x=8.75, y=0.5, w=1.8, h=0.3,
             size=11, color=MUTED, anchor=MSO_ANCHOR.MIDDLE)
    lg2 = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(10.6), Inches(0.5),
                             Inches(0.28), Inches(0.28))
    lg2.fill.solid(); lg2.fill.fore_color.rgb = PANEL_SOFT
    lg2.line.color.rgb = ACCENT; lg2.shadow.inherit = False
    add_text(s, "= 今回開発した部分", x=10.95, y=0.5, w=2.0, h=0.3,
             size=11, color=ACCENT_DK, bold=True, anchor=MSO_ANCHOR.MIDDLE)

    # ---- メインフロー: ログ → エンジン → GUI → 人 ----
    flow_y = 2.3
    # ログ
    add_card(s, 0.6, flow_y, 2.4, 1.9, fill=PANEL, line=LINE)
    add_text(s, "📄", x=0.6, y=flow_y + 0.2, w=2.4, h=0.6, size=28,
             align=PP_ALIGN.CENTER)
    add_text(s, "Windows のログ", x=0.6, y=flow_y + 0.85, w=2.4, h=0.4,
             size=13, color=TEXT, bold=True, align=PP_ALIGN.CENTER)
    add_text(s, "数万件", x=0.6, y=flow_y + 1.25, w=2.4, h=0.35,
             size=11, color=MUTED, align=PP_ALIGN.CENTER)

    add_arrow_right(s, 3.15, flow_y + 0.75)

    # エンジン (グレー = 既存) + 青バッジ (lookup 拡張)
    add_card(s, 3.85, flow_y, 3.6, 1.9, fill=PANEL_GRAY, line=LINE)
    add_text(s, "Hayabusa エンジン", x=3.85, y=flow_y + 0.22, w=3.6, h=0.4,
             size=14, color=TEXT, bold=True, align=PP_ALIGN.CENTER)
    add_text(s, "(既存 OSS・Rust 製)", x=3.85, y=flow_y + 0.6, w=3.6, h=0.35,
             size=11, color=MUTED, align=PP_ALIGN.CENTER)
    badge = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                               Inches(4.15), Inches(flow_y + 1.05),
                               Inches(3.0), Inches(0.6))
    badge.fill.solid(); badge.fill.fore_color.rgb = PANEL_SOFT
    badge.line.color.rgb = ACCENT; badge.line.width = Pt(1.25)
    badge.shadow.inherit = False
    add_text(s, "★ 中身を改造して新機能を追加", x=4.15, y=flow_y + 1.05,
             w=3.0, h=0.6, size=11.5, color=ACCENT_DK, bold=True,
             align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

    add_arrow_right(s, 7.6, flow_y + 0.75)

    # GUI (青 = 自作)
    gui = add_card(s, 8.3, flow_y, 3.0, 1.9, fill=PANEL_SOFT, line=LINE)
    gui.line.color.rgb = ACCENT; gui.line.width = Pt(1.5)
    add_text(s, "🖥️", x=8.3, y=flow_y + 0.18, w=3.0, h=0.55, size=24,
             align=PP_ALIGN.CENTER)
    add_text(s, "調査用 GUI", x=8.3, y=flow_y + 0.78, w=3.0, h=0.4,
             size=14, color=ACCENT_DK, bold=True, align=PP_ALIGN.CENTER)
    add_text(s, "ゼロから開発 (約 8,000 行)", x=8.3, y=flow_y + 1.2, w=3.0,
             h=0.35, size=11, color=MUTED, align=PP_ALIGN.CENTER)

    add_arrow_right(s, 11.45, flow_y + 0.75)

    add_text(s, "🧑‍💻", x=11.95, y=flow_y + 0.35, w=1.0, h=0.7, size=34,
             align=PP_ALIGN.CENTER)
    add_text(s, "調べる人", x=11.85, y=flow_y + 1.1, w=1.2, h=0.4,
             size=12, color=TEXT, bold=True, align=PP_ALIGN.CENTER)

    # ---- エンジンへ注ぎ込む 2 つの自作要素 (下から上矢印) ----
    feed_y = 5.3
    add_card(s, 2.5, feed_y, 3.0, 1.5, fill=PANEL_SOFT, line=LINE
             ).line.color.rgb = ACCENT
    add_text(s, "📜 自作の検知ルール", x=2.5, y=feed_y + 0.2, w=3.0, h=0.4,
             size=13, color=ACCENT_DK, bold=True, align=PP_ALIGN.CENTER)
    add_text(s, "13 本 (痕跡隠蔽の検知など)", x=2.5, y=feed_y + 0.65, w=3.0,
             h=0.4, size=11, color=MUTED, align=PP_ALIGN.CENTER)

    add_card(s, 5.9, feed_y, 3.0, 1.5, fill=PANEL_SOFT, line=LINE
             ).line.color.rgb = ACCENT
    add_text(s, "🌐 悪いものリスト", x=5.9, y=feed_y + 0.2, w=3.0, h=0.4,
             size=13, color=ACCENT_DK, bold=True, align=PP_ALIGN.CENTER)
    add_text(s, "約 8 万件を自動で取り込み", x=5.9, y=feed_y + 0.65, w=3.0,
             h=0.4, size=11, color=MUTED, align=PP_ALIGN.CENTER)

    add_arrow_up(s, 3.8, 4.45, color=ACCENT)
    add_arrow_up(s, 7.2, 4.45, color=ACCENT)

    page_no(s, n, total)


def slide_dev_engine(prs, n, total):
    """7: 開発① エンジン改造 (Rust) — lookup: 拡張."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "①  エンジン本体の改造 — 新しい文法を追加",
           kicker="開発内容 1 / 3   (Rust)")

    add_text(s, "Hayabusa の「ルールの書き方」自体を拡張しました。",
             x=0.6, y=1.85, w=6.3, h=0.5, size=16, color=TEXT, bold=True)

    add_text(s, "ルールに 1 行、",
             x=0.6, y=2.6, w=6.3, h=0.45, size=15, color=TEXT)
    add_text(s, "「このリストに載っていたら警告して」",
             x=0.6, y=3.05, w=6.3, h=0.6, size=21, color=ACCENT_DK,
             font=FONT_HEAD, bold=True)
    add_text(s, "と書けるようにする機能 (lookup:) を、",
             x=0.6, y=3.7, w=6.3, h=0.45, size=15, color=TEXT)
    add_text(s, "エンジンのソースコード (Rust) に追加。",
             x=0.6, y=4.15, w=6.3, h=0.45, size=15, color=TEXT)

    add_card(s, 0.6, 5.0, 6.3, 1.75, fill=PANEL_SOFT, line=PANEL_SOFT)
    add_text(s, "💡 これで何が嬉しい?", x=0.85, y=5.18, w=5.9, h=0.4,
             size=12.5, color=TEXT, bold=True)
    add_text(s, "世界中で共有されている「悪いものリスト」(約 8 万件) を、\nルールを書き換えずにそのまま検知に使えるようになった。",
             x=0.85, y=5.62, w=5.9, h=0.95, size=12, color=MUTED,
             line_spacing=1.45)

    # 右: ルールの実例 (簡略化)
    add_card(s, 7.3, 1.85, 5.45, 3.4, fill=CODE_BG, line=CODE_BG)
    add_text(s, "自作ルールの実例 (簡略化)", x=7.6, y=2.05, w=4.9, h=0.3,
             size=10, color=CODE_DIM, font=FONT_MONO)
    code_lines = [
        ("title: 危険なドライバの読み込みを検知", CODE_TEXT),
        ("lookup:", CODE_HL),
        ("  file: loldrivers.txt   # 悪い指紋 1,929 件", CODE_HL),
        ("detection:", CODE_TEXT),
        ("  Hashes|lookup: lol_drivers", CODE_HL),
        ("            ↑ 追加した新しい文法", CODE_DIM),
        ("level: critical", CODE_TEXT),
    ]
    cy = 2.5
    for text, color in code_lines:
        add_text(s, text, x=7.6, y=cy, w=4.9, h=0.34,
                 size=11.5, color=color, font=FONT_MONO)
        cy += 0.39

    # 右下: 照合フロー
    add_card(s, 7.3, 5.5, 5.45, 1.25, fill=PANEL, accent_left=ACCENT)
    add_text(s, "ログ 1 件ごとにリスト 8 万件と照合しても速度が落ちない",
             x=7.55, y=5.68, w=5.0, h=0.45, size=12, color=TEXT, bold=True)
    add_text(s, "よう、起動時に一度だけ読み込んで記憶する設計 (Rust)。",
             x=7.55, y=6.12, w=5.0, h=0.45, size=12, color=MUTED)

    page_no(s, n, total)


def slide_dev_rules(prs, n, total):
    """8: 開発② 検知ルールの自作 — 痕跡を消す行為を逆に手がかりに."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "②  攻撃を見抜く検知ルールを 13 本自作",
           kicker="開発内容 2 / 3   (検知ルール)")

    add_text(s, "着眼点: 攻撃者は必ず「証拠隠し」をする。なら、消す行為そのものを検知すればいい。",
             x=0.6, y=1.8, w=12.1, h=0.5, size=15, color=ACCENT_DK,
             bold=True, italic=True)

    types = [
        ("🧹", "ログの消去", "調査の手がかりになる\nログを消すコマンドの実行",
         "wevtutil 等"),
        ("💣", "復元データの削除", "バックアップを消す行為\n(ランサムウェアの前兆)",
         "シャドウコピー削除"),
        ("🙈", "監視の無効化", "ログを記録する機能や\n監査そのものを止める行為",
         "監査ポリシー改変"),
        ("🔑", "パスワード抜き取り", "Windows が記憶している\n認証情報への不正アクセス",
         "LSASS ダンプ"),
    ]
    card_w = 2.95
    for i, (icon, name, cond, tech) in enumerate(types):
        x = 0.6 + i * (card_w + 0.2)
        y = 2.5
        add_card(s, x, y, card_w, 3.2, fill=PANEL, accent_left=ACCENT)
        add_text(s, icon, x=x + 0.2, y=y + 0.2, w=1.0, h=0.7,
                 size=30, color=ACCENT)
        add_text(s, name, x=x + 0.2, y=y + 0.95, w=card_w - 0.3, h=0.5,
                 size=17, color=TEXT, font=FONT_HEAD, bold=True)
        add_text(s, cond, x=x + 0.2, y=y + 1.5, w=card_w - 0.4, h=0.95,
                 size=11, color=TEXT, line_spacing=1.4)
        add_text(s, "(" + tech + ")", x=x + 0.2, y=y + 2.55, w=card_w - 0.4,
                 h=0.4, size=10, color=MUTED, italic=True)

    add_card(s, 0.6, 6.0, 12.1, 0.95, fill=PANEL_SOFT, line=PANEL_SOFT)
    add_text(s, "誤検知を減らす工夫:  1 つの特徴では鳴らさず、複数の特徴が同時に揃ったときだけ警告する設計に。",
             x=0.95, y=6.0, w=11.5, h=0.95, size=13.5, color=TEXT,
             anchor=MSO_ANCHOR.MIDDLE)
    page_no(s, n, total)


def slide_dev_gui(prs, n, total):
    """9: 開発③ GUI — 結果を「読める」にする画面をゼロから開発."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "③  結果を「読める」にする GUI をゼロから開発",
           kicker="開発内容 3 / 3   (Python + JavaScript 約 8,000 行)")

    points = [
        ("🇯🇵", "日本語の解説付き",
         "検知をクリックすると「何が起きた?\n次にどうする?」を日本語で表示"),
        ("🚨", "危険度ランキング",
         "どの PC から調べるべきかを\n自動採点して並べ替え"),
        ("📊", "全体が一目で",
         "重大度・時間の流れ・多い攻撃を\nグラフで俯瞰"),
    ]
    cy = 1.95
    for icon, title, body in points:
        add_card(s, 0.6, cy, 5.3, 1.5, fill=PANEL, accent_left=ACCENT)
        add_text(s, icon, x=0.85, y=cy + 0.18, w=0.8, h=0.7,
                 size=26, color=ACCENT)
        add_text(s, title, x=1.7, y=cy + 0.16, w=4.0, h=0.45,
                 size=16, color=TEXT, font=FONT_HEAD, bold=True)
        add_text(s, body, x=1.7, y=cy + 0.62, w=4.05, h=0.8,
                 size=11, color=MUTED, line_spacing=1.35)
        cy += 1.7

    # 右: ダッシュボード実画面
    add_screenshot(s, "dashboard", x=6.3, y=1.85, w=6.45, h=5.0)
    add_text(s, "▲ 実際の画面 (ブラウザで動作・データは外部に送らない)",
             x=6.3, y=6.9, w=6.45, h=0.35, size=11, color=MUTED,
             align=PP_ALIGN.CENTER)

    page_no(s, n, total)


def slide_dev_anomaly(prs, n, total):
    """10: 開発③+ — ルールでは書けない「いつもと違う」も自作の分析で検出."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "さらに: ルールでは書けない「いつもと違う」も検出",
           kicker="開発内容 +α   (自作の統計分析)")

    add_text(s,
             "ルールは 1 件ずつしか判定できない。そこで「全体の傾向」を統計で見る分析を自作しました。",
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
        add_card(s, x, y, card_w, 2.85, fill=PANEL, accent_left=ACCENT)
        add_text(s, icon, x=x + 0.2, y=y + 0.16, w=1.0, h=0.62,
                 size=26, color=ACCENT)
        add_text(s, name, x=x + 0.2, y=y + 0.8, w=card_w - 0.3, h=0.5,
                 size=17, color=TEXT, font=FONT_HEAD, bold=True)
        add_text(s, cond, x=x + 0.2, y=y + 1.33, w=card_w - 0.4, h=0.9,
                 size=11, color=TEXT, line_spacing=1.4)
        add_text(s, "例: " + story, x=x + 0.2, y=y + 2.28, w=card_w - 0.4,
                 h=0.5, size=10, color=MUTED, italic=True, line_spacing=1.3)

    # ---- 締め: ルール検知との違いを対比で示す (データの主張はしない) ----
    add_card(s, 0.6, 5.5, 12.1, 1.5, fill=PANEL_SOFT, line=PANEL_SOFT)

    add_text(s, "📏 ルールによる検知 (既存の方法)",
             x=1.0, y=5.72, w=5.4, h=0.4, size=13.5, color=TEXT, bold=True)
    add_text(s, "事前に知っている「悪い特徴」と一致したら警告。\n既に知られている手口には確実で強い。",
             x=1.0, y=6.14, w=5.4, h=0.75, size=11.5, color=MUTED,
             line_spacing=1.4)

    # 中央の区切り線
    div = s.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                             Inches(6.62), Inches(5.75),
                             Inches(0.018), Inches(1.0))
    div.fill.solid(); div.fill.fore_color.rgb = LINE
    div.line.fill.background(); div.shadow.inherit = False

    add_text(s, "📈 振舞いによる検知 (今回自作した分析)",
             x=7.0, y=5.72, w=5.4, h=0.4, size=13.5, color=ACCENT_DK,
             bold=True)
    add_text(s, "「普段との違い」に反応して知らせる。\nルールがまだ無い未知の手口への「気づき」になる。",
             x=7.0, y=6.14, w=5.4, h=0.75, size=11.5, color=MUTED,
             line_spacing=1.4)
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


def slide_summary(prs, n, total):
    """12: まとめ — やったこと 4 つの数字 + 今後."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "まとめ — 開発したもの", kicker="成果")

    stats = [
        ("新文法",   "lookup:", "エンジン本体 (Rust) を改造し\nリスト照合機能を追加", ACCENT_DK),
        ("13",      "本",      "攻撃を見抜く検知ルールを\n自作 (痕跡隠蔽の検知など)", HIGH),
        ("約8,000", "行",      "結果を読み解く GUI を\nゼロから開発",               MED),
        ("約8万",   "件",      "「悪いものリスト」を\n自動で取り込んで照合",          OK),
    ]
    card_w = 2.95
    for i, (num, unit, label, color) in enumerate(stats):
        x = 0.6 + i * (card_w + 0.2)
        y = 1.95
        add_card(s, x, y, card_w, 3.6, fill=PANEL, accent_left=color)
        add_text(s, num, x=x + 0.18, y=y + 0.45, w=card_w - 0.36, h=1.1,
                 size=40, color=color, font=FONT_HEAD, bold=True,
                 align=PP_ALIGN.CENTER)
        add_text(s, unit, x=x, y=y + 1.55, w=card_w, h=0.5,
                 size=20, color=TEXT, font=FONT_HEAD,
                 align=PP_ALIGN.CENTER)
        add_text(s, label, x=x + 0.2, y=y + 2.25, w=card_w - 0.4, h=1.1,
                 size=12, color=MUTED, align=PP_ALIGN.CENTER,
                 line_spacing=1.4)

    add_card(s, 0.6, 5.95, 12.1, 1.1, fill=PANEL_SOFT, line=PANEL_SOFT)
    add_text(s, "🚀 今後:  時間の流れを追った相関分析 (「A の後に B が起きたら怪しい」) や、AI による検知ルールの自動生成へ。",
             x=0.95, y=5.95, w=11.5, h=1.1, size=14, color=TEXT,
             anchor=MSO_ANCHOR.MIDDLE)
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
    add_text(s, "成果物はすべて GitHub で公開しています", x=3.1, y=4.1, w=7.1,
             h=0.4, size=13, color=ICE)
    add_text(s, "github.com/Assy2005/hayabusa-plus",
             x=3.1, y=4.5, w=7.1, h=0.6, size=24,
             color=WHITE, font=FONT_MONO, bold=True)
    add_text(s, "ソースコード・検知ルール・設計書・この資料まで、どなたでも使えます (OSS)。",
             x=3.1, y=5.2, w=7.1, h=0.4, size=13, color=ICE)
    add_text(s, "zip をダウンロード → 展開 → 実行、ですぐ試せます",
             x=3.1, y=5.6, w=7.1, h=0.4, size=12, color=ICE, italic=True)

    add_text(s, "お手元の Windows PC のログで、ぜひ一度。",
             x=0.6, y=6.8, w=12, h=0.4, size=12, color=ICE,
             italic=True, align=PP_ALIGN.CENTER)


# ===========================================================================
# main
# ===========================================================================

def main():
    prs = new_pres()
    prs.title  = "hayabusa-plus (研究発表・一般向け)"
    prs.author = "hayabusa-plus"

    total = 13
    slide_title(prs, total)             # 1  — タイトル (番号なし)
    slide_question(prs, 2, total)       # 2  — 背景: 攻撃を受けたら?
    slide_problem(prs, 3, total)        # 3  — 背景: ログは読めない
    slide_hayabusa(prs, 4, total)       # 4  — 既存技術: Hayabusa と課題
    slide_goal(prs, 5, total)           # 5  — 目的
    slide_overview(prs, 6, total)       # 6  — 全体像 (既存 vs 自作)
    slide_dev_engine(prs, 7, total)     # 7  — 開発① エンジン改造
    slide_dev_rules(prs, 8, total)      # 8  — 開発② ルール自作
    slide_dev_gui(prs, 9, total)        # 9  — 開発③ GUI
    slide_dev_anomaly(prs, 10, total)   # 10 — 開発+α 異常検知
    slide_demo(prs, 11, total)          # 11 — デモ
    slide_summary(prs, 12, total)       # 12 — まとめ
    slide_thanks(prs, total, total)     # 13 — おわり

    # PowerPoint で開いていると上書きが失敗するので、空いている名前に退避する。
    base = Path(__file__).parent
    candidates = [base / "hayabusa-plus.pptx",
                  base / "hayabusa-plus.new.pptx"]
    candidates += [base / f"hayabusa-plus.new{i}.pptx" for i in range(2, 6)]
    for out in candidates:
        try:
            prs.save(str(out))
            if out.name != "hayabusa-plus.pptx":
                print(f"(hayabusa-plus.pptx was locked) -> {out}")
                print("→ PowerPoint を閉じてから再実行すると本来の名前で保存されます。")
            else:
                print(f"OK -> {out}")
            break
        except PermissionError:
            continue
    else:
        raise SystemExit("すべての保存先がロックされています。PowerPoint を閉じてください。")
    print(f"   slides: {len(prs.slides)}")


if __name__ == "__main__":
    main()
