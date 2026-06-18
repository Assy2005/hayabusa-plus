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
    7.   開発① エンジン改造 — lookup: という新しい文法を追加
    8.   ↑の内部フロー — loldrivers.io から検知までを 1 枚で追う
    9.   開発② ルール自作
    10.  ↑の中身 — 各ルールがログのどこを見ているか (wevtutil 等)
    11.  開発③ GUI
    12.  開発+α 異常検知
    13.  検証 — 実測で効果を示す (lookup 検証 + サンプル検知)
    14.  デモ
    15.  まとめ — 成果の数字と今後
    16.  おわり
    付録. 検知ルール 13 本一覧 / 想定問答 (Q&A) ×3
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
DEMO_VIDEO = Path(__file__).resolve().parents[2] / "demo" / "hayabusa-plus-demo.mp4"
DEMO_POSTER = IMG_DIR / "dashboard.png"                    # 動画のサムネ


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
        "🖥️ 結果を読み解ける GUI をゼロから開発",
    ]
    ly = 4.78
    for line in lines:
        add_text(s, line, x=3.35, y=ly, w=6.8, h=0.45, size=14, color=WHITE)
        ly += 0.46

    # 発表者情報 (研究発表会の体裁)。氏名・所属はビルド時にここを編集する。
    add_text(s, "発表者: 島崎朝日   ・   所属: 小林研究室",
             x=0.6, y=6.5, w=12, h=0.4, size=16, color=WHITE, align=PP_ALIGN.CENTER)
    add_text(s, "プロジェクト名: hayabusa-plus   /   github.com/Assy2005/hayabusa-plus",
             x=0.6, y=6.95, w=12, h=0.35, size=12, color=ICE,
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
    add_text(s, "ゼロから開発", x=8.3, y=flow_y + 1.2, w=3.0,
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
        ("  - name: lol_drivers", CODE_HL),
        ("    file: loldrivers.txt  # 悪い指紋 1,929 件", CODE_HL),
        ("detection:", CODE_TEXT),
        ("  Hashes|lookup: lol_drivers", CODE_HL),
        ("           ↑ 追加した新しい文法", CODE_DIM),
        ("level: critical", CODE_TEXT),
    ]
    cy = 2.45
    for text, color in code_lines:
        add_text(s, text, x=7.6, y=cy, w=4.9, h=0.34,
                 size=11.5, color=color, font=FONT_MONO)
        cy += 0.355

    # 右下: リストの出どころ + 次ページへの誘導
    add_card(s, 7.3, 5.5, 5.45, 1.25, fill=PANEL, accent_left=ACCENT)
    add_text(s, "この「悪い指紋リスト」は世界中の研究者が集めた公開情報",
             x=7.55, y=5.66, w=5.0, h=0.45, size=12, color=TEXT, bold=True)
    add_text(s, "(例: loldrivers.io の悪用ドライバ一覧)。出どころと処理の",
             x=7.55, y=6.07, w=5.0, h=0.4, size=11.5, color=MUTED)
    add_text(s, "流れは次ページで説明します。",
             x=7.55, y=6.41, w=5.0, h=0.4, size=11.5, color=MUTED)

    page_no(s, n, total)


def slide_lookup_flow(prs, n, total):
    """8: 開発① の内部フロー — loldrivers.io から critical 検知までを 1 枚で追う.

    レビューで「lookup が実際に何をしているのか／内部フローを説明して」と
    求められた点に答えるスライド。具体例として BYOVD (悪用される脆弱
    ドライバの読み込み) 検知の経路を、源泉 (loldrivers.io) → 取得整形 →
    起動時ロード → 1 件ごとの照合 → 検知、の 5 段で示す。
    """
    s = add_slide(prs, BG_LIGHT)
    header(s, "lookup の内部フロー — リストはどこから来て、どう照合されるか",
           kicker="開発内容① の中身   (内部フロー)")

    add_text(s, "具体例: 「悪用される脆弱ドライバの読み込み (BYOVD)」を検知するまでの流れ。",
             x=0.6, y=1.78, w=12.1, h=0.45, size=14, color=MUTED, italic=True)

    def flow_card(x, y, w, h, icon, title, body, *, tag=None,
                  accent=ACCENT, title_color=TEXT):
        add_card(s, x, y, w, h, fill=PANEL, accent_left=accent)
        add_text(s, icon, x=x + 0.22, y=y + 0.16, w=0.8, h=0.6,
                 size=23, color=accent)
        add_text(s, title, x=x + 0.92, y=y + 0.2, w=w - 1.05, h=0.5,
                 size=14.5, color=title_color, font=FONT_HEAD, bold=True)
        add_text(s, body, x=x + 0.24, y=y + 0.8, w=w - 0.45, h=h - 1.2,
                 size=11, color=MUTED, line_spacing=1.32)
        if tag:
            add_text(s, tag, x=x + 0.24, y=y + h - 0.38, w=w - 0.45, h=0.32,
                     size=10, color=accent, bold=True, font=FONT_MONO)

    # ---- 準備フェーズ (スキャン前に 1 回) : 源泉 → 取得整形 → 起動時ロード ----
    ty, th = 2.3, 2.05
    flow_card(0.6, ty, 3.5, th, "🌐", "loldrivers.io",
              "世界中の研究者が集めた\n「悪用される脆弱ドライバ」の\nハッシュ一覧 (誰でも入手可・無料)",
              tag="出どころ (Source)")
    add_arrow_right(s, 4.16, ty + 0.82, w=0.5)
    flow_card(4.72, ty, 3.5, th, "⬇", "取得して整形",
              "CSV を取得し、1 行 1 ハッシュの\nテキストに変換して保存する\n(GUI のボタン 1 つで実行)",
              tag="→ loldrivers.txt (1,929 件)")
    add_arrow_right(s, 8.28, ty + 0.82, w=0.5)
    flow_card(8.84, ty, 3.5, th, "🦀", "起動時に記憶",
              "エンジン起動時に一度だけ読み込み、\nメモリ上の高速な表に保持する\n(RwLock<HashMap>)",
              tag="Rust・読み込みは起動時の 1 回だけ")

    # ---- 準備 → 実行の橋渡し (下向き矢印) ----
    da = s.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Inches(6.45),
                            Inches(4.45), Inches(0.45), Inches(0.42))
    da.fill.solid(); da.fill.fore_color.rgb = ACCENT
    da.line.fill.background(); da.shadow.inherit = False
    add_text(s, "スキャン実行中 — ログを 1 件ずつ処理", x=7.05, y=4.5,
             w=5.5, h=0.4, size=12, color=ACCENT_DK, italic=True, bold=True)

    # ---- 実行フェーズ (ログ 1 件ごと) : 照合 → 検知 ----
    by, bh = 4.95, 1.55
    flow_card(1.4, by, 4.7, bh, "🔍", "ログ 1 件ごとに照合",
              "Sysmon EID 6 (ドライバ読込) の\nハッシュを、記憶した表と突合。\n1 件あたりほぼ一瞬 (O(1))")
    add_arrow_right(s, 6.18, by + 0.55, w=0.55)
    flow_card(6.95, by, 4.7, bh, "🚨", "一致したら critical 通知",
              "既知の悪用ドライバが読み込まれた\n= BYOVD 攻撃の痕跡。\n最高レベル (critical) で警告。",
              accent=CRIT, title_color=CRIT)

    add_text(s,
             "ポイント:  リストが何万件に増えても照合速度は一定。ルール本文は 1 行のまま、"
             "リスト側を更新するだけで最新の脅威に追従できる。",
             x=0.6, y=6.62, w=12.1, h=0.4, size=11.5, color=ACCENT_DK, bold=True)

    page_no(s, n, total)


def slide_dev_rules(prs, n, total):
    """9: 開発② 検知ルールの自作 — 痕跡を消す行為を逆に手がかりに."""
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


def slide_rules_internals(prs, n, total):
    """10: 開発② の中身 — 4 つのルールが実際にログのどこを見ているか.

    レビューで「wevtutil などが攻撃にどう影響し、ルールがどう捕まえるのか」
    を問われた点に答える 1 枚。前ページ (スライド 9) の 4 カードそれぞれに
    ついて「見るログ (EID) / 注目するログ項目 / 鳴る条件」を表で示す。
    重要度の色 (high=橙 / critical=赤) は実際のルール定義に一致させている。
    """
    s = add_slide(prs, BG_LIGHT)
    header(s, "ルールが実際に「見ている」もの",
           kicker="開発内容② の中身   (検知のしくみ)")
    add_text(s, "攻撃者が必ず行う「証拠隠し・準備」を、ログのどの項目で捕まえているか。",
             x=0.6, y=1.74, w=12.1, h=0.4, size=14, color=MUTED, italic=True)

    # 列見出し
    cols = [("検知する行為", 0.78, 2.4),
            ("見るログ (種類)", 3.2, 2.5),
            ("注目する手がかり (ログの項目)", 5.85, 4.3),
            ("ひとこと", 10.35, 2.3)]
    for label, cx, cw in cols:
        add_text(s, label, x=cx, y=2.12, w=cw, h=0.3,
                 size=10.5, color=ACCENT_DK, bold=True)

    rows = [
        ("🧹", "ログの消去", "high", HIGH,
         "プロセス起動\nSysmon EID 1 / Security 4688",
         "Image:  …\\wevtutil.exe\nCommandLine:  \" cl \" (=消去)",
         "消すコマンド\n自体がログに残る"),
        ("💣", "復元データの削除", "critical", CRIT,
         "プロセス起動\nSysmon EID 1",
         "Image:  …\\vssadmin.exe 等\nCommandLine:  delete + shadows",
         "ランサムウェア\nの前兆"),
        ("🙈", "監視の無効化", "high", HIGH,
         "監査ポリシー変更\nSecurity EID 4719",
         "AuditPolicyChanges:\nSuccess/Failure removed\n(かつ人間のアカウント)",
         "記録を止めた\n瞬間の 1 件"),
        ("🔑", "パスワード抜き取り", "critical", CRIT,
         "プロセス起動\nSysmon EID 1",
         "Image:  …\\rundll32.exe\nCommandLine:  comsvcs + MiniDump",
         "正規ツールの\n悪用を見抜く"),
    ]
    ry, rh = 2.5, 0.92
    for icon, name, lvl, lvlc, logt, clue, point in rows:
        add_card(s, 0.6, ry, 12.1, rh, fill=PANEL, accent_left=lvlc)
        add_text(s, icon, x=0.74, y=ry, w=0.55, h=rh, size=20, color=lvlc,
                 anchor=MSO_ANCHOR.MIDDLE)
        add_text(s, name, x=1.3, y=ry + 0.17, w=1.9, h=0.4,
                 size=11.5, color=TEXT, font=FONT_HEAD, bold=True)
        add_text(s, lvl, x=1.3, y=ry + 0.56, w=1.9, h=0.3,
                 size=9, color=lvlc, bold=True, font=FONT_MONO)
        add_text(s, logt, x=3.2, y=ry, w=2.5, h=rh, size=10.5, color=TEXT,
                 anchor=MSO_ANCHOR.MIDDLE, line_spacing=1.22)
        add_text(s, clue, x=5.85, y=ry, w=4.3, h=rh, size=10, color=ACCENT_DK,
                 font=FONT_MONO, anchor=MSO_ANCHOR.MIDDLE, line_spacing=1.22)
        add_text(s, point, x=10.35, y=ry, w=2.3, h=rh, size=10.5, color=MUTED,
                 anchor=MSO_ANCHOR.MIDDLE, line_spacing=1.2)
        ry += rh + 0.05

    fy = ry + 0.03
    add_card(s, 0.6, fy, 12.1, 0.55, fill=PANEL_SOFT, line=PANEL_SOFT)
    add_text(s,
             "共通の発想:  マルウェア本体は姿を変えられても、「ログ消去・復元点削除・"
             "監視停止・認証情報の窃取」は目的に直結し変えにくい。だから “行為そのもの” を見る。",
             x=0.95, y=fy, w=11.5, h=0.55, size=11.5, color=TEXT,
             anchor=MSO_ANCHOR.MIDDLE, line_spacing=1.2)
    page_no(s, n, total)


def slide_dev_gui(prs, n, total):
    """11: 開発③ GUI — 結果を「読める」にする画面をゼロから開発."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "③  結果を「読める」にする GUI をゼロから開発",
           kicker="開発内容 3 / 3   (Python + JavaScript)")

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
    """12: 開発③+ — ルールでは書けない「いつもと違う」も自作の分析で検出."""
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


def slide_evaluation(prs, n, total):
    """13: 検証 — ちゃんと検知できるかを実測で示す.

    実測に基づく正直な 1 枚:
      左 = 自作エンジン拡張 (lookup) の動作検証 (本研究の核の直接検証)
      右 = 公開攻撃サンプルでのプラットフォーム検知カバレッジ
    自作ルールの発火条件 (対応テレメトリ) は上流ルールと区別して脚注に明記。
    """
    s = add_slide(prs, BG_LIGHT)
    header(s, "検証 — 実際に検知できるか", kicker="評価 (実測)")

    # 左: 自作 lookup 拡張の検証 ----------------------------------------
    add_card(s, 0.6, 1.85, 6.0, 4.55, fill=PANEL, accent_left=ACCENT)
    add_text(s, "① 自作エンジン拡張 (lookup) の検証", x=0.9, y=2.05, w=5.5, h=0.5,
             size=16, color=ACCENT_DK, font=FONT_HEAD, bold=True)
    steps = [
        "既知の「悪用ドライバ」ハッシュを仕込んだ\n検証用ログ (Sysmon EID 6) を解析",
        "→ ルール本文は 1 行も変えず、外部 IoC\n   リスト側だけで照合",
    ]
    cy = 2.65
    for t in steps:
        add_text(s, "• " + t, x=0.95, y=cy, w=5.4, h=0.8, size=12.5,
                 color=TEXT, line_spacing=1.35)
        cy += 0.95
    # 結果チップ (実測)
    add_card(s, 0.95, 4.55, 5.3, 1.05, fill=CODE_BG, line=CODE_BG)
    add_text(s, "実測結果", x=1.15, y=4.68, w=4.9, h=0.3, size=10,
             color=CODE_DIM, font=FONT_MONO)
    add_text(s, "level = critical", x=1.15, y=4.98, w=4.9, h=0.32,
             size=13, color=CODE_HL, font=FONT_MONO)
    add_text(s, "rule  = LOLDrivers hash match", x=1.15, y=5.3, w=4.9, h=0.32,
             size=13, color=CODE_TEXT, font=FONT_MONO)
    add_text(s, "→ IoC リストを取り込んで検知できることを実証 ✓",
             x=0.95, y=5.8, w=5.4, h=0.5, size=12.5, color=OK, bold=True)

    # 右: 公開サンプルでのプラットフォーム検知 --------------------------
    add_card(s, 6.85, 1.85, 5.88, 4.55, fill=PANEL, accent_left=OK)
    add_text(s, "② 公開攻撃サンプルでの検知", x=7.15, y=2.05, w=5.4, h=0.5,
             size=16, color=TEXT, font=FONT_HEAD, bold=True)
    rows = [
        ("ログ消去 (Security 1102)",        "high", HIGH),
        ("ポートフォワード (netsh/RDP)",     "high", HIGH),
        ("バインドシェル / DLL ハイジャック", "high", HIGH),
        ("プロセス注入 (Meterpreter)",       "medium", MED),
        ("DLL サイドローディング",           "medium", MED),
    ]
    ry = 2.62
    for label, sev, col in rows:
        add_text(s, label, x=7.15, y=ry, w=4.4, h=0.4, size=12, color=TEXT,
                 anchor=MSO_ANCHOR.MIDDLE)
        pill = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                  Inches(11.65), Inches(ry + 0.02),
                                  Inches(0.95), Inches(0.34))
        pill.fill.solid(); pill.fill.fore_color.rgb = col
        pill.line.fill.background(); pill.shadow.inherit = False
        add_text(s, sev, x=11.65, y=ry + 0.02, w=0.95, h=0.34, size=10.5,
                 color=WHITE, bold=True, align=PP_ALIGN.CENTER,
                 anchor=MSO_ANCHOR.MIDDLE)
        ry += 0.5
    add_text(s, "検証した 6 サンプル中 5 種で脅威を検知（最大 high）。",
             x=7.15, y=5.2, w=5.4, h=0.4, size=12.5, color=TEXT, bold=True)
    add_text(s,
             "※ ここでの発火は上流 Sigma ルールと自作分の合算。自作の 13 ルールは"
             "対応する痕跡（Sysmon EID 1 の wevtutil 等）を含むログで発火する設計。",
             x=7.15, y=5.62, w=5.45, h=0.75, size=10, color=MUTED,
             line_spacing=1.3)

    add_text(s, "実際のログを読み込ませ、平文ではなく検知として浮かび上がることを確認。",
             x=0.6, y=6.55, w=12.1, h=0.4, size=12.5, color=ACCENT_DK,
             bold=True, align=PP_ALIGN.CENTER)
    page_no(s, n, total)


def slide_demo(prs, n, total):
    """14: デモ — 録画デモ動画を埋め込んだセクション扉 (紺).

    動画ファイルがあればスライド中央に埋め込む (クリックで再生)。ライブ
    デモがうまく動かないときの保険になる。無ければ従来のテキスト扉。
    """
    s = add_slide(prs, NAVY)

    if DEMO_VIDEO.exists():
        add_text(s, "DEMO", x=0.6, y=0.55, w=12, h=0.9,
                 size=44, color=WHITE, font=FONT_HEAD, bold=True,
                 align=PP_ALIGN.CENTER)
        # 16:9 で中央に配置
        vw, vh = 8.4, 4.725
        vx = (13.333 - vw) / 2
        vy = 1.55
        poster = str(DEMO_POSTER) if DEMO_POSTER.exists() else None
        movie = s.shapes.add_movie(
            str(DEMO_VIDEO), Inches(vx), Inches(vy), Inches(vw), Inches(vh),
            poster_frame_image=poster, mime_type="video/mp4")
        movie.line.color.rgb = ICE
        movie.line.width = Pt(1.0)
        add_text(s, "▶ クリックで再生 — 実際の画面の録画 (約 38 秒・字幕つき)",
                 x=0.6, y=6.5, w=12, h=0.5, size=15, color=ICE,
                 italic=True, align=PP_ALIGN.CENTER)
    else:
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
    """15: まとめ — やったこと 4 つの数字 + 今後."""
    s = add_slide(prs, BG_LIGHT)
    header(s, "まとめ — 開発したもの", kicker="成果")

    stats = [
        ("新文法",   "lookup:", "エンジン本体 (Rust) を改造し\nリスト照合機能を追加", ACCENT_DK),
        ("13",      "本",      "攻撃を見抜く検知ルールを\n自作 (痕跡隠蔽の検知など)", HIGH),
        ("GUI",     "ゼロから開発", "結果を日本語で読み解く\n調査画面を自作",        MED),
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
    """16: 締め (紺) — 持ち帰りアクションを 1 つだけ."""
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


def slide_appendix_rules(prs, total):
    """付録: 同梱している検知ルール 13 本を、攻撃の流れ順に整理した一覧.

    「13 本それぞれ何?」と質問されたとき用のバックアップ。発表本編 (1-15) の
    あとに置く。説明は専門用語を避けた自然な日本語で 1 行ずつ。色ドットは
    実際のルールの重要度 (critical=赤 / high=橙) に一致。
    """
    s = add_slide(prs, BG_LIGHT)
    header(s, "付録: 同梱している検知ルール 13 本",
           kicker="Q&A 用   — 攻撃の流れに沿って整理")

    # 凡例 (重要度の色)
    lg = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(9.05), Inches(0.55),
                            Inches(0.16), Inches(0.16))
    lg.fill.solid(); lg.fill.fore_color.rgb = CRIT
    lg.line.fill.background(); lg.shadow.inherit = False
    add_text(s, "critical (最重要)", x=9.28, y=0.5, w=1.7, h=0.3,
             size=10, color=MUTED, anchor=MSO_ANCHOR.MIDDLE)
    lg2 = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(11.1), Inches(0.55),
                             Inches(0.16), Inches(0.16))
    lg2.fill.solid(); lg2.fill.fore_color.rgb = HIGH
    lg2.line.fill.background(); lg2.shadow.inherit = False
    add_text(s, "high (重要)", x=11.33, y=0.5, w=1.4, h=0.3,
             size=10, color=MUTED, anchor=MSO_ANCHOR.MIDDLE)

    # 4 グループ (攻撃の段階) × それぞれのルール
    groups = [
        ("① 外から入る・動く・つながる", [
            (CRIT, "既知のマルウェアそのものが実行された (MalwareBazaar 照合)"),
            (CRIT, "指令サーバ (C2) として知られる場所への通信 (URLhaus 照合)"),
            (CRIT, "正規ツール certutil を悪用して外部からファイルを取得"),
            (CRIT, "悪用が知られた脆弱ドライバの読み込み (LOLDrivers 照合)"),
        ]),
        ("② 盗む・住み着く", [
            (CRIT, "ログイン情報の抜き取り (LSASS のメモリダンプ)"),
            (HIGH, "書き換え可能な場所のプログラムをサービス登録して常駐"),
            (HIGH, "WMI で「出来事をきっかけに自動起動」を仕込む"),
        ]),
        ("③ 監視を無力化する", [
            (HIGH, "PowerShell のウイルス検査 (AMSI) を無力化"),
            (CRIT, "ログ記録サービスそのものを停止・無効化"),
            (HIGH, "監査設定から記録項目を外して “見えなく” する"),
        ]),
        ("④ 証拠を消す", [
            (HIGH, "wevtutil などでイベントログをまるごと消去"),
            (CRIT, "監査を変えた直後にログ消去、という “合わせ技”"),
            (CRIT, "復元用スナップショットの削除 (ランサムの前兆)"),
        ]),
    ]

    card_w, card_h = 5.85, 2.45
    positions = [(0.6, 1.95), (6.88, 1.95), (0.6, 4.5), (6.88, 4.5)]
    for (title, rules), (cx, cy) in zip(groups, positions):
        add_card(s, cx, cy, card_w, card_h, fill=PANEL, accent_left=ACCENT)
        add_text(s, title, x=cx + 0.28, y=cy + 0.16, w=card_w - 0.45, h=0.45,
                 size=14, color=ACCENT_DK, font=FONT_HEAD, bold=True)
        ly = cy + 0.72
        for color, desc in rules:
            dot = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(cx + 0.3),
                                     Inches(ly + 0.07), Inches(0.12), Inches(0.12))
            dot.fill.solid(); dot.fill.fore_color.rgb = color
            dot.line.fill.background(); dot.shadow.inherit = False
            add_text(s, desc, x=cx + 0.54, y=ly, w=card_w - 0.78, h=0.4,
                     size=10.5, color=TEXT, line_spacing=1.1)
            ly += 0.42

    add_text(s, "付録", x=12.0, y=7.05, w=1.0, h=0.3,
             size=9, color=MUTED, align=PP_ALIGN.RIGHT)


def slide_qa(prs, kicker, title, items):
    """付録: 想定問答 (Q&A) を 1 枚に 3 問。質問されたら該当ページを出す用。

    items = [(question, answer), ...] を縦に積む。本編 (1-15) の番号は崩さず、
    フッタは「付録」とだけ表示する。
    """
    s = add_slide(prs, BG_LIGHT)
    header(s, title, kicker=kicker)
    y = 1.95
    ch = (6.98 - y) / len(items) - 0.16
    for q, a in items:
        add_card(s, 0.6, y, 12.13, ch, fill=PANEL, accent_left=ACCENT)
        add_text(s, "Q.  " + q, x=0.95, y=y + 0.16, w=11.5, h=0.5,
                 size=15, color=TEXT, font=FONT_HEAD, bold=True)
        add_text(s, "A.  " + a, x=0.95, y=y + 0.66, w=11.45, h=ch - 0.78,
                 size=12.5, color=MUTED, line_spacing=1.32)
        y += ch + 0.16
    add_text(s, "付録", x=12.0, y=7.05, w=1.0, h=0.3,
             size=9, color=MUTED, align=PP_ALIGN.RIGHT)


# 想定問答の中身 (3 枚ぶん)
QA_POSITION = [
    ("既存の Hayabusa と何が違うの?",
     "検知エンジンに lookup 文法を追加し、攻撃を見抜くルールを 13 本自作。さらに結果を"
     "日本語で読み解く GUI、振る舞い分析、IoC の自動取り込みを足した。土台の検知力は"
     "活かしつつ「専門家でなくても使える形」にしたのが差分。"),
    ("SIEM や商用 EDR と何が違うの?",
     "導入ゼロ・オフライン・無料で、PC 1 台に展開すればすぐ動く。大規模な常時監視では"
     "なく「インシデント時に手元で素早く調べる」用途に振り切っている。"),
    ("Sigma ルールはそのまま使える? 独自拡張で互換は壊れない?",
     "世界共通の Sigma 約 5,000 本に加え、自作 13 本が使える。lookup は独自拡張だが、"
     "上流の Hayabusa は知らない記法を無視するだけなので互換は壊れない。"),
]

QA_QUALITY = [
    ("誤検知は多くならないの?",
     "単一の特徴では鳴らさず複数条件の AND で判定。各ルールに誤検知例を明記し、ゴールデン"
     "イメージの許可リストや、GUI 上での TP/FP 判定・抑制で運用しながら絞り込める。"),
    ("速度や扱える規模は?",
     "Rust 製で数万件を数十秒。lookup は起動時に 1 回だけリストを読み込み O(1) で照合する"
     "ため、リストが増えても速度はほぼ一定（本デモでも 1.2 万件超を処理）。"),
    ("IoC リストはどうやって最新に保つ?",
     "feeds.yml に宣言し、ボタン 1 つで取得・正規化 (loldrivers / MalwareBazaar / URLhaus "
     "/ Feodo)。取得失敗時は前回分を保持し、カバレッジを空にしない設計。"),
]

QA_SAFETY = [
    ("データは外部に送られない? 安全?",
     "localhost 限定バインドで外部送信なし、追加ソフトも不要。自 PC のライブ解析は管理者"
     "権限＋明示チェック時のみ。DNS リバインドや CSRF への対策も実装済み。"),
    ("未知の攻撃 (ゼロデイ) は検知できる?",
     "ルールは既知の手口に強い。未知は振る舞い分析（急増・拡散・沈黙・時間外）で「いつもと"
     "違う」を拾う、という二段構えでカバーする。"),
    ("今後の発展は?",
     "時間の流れを追った相関分析（「A の後に B が起きたら怪しい」）や、AI による検知ルールの"
     "自動生成へ。"),
]


# ===========================================================================
# 発表者ノート (各スライドで話す原稿) — PowerPoint の「ノート」欄に入る
# ===========================================================================
# index = スライド番号 (1 始まり)。発表時間 11-12 分を想定した分量。
SPEAKER_NOTES = {
    1: (
        "本日は「OSS 解析エンジン Hayabusa の拡張による、誰でも使えるサイバー攻撃調査"
        "ツールの開発」というテーマで発表します。\n"
        "一言でいうと、プロの道具を“誰でも使える形”に作り変えた研究です。\n"
        "やったことは大きく 3 つ。①エンジン本体 (Rust) への新しい検知機能の追加、"
        "②攻撃を見抜く検知ルールの自作、③結果を読み解ける GUI の開発です。\n"
        "成果物はすべて GitHub で公開しています。"
    ),
    2: (
        "まず背景から。もし皆さんの会社がサイバー攻撃を受けたら、どうしますか。\n"
        "知りたいのは「どこから侵入されたか」「誰に何をされたか」「被害はどこまで"
        "広がったか」。しかもこれを“素早く”知る必要があります。対応が遅れるほど"
        "被害は広がるからです。"
    ),
    3: (
        "その答えは、実は Windows が残しているログの中にあります。ログオン、プロセス"
        "起動、通信 ── 攻撃の痕跡はすべて記録されている。\n"
        "ただ問題は“量”です。たった 1 台の PC でも数万件。これを人間が 1 件ずつ読むのは"
        "現実的に不可能で、専門家が時間をかけても見落とします。"
    ),
    4: (
        "そこで土台にしたのが、日本の Yamato Security が公開している無料ツール "
        "Hayabusa です。世界中の研究者が作った約 5,000 本の攻撃パターンと、数万件の"
        "ログを数十秒で照合できる、実績あるツールです。\n"
        "ただ弱点があって、黒い画面でコマンドを打つ必要があり、結果は CSV 数万行、"
        "しかも英語と専門用語。「で、次どうすれば?」は教えてくれない。\n"
        "つまり“強力だが専門家にしか使えない”。ここを出発点にしました。"
    ),
    5: (
        "目的は明確で、この「専門家の道具」を「誰でも使える調査プラットフォーム」に"
        "することです。\n"
        "方針は 3 つ。①見つける力を強くする (エンジン改造とルール自作)、②結果を"
        "読めるようにする (GUI)、③手元だけで完結させる (データを外に出さない・追加"
        "ソフト不要)。\n"
        "この 3 つが、この後の発表の章立てになります。"
    ),
    6: (
        "全体像です。グレーが既存の Hayabusa、青が私が開発した部分です。\n"
        "ログがエンジンで解析され、GUI を通して人が読む、という流れ。エンジンには"
        "中身を改造して新機能を追加し、下から「自作の検知ルール 13 本」と「悪いもの"
        "リスト約 8 万件」を注ぎ込んでいます。GUI はゼロから自作しました。\n"
        "では順に説明します。"
    ),
    7: (
        "1 つ目、エンジン本体の改造です。Hayabusa の「ルールの書き方」自体を拡張"
        "しました。\n"
        "具体的には、ルールに 1 行「このリストに載っていたら警告して」と書ける "
        "lookup という機能を、Rust のソースコードに追加しました。\n"
        "これで世界中で共有されている悪性ハッシュや URL のリスト約 8 万件を、ルールを"
        "書き換えずにそのまま検知に使えます。このリストの出どころと処理の流れを、"
        "次のページで説明します。"
    ),
    8: (
        "これが lookup の内部フローです。例として、悪用される脆弱ドライバの検知 "
        "(BYOVD) を追います。\n"
        "まず出どころは loldrivers.io。世界中の研究者が集めた“悪用されるドライバ”の"
        "ハッシュ一覧です。これを取得してテキストに整形し、1,929 件のリストとして"
        "保存します。\n"
        "エンジンは起動時に一度だけこれをメモリに読み込み、あとはログ 1 件ごとに、"
        "ドライバ読込イベントのハッシュをこの表と照合。一致すれば攻撃の痕跡として "
        "critical で通知します。\n"
        "ポイントは、リストが増えても照合速度は一定で、リストを更新するだけで最新の"
        "脅威に追従できることです。"
    ),
    9: (
        "2 つ目、検知ルールを 13 本自作しました。\n"
        "着眼点は「攻撃者は必ず証拠隠しをする。なら、消す行為そのものを検知すれば"
        "いい」。代表的な 4 つが、ログの消去、復元データの削除、監視の無効化、"
        "パスワードの抜き取りです。\n"
        "誤検知を減らすため、1 つの特徴では鳴らさず、複数の特徴が同時に揃ったときだけ"
        "警告する設計にしています。"
    ),
    10: (
        "では、これらが実際にログの“どこ”を見ているか。\n"
        "例えばログの消去なら、プロセス起動ログで wevtutil.exe が cl (クリア) 付きで"
        "実行されたかを見ます。復元データ削除なら vssadmin の delete shadows ── これは"
        "ランサムウェアの前兆です。監視の無効化は監査ポリシー変更のイベント 4719、"
        "パスワード抜き取りは rundll32 が comsvcs と MiniDump を使ったか。\n"
        "共通しているのは、マルウェア本体は姿を変えられても、これらの“目的に直結した"
        "行為”は変えにくい、という点。だからそこを見るんです。"
    ),
    11: (
        "3 つ目、結果を読めるようにする GUI をゼロから開発しました。\n"
        "検知をクリックすると「何が起きて、次にどうするか」を日本語で表示。どの PC から"
        "調べるべきかを自動採点して並べ替え、全体像はグラフで俯瞰できます。\n"
        "右が実際の画面です。すべてブラウザで動き、データは外部に送りません。"
    ),
    12: (
        "さらに、ルールでは書けない「いつもと違う」も検出できるよう、統計分析を"
        "自作しました。\n"
        "急増、複数 PC への拡散、急に静かになる、時間外の活動、の 4 種類です。\n"
        "ルールは既知の手口に強い一方、振る舞い分析は“未知の手口への気づき”になる。"
        "両者を組み合わせるのが狙いです。"
    ),
    14: (
        "ここから実際の画面でお見せします。サンプルログを読み込んで、調査の流れを"
        "見ていただきます。\n"
        "(デモ: スキャン実行 → ダッシュボードで全体把握 → 検知の日本語解説 → "
        "ホスト別の危険度ランキング、の順に見せる)\n"
        "※ ライブが不調なときは、スライド中央の動画をクリックすれば同じ流れの"
        "録画 (約 38 秒・字幕つき) が再生されます。"
    ),
    13: (
        "研究として「で、効果は?」に答えるスライドです。\n"
        "核心の自作 lookup 拡張は、既知の悪用ドライバのハッシュを仕込んだ検証用ログで "
        "critical 検知を確認できました ── ルール本文を変えずに外部リスト側だけで検知"
        "できる、という仕組みの実証です。\n"
        "さらに公開されている攻撃サンプル 6 種を読み込ませると 5 種で脅威を検知。なお"
        "ここでの発火は上流ルールと自作分の合算で、自作 13 ルールは対応する痕跡を含む"
        "ログで鳴る設計、という点も正直に添えてあります。"
    ),
    15: (
        "まとめます。エンジンに lookup という新しい文法を追加し、検知ルールを 13 本"
        "自作、結果を読み解く GUI を新たに開発し、悪いものリスト約 8 万件を"
        "自動で取り込んで照合できるようにしました。\n"
        "今後は、時間の流れを追った相関分析 (「A の後に B が起きたら怪しい」) や、"
        "AI による検知ルールの自動生成に進めたいと考えています。"
    ),
    16: (
        "以上です。ありがとうございました。\n"
        "成果物はすべて GitHub で公開しているので、お手元の Windows PC のログで"
        "ぜひ一度試してみてください。ご質問・フィードバックをお願いします。"
    ),
    17: (
        "(付録・Q&A 用) 「13 本って具体的には?」と聞かれたら、このスライドを"
        "出してください。\n"
        "本編では代表的な 4 種類を紹介しましたが、実際は攻撃の流れに沿って 13 本を"
        "用意しています。「①外から入って動く → ②盗んで住み着く → ③監視を無力化 → "
        "④証拠を消す」という順番で、それぞれの段階で出る特徴を捕まえます。\n"
        "赤が critical、橙が high です。気になるルールがあれば個別に説明できます。"
    ),
}


def attach_notes(prs):
    """SPEAKER_NOTES の各原稿を、対応するスライドのノート欄へ書き込む。"""
    for idx, slide in enumerate(prs.slides, start=1):
        text = SPEAKER_NOTES.get(idx)
        if not text:
            continue
        slide.notes_slide.notes_text_frame.text = text


# ===========================================================================
# main
# ===========================================================================

def main():
    prs = new_pres()
    prs.title  = "hayabusa-plus (研究発表・一般向け)"
    prs.author = "hayabusa-plus"

    total = 16
    slide_title(prs, total)             # 1  — タイトル (番号なし)
    slide_question(prs, 2, total)       # 2  — 背景: 攻撃を受けたら?
    slide_problem(prs, 3, total)        # 3  — 背景: ログは読めない
    slide_hayabusa(prs, 4, total)       # 4  — 既存技術: Hayabusa と課題
    slide_goal(prs, 5, total)           # 5  — 目的
    slide_overview(prs, 6, total)       # 6  — 全体像 (既存 vs 自作)
    slide_dev_engine(prs, 7, total)     # 7  — 開発① エンジン改造 (lookup: 文法)
    slide_lookup_flow(prs, 8, total)    # 8  — ↑の内部フロー (loldrivers.io→検知)
    slide_dev_rules(prs, 9, total)      # 9  — 開発② ルール自作
    slide_rules_internals(prs, 10, total)  # 10 — ↑の中身 (各ルールが見るログ項目)
    slide_dev_gui(prs, 11, total)       # 11 — 開発③ GUI
    slide_dev_anomaly(prs, 12, total)   # 12 — 開発+α 異常検知
    slide_evaluation(prs, 13, total)    # 13 — 検証 (実測で効果を示す)
    slide_demo(prs, 14, total)          # 14 — デモ
    slide_summary(prs, 15, total)       # 15 — まとめ
    slide_thanks(prs, total, total)     # 16 — おわり
    slide_appendix_rules(prs, total)    # 付録 — 検知ルール 13 本の一覧 (Q&A 用)
    slide_qa(prs, "付録 — 想定問答 (Q&A)",
             "よくある質問 ①  立ち位置・差分", QA_POSITION)
    slide_qa(prs, "付録 — 想定問答 (Q&A)",
             "よくある質問 ②  精度・性能・運用", QA_QUALITY)
    slide_qa(prs, "付録 — 想定問答 (Q&A)",
             "よくある質問 ③  安全性・未知の攻撃・今後", QA_SAFETY)

    attach_notes(prs)                   # 各スライドに発表者ノートを付与

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
