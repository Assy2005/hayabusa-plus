"""
hayabusa-plus 発表用 PowerPoint (.pptx) 生成スクリプト — 一般向け版
==================================================================

11 枚構成。発表時間 10-12 分 (+ デモ 5 分 + Q&A 5 分) を想定。

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
    - GUI と同じダークテーマ (#0b0d12 + #ff5722)
    - 16:9 ワイドスクリーン
"""

from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn
from lxml import etree


# ---------------------------------------------------------------------------
# カラーパレット (GUI と統一)
# ---------------------------------------------------------------------------
BG_DARK    = RGBColor(0x0B, 0x0D, 0x12)
BG_PANEL   = RGBColor(0x16, 0x1B, 0x26)
BG_PANEL2  = RGBColor(0x1F, 0x29, 0x42)
LINE       = RGBColor(0x2A, 0x36, 0x54)
ACCENT     = RGBColor(0xFF, 0x57, 0x22)   # オレンジ (主)
ACCENT_2   = RGBColor(0xFF, 0xAB, 0x40)   # ゴールド (副)
TEXT       = RGBColor(0xD8, 0xDE, 0xF0)
TEXT_BRIGHT= RGBColor(0xFF, 0xFF, 0xFF)
MUTED      = RGBColor(0x7D, 0x86, 0x9C)

CRIT       = RGBColor(0xFF, 0x17, 0x44)
HIGH       = RGBColor(0xFF, 0x52, 0x52)
MED        = RGBColor(0xFF, 0xB3, 0x00)
LOW        = RGBColor(0x42, 0xA5, 0xF5)
OK         = RGBColor(0x26, 0xC2, 0x81)

FONT_HEAD = "Cambria"
FONT_BODY = "Calibri"
FONT_MONO = "Consolas"


# ---------------------------------------------------------------------------
# ヘルパ
# ---------------------------------------------------------------------------

def new_pres():
    prs = Presentation()
    prs.slide_width  = Inches(13.333)
    prs.slide_height = Inches(7.5)
    return prs


def add_dark_slide(prs, bg=BG_DARK):
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


def add_card(slide, x, y, w, h, *, fill=BG_PANEL, accent_left=None):
    card = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    card.fill.solid()
    card.fill.fore_color.rgb = fill
    card.line.color.rgb = LINE
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


def page_no(slide, n, total):
    add_text(slide, f"{n} / {total}", x=12.3, y=7.1, w=1.0, h=0.3,
             size=9, color=MUTED, align=PP_ALIGN.RIGHT)


def slide_header_strip(slide, title, *, kicker=None):
    if kicker:
        add_text(slide, kicker, x=0.6, y=0.4, w=12, h=0.3,
                 size=11, color=ACCENT, font=FONT_BODY, bold=True)
    add_text(slide, title, x=0.6, y=0.7, w=12, h=0.7,
             size=28, color=TEXT_BRIGHT, font=FONT_HEAD, bold=True)
    bar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(1.45), Inches(0.6), Inches(0.05))
    bar.fill.solid()
    bar.fill.fore_color.rgb = ACCENT
    bar.line.fill.background()
    bar.shadow.inherit = False


# ===========================================================================
# スライド定義 — 一般向け版
# ===========================================================================

def slide_title(prs, total):
    """1: タイトル — フックを副題でしっかり言い切る."""
    s = add_dark_slide(prs)
    bar_top = s.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                 0, Inches(2.6), prs.slide_width, Inches(0.04))
    bar_top.fill.solid(); bar_top.fill.fore_color.rgb = ACCENT
    bar_top.line.fill.background(); bar_top.shadow.inherit = False

    add_text(s, "🦅", x=0.6, y=1.0, w=2, h=1.2,
             size=80, color=ACCENT, align=PP_ALIGN.LEFT)
    add_text(s, "hayabusa-plus",
             x=2.0, y=1.05, w=11, h=1.3,
             size=72, color=TEXT_BRIGHT, font=FONT_HEAD, bold=True)

    # 副タイトル — 専門知識ゼロでも刺さる一文に
    add_text(s, "サイバー攻撃の痕跡を、誰でも読めるように",
             x=0.6, y=3.6, w=12, h=0.7, size=30,
             color=ACCENT_2, font=FONT_HEAD, italic=True,
             align=PP_ALIGN.CENTER)

    # サブ説明
    add_text(s, "Windows のログから「何が起きたのか」を、",
             x=0.6, y=4.6, w=12, h=0.45, size=18, color=MUTED,
             align=PP_ALIGN.CENTER)
    add_text(s, "ブラウザの画面で見える形にしました。",
             x=0.6, y=5.05, w=12, h=0.45, size=18, color=MUTED,
             align=PP_ALIGN.CENTER)

    add_text(s, "github.com/Assy2005/hayabusa-plus",
             x=0.6, y=6.7, w=12, h=0.4, size=14, color=MUTED,
             font=FONT_MONO, align=PP_ALIGN.CENTER)


def slide_question(prs, n, total):
    """2: 問いかけ — 自分事に変える."""
    s = add_dark_slide(prs)

    add_text(s, "もし、あなたの会社が",
             x=0.6, y=1.6, w=12, h=0.8, size=32, color=TEXT,
             align=PP_ALIGN.CENTER)
    add_text(s, "サイバー攻撃を受けたら",
             x=0.6, y=2.3, w=12, h=0.9, size=42, color=TEXT_BRIGHT,
             font=FONT_HEAD, bold=True, align=PP_ALIGN.CENTER)
    add_text(s, "...どうしますか?",
             x=0.6, y=3.2, w=12, h=0.8, size=32, color=TEXT,
             align=PP_ALIGN.CENTER)

    # 3 つの問い (カード)
    questions = [
        ("どこから", "侵入された?"),
        ("誰が", "何をされた?"),
        ("被害は", "どこまで広がった?"),
    ]
    card_w = 3.5
    for i, (top, bot) in enumerate(questions):
        x = 1.4 + i * (card_w + 0.4)
        y = 4.7
        add_card(s, x, y, card_w, 1.8, fill=BG_PANEL, accent_left=ACCENT)
        add_text(s, top, x=x, y=y + 0.25, w=card_w, h=0.55,
                 size=18, color=ACCENT_2, font=FONT_HEAD, bold=True,
                 align=PP_ALIGN.CENTER)
        add_text(s, bot, x=x, y=y + 0.85, w=card_w, h=0.6,
                 size=22, color=TEXT_BRIGHT, font=FONT_HEAD, bold=True,
                 align=PP_ALIGN.CENTER)

    add_text(s, "これを 素早く 知る必要があります",
             x=0.6, y=6.85, w=12, h=0.4, size=14, color=MUTED,
             italic=True, align=PP_ALIGN.CENTER)
    page_no(s, n, total)


def slide_problem(prs, n, total):
    """3: 課題 — Windows ログの圧倒される感を伝える."""
    s = add_dark_slide(prs)
    slide_header_strip(s, "答えは Windows のログの中にある", kicker="01  でも...")

    # 左側: ログの「文字の壁」感を出す疑似コード
    add_card(s, 0.6, 1.85, 6.4, 5.0, fill=RGBColor(0x08, 0x0A, 0x10),
             accent_left=MUTED)
    add_text(s, "Windows のログ (実例)", x=0.85, y=1.95, w=6, h=0.3,
             size=10, color=MUTED, font=FONT_MONO)

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
    ly = 2.4
    for line in log_lines:
        add_text(s, line, x=0.85, y=ly, w=6.0, h=0.32,
                 size=10, color=MUTED, font=FONT_MONO)
        ly += 0.36

    # 右側: 結論
    add_text(s, "1 台の PC で", x=7.4, y=2.3, w=5.5, h=0.5,
             size=22, color=TEXT, align=PP_ALIGN.LEFT)
    add_text(s, "数万件", x=7.4, y=2.85, w=5.5, h=1.0,
             size=68, color=ACCENT_2, font=FONT_HEAD, bold=True,
             align=PP_ALIGN.LEFT)
    add_text(s, "のログが残っています", x=7.4, y=3.95, w=5.5, h=0.5,
             size=22, color=TEXT, align=PP_ALIGN.LEFT)

    # 結論
    add_card(s, 7.4, 5.0, 5.5, 1.9, fill=BG_PANEL2, accent_left=CRIT)
    add_text(s, "これを 1 件ずつ読むのは",
             x=7.6, y=5.2, w=5.2, h=0.45, size=15, color=TEXT)
    add_text(s, "現実的に不可能。",
             x=7.6, y=5.7, w=5.2, h=0.6, size=24, color=CRIT,
             font=FONT_HEAD, bold=True)
    add_text(s, "→ 専門家が時間をかけても見落とす。",
             x=7.6, y=6.35, w=5.2, h=0.4, size=12, color=MUTED, italic=True)

    page_no(s, n, total)


def slide_solution(prs, n, total):
    """4: 解決策 — それを"見える化"した."""
    s = add_dark_slide(prs)
    slide_header_strip(s, "それを、ブラウザで見える形にしました",
                       kicker="02  hayabusa-plus とは")

    add_text(s, "数万件のログを",
             x=0.6, y=2.0, w=12, h=0.6, size=22, color=MUTED,
             align=PP_ALIGN.CENTER)
    add_text(s, "「人が読める形」に整理して、画面に並べます。",
             x=0.6, y=2.7, w=12, h=0.7, size=28, color=TEXT_BRIGHT,
             font=FONT_HEAD, bold=True, align=PP_ALIGN.CENTER)

    # 3 つの key value
    keys = [
        ("🖥️", "ブラウザだけ", "外部にデータを送らない\nオフラインで完結"),
        ("📦", "インストール簡単", "Python があれば動く\n専用アプリ不要"),
        ("🆓", "OSS で公開", "誰でも使える\nGitHub で配布中"),
    ]
    card_w = 3.9
    for i, (icon, title, body) in enumerate(keys):
        x = 0.6 + i * (card_w + 0.4)
        y = 4.0
        add_card(s, x, y, card_w, 2.6, fill=BG_PANEL2, accent_left=ACCENT)
        add_text(s, icon, x=x + 0.3, y=y + 0.3, w=1.0, h=0.8,
                 size=36, color=ACCENT_2)
        add_text(s, title, x=x + 0.3, y=y + 1.15, w=card_w - 0.5, h=0.5,
                 size=20, color=TEXT_BRIGHT, font=FONT_HEAD, bold=True)
        add_text(s, body, x=x + 0.3, y=y + 1.7, w=card_w - 0.5, h=0.85,
                 size=12, color=MUTED, line_spacing=1.4)

    page_no(s, n, total)


def slide_feature_priority(prs, n, total):
    """5: 機能 ① ホスト優先度ランキング."""
    s = add_dark_slide(prs)
    slide_header_strip(s, "①  「どこから調べるべきか」が分かる",
                       kicker="03  機能 1 / 4")

    # 左: 説明
    add_text(s, "会社のすべての PC を",
             x=0.6, y=1.95, w=6, h=0.5, size=18, color=TEXT)
    add_text(s, "「危険度」順に並べます",
             x=0.6, y=2.55, w=6.5, h=0.6, size=26, color=TEXT_BRIGHT,
             font=FONT_HEAD, bold=True)

    add_text(s, "「どの PC から手を付ければいいか」が、",
             x=0.6, y=3.7, w=6.5, h=0.5, size=14, color=TEXT,
             line_spacing=1.5)
    add_text(s, "一目で分かります。",
             x=0.6, y=4.15, w=6.5, h=0.5, size=14, color=ACCENT_2,
             bold=True, line_spacing=1.5)

    add_text(s, "💡 危険度は、過去の検出履歴から",
             x=0.6, y=5.2, w=6.5, h=0.4, size=12, color=MUTED)
    add_text(s, "    自動計算 (重大度・件数・直近性で重み付け)",
             x=0.6, y=5.55, w=6.5, h=0.4, size=12, color=MUTED)

    # 右: ランキング風モック
    add_card(s, 7.3, 1.95, 5.5, 5.0, fill=BG_PANEL, accent_left=ACCENT)
    add_text(s, "ホスト 危険度ランキング", x=7.5, y=2.1, w=5.0, h=0.4,
             size=11, color=MUTED)

    rows = [
        ("LAPTOP-A12",     87.7, CRIT,  "最優先"),
        ("DESKTOP-B05",    52.3, HIGH,  ""),
        ("LAPTOP-C03",     28.9, MED,   ""),
        ("PC-D17",         21.7, LOW,   ""),
        ("WS-E08",         18.1, LOW,   ""),
    ]
    ry = 2.7
    for name, score, color, note in rows:
        # 行背景
        bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                Inches(7.5), Inches(ry),
                                Inches(5.1), Inches(0.78))
        bg.fill.solid(); bg.fill.fore_color.rgb = BG_PANEL2
        bg.line.fill.background(); bg.shadow.inherit = False

        # ホスト名
        add_text(s, name, x=7.6, y=ry + 0.08, w=1.8, h=0.3,
                 size=12, color=TEXT, font=FONT_MONO, bold=True)
        # スコア
        add_text(s, f"{score:.1f}",
                 x=11.5, y=ry + 0.08, w=1.0, h=0.3,
                 size=14, color=color, font=FONT_HEAD, bold=True,
                 align=PP_ALIGN.RIGHT)
        # バー
        bar_w = (score / 100.0) * 2.5
        bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                 Inches(8.8), Inches(ry + 0.48),
                                 Inches(bar_w), Inches(0.18))
        bar.fill.solid(); bar.fill.fore_color.rgb = color
        bar.line.fill.background(); bar.shadow.inherit = False
        # 注釈
        if note:
            add_text(s, "⚠ " + note,
                     x=7.6, y=ry + 0.42, w=1.6, h=0.3,
                     size=10, color=color, bold=True)
        ry += 0.85

    page_no(s, n, total)


def slide_feature_explain(prs, n, total):
    """6: 機能 ② 検知をクリックで説明."""
    s = add_dark_slide(prs)
    slide_header_strip(s, "②  「何が起きているか」が分かる",
                       kicker="04  機能 2 / 4")

    # 左: 説明
    add_text(s, "怪しい動きが見つかったら、",
             x=0.6, y=1.95, w=6, h=0.5, size=18, color=TEXT)
    add_text(s, "クリックするだけで",
             x=0.6, y=2.55, w=6.5, h=0.6, size=26, color=TEXT_BRIGHT,
             font=FONT_HEAD, bold=True)
    add_text(s, "意味と対応方法を表示します",
             x=0.6, y=3.2, w=6.5, h=0.6, size=26, color=ACCENT_2,
             font=FONT_HEAD, bold=True)

    add_text(s, "従来は専門家が翻訳していた情報を、",
             x=0.6, y=4.4, w=6.5, h=0.5, size=14, color=TEXT)
    add_text(s, "日本語の解説でその場で表示します。",
             x=0.6, y=4.85, w=6.5, h=0.5, size=14, color=TEXT)

    add_text(s, "💡 「次にすべきこと」も提示するので、",
             x=0.6, y=5.85, w=6.5, h=0.4, size=12, color=MUTED)
    add_text(s, "    初心者でも調査の進め方が分かります。",
             x=0.6, y=6.2, w=6.5, h=0.4, size=12, color=MUTED)

    # 右: 解説パネル風モック
    add_card(s, 7.3, 1.95, 5.5, 5.0, fill=BG_PANEL, accent_left=CRIT)

    # ヘッダ
    add_text(s, "[重大] ", x=7.5, y=2.1, w=1.0, h=0.4,
             size=11, color=CRIT, bold=True, font=FONT_MONO)
    add_text(s, "ID 情報の不正取得を検知",
             x=8.2, y=2.05, w=4.5, h=0.5, size=14, color=TEXT_BRIGHT,
             font=FONT_HEAD, bold=True)

    # セクション
    sections = [
        ("📋 何を検知?",
         "本来アクセスしてはいけない\n認証情報メモリ領域への\nアクセスが行われた"),
        ("⚠ 重要度の意味",
         "今すぐ確認が必要なレベル。\n攻撃が成功している可能性大"),
        ("→ 次にすべきこと",
         "1. 該当 PC をネットから切断\n2. 直前の操作履歴を確認\n3. パスワードの一斉変更"),
    ]
    sy = 2.65
    for h, body in sections:
        add_text(s, h, x=7.5, y=sy, w=5.2, h=0.35,
                 size=11, color=ACCENT, bold=True)
        add_text(s, body, x=7.6, y=sy + 0.4, w=5.1, h=1.0,
                 size=11, color=TEXT, line_spacing=1.3)
        sy += 1.45

    page_no(s, n, total)


def slide_feature_anomaly(prs, n, total):
    """7: 機能 ③ いつもと違うを見つける."""
    s = add_dark_slide(prs)
    slide_header_strip(s, "③  「いつもと違う」を見つける",
                       kicker="05  機能 3 / 4")

    add_text(s,
             "個別のログが普通でも、" "全体の傾向で「おかしさ」を検出します。",
             x=0.6, y=1.85, w=12, h=0.5, size=16, color=TEXT, italic=True)

    types = [
        ("🔥", "急増している", "平常の数十〜数千倍の\n動きが急に発生",
         "例: 大量のパスワード試行"),
        ("🌐", "広がっている", "同じ動きが\n複数の PC で同時発生",
         "例: マルウェアが横展開"),
        ("🤫", "急に静かに", "普段活動している PC が\n急にログを残さなくなる",
         "例: 攻撃者がログを消した"),
        ("🌙", "時間外の活動", "深夜などの業務時間外に\n重要な動きが発生",
         "例: 業務外を狙った侵入"),
    ]
    card_w = 2.95
    for i, (icon, name, cond, story) in enumerate(types):
        x = 0.6 + i * (card_w + 0.2)
        y = 2.7
        add_card(s, x, y, card_w, 3.3, fill=BG_PANEL, accent_left=ACCENT)
        add_text(s, icon, x=x + 0.2, y=y + 0.2, w=1.0, h=0.7,
                 size=30, color=ACCENT_2)
        add_text(s, name, x=x + 0.2, y=y + 0.95, w=card_w - 0.3, h=0.5,
                 size=18, color=TEXT_BRIGHT, font=FONT_HEAD, bold=True)
        # 何を見ている
        add_text(s, cond, x=x + 0.2, y=y + 1.6, w=card_w - 0.3, h=0.9,
                 size=11, color=TEXT, line_spacing=1.4)
        # 例
        add_text(s, "例:", x=x + 0.2, y=y + 2.55, w=card_w - 0.3, h=0.3,
                 size=10, color=MUTED, bold=True)
        add_text(s, story, x=x + 0.55, y=y + 2.55, w=card_w - 0.5, h=0.6,
                 size=10, color=MUTED, italic=True)

    # 実例 highlight
    add_card(s, 0.6, 6.2, 12.1, 0.95, fill=BG_PANEL2, accent_left=ACCENT)
    add_text(s, "💡 実例: ",
             x=0.85, y=6.45, w=1.2, h=0.45, size=14,
             color=ACCENT_2, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    add_text(s, "ある PC で疑わしい動きが ",
             x=2.0, y=6.45, w=4.0, h=0.45, size=14,
             color=TEXT, anchor=MSO_ANCHOR.MIDDLE)
    add_text(s, "いつもの 2,492 倍 ",
             x=5.9, y=6.45, w=2.4, h=0.45, size=18,
             color=ACCENT_2, font=FONT_HEAD, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    add_text(s, "発生していたのを自動検出。",
             x=8.2, y=6.45, w=4.5, h=0.45, size=14,
             color=TEXT, anchor=MSO_ANCHOR.MIDDLE)
    page_no(s, n, total)


def slide_feature_iocheck(prs, n, total):
    """8: 機能 ④ 既知の悪との照合."""
    s = add_dark_slide(prs)
    slide_header_strip(s, "④  世界中の「悪いものリスト」と自動照合",
                       kicker="06  機能 4 / 4")

    # 左: 説明
    add_text(s, "セキュリティ研究者が日々まとめている",
             x=0.6, y=1.95, w=6.5, h=0.5, size=15, color=TEXT)
    add_text(s, "「既知の悪いもの」",
             x=0.6, y=2.55, w=6.5, h=0.6, size=26, color=TEXT_BRIGHT,
             font=FONT_HEAD, bold=True)
    add_text(s, "を 自動で取り込みます。",
             x=0.6, y=3.2, w=6.5, h=0.5, size=18, color=ACCENT_2)

    add_text(s, "もしあなたの PC で",
             x=0.6, y=4.25, w=6.5, h=0.4, size=14, color=TEXT)
    add_text(s, "それらに該当する動きがあれば、",
             x=0.6, y=4.65, w=6.5, h=0.4, size=14, color=TEXT)
    add_text(s, "即座に警告します。",
             x=0.6, y=5.05, w=6.5, h=0.5, size=18, color=ACCENT,
             bold=True)

    add_text(s, "💡 リストはボタン一発、または自動で更新。",
             x=0.6, y=6.2, w=6.5, h=0.4, size=12, color=MUTED)
    add_text(s, "    常に最新の脅威情報で守られます。",
             x=0.6, y=6.55, w=6.5, h=0.4, size=12, color=MUTED)

    # 右: 数字の callout
    add_card(s, 7.3, 1.95, 5.5, 5.0, fill=BG_PANEL2, accent_left=ACCENT)
    add_text(s, "現在の取り込み実績",
             x=7.5, y=2.1, w=5.0, h=0.4, size=11, color=MUTED)

    # 大きな数字
    add_text(s, "82,679",
             x=7.5, y=2.6, w=5.2, h=1.6,
             size=92, color=ACCENT_2, font=FONT_HEAD, bold=True,
             align=PP_ALIGN.CENTER)
    add_text(s, "件の「既知の悪」を保持",
             x=7.5, y=4.2, w=5.2, h=0.5, size=15, color=TEXT,
             align=PP_ALIGN.CENTER)

    # 内訳
    sources = [
        ("悪性プログラムのハッシュ", "約 4,400 件"),
        ("攻撃用 URL",           "約 78,000 件"),
        ("攻撃者の通信先 IP",      "数件 (毎日更新)"),
    ]
    sy = 5.0
    for name, count in sources:
        add_text(s, "• " + name, x=7.5, y=sy, w=3.6, h=0.35,
                 size=11, color=TEXT)
        add_text(s, count, x=11.2, y=sy, w=1.5, h=0.35,
                 size=11, color=ACCENT_2, bold=True, align=PP_ALIGN.RIGHT)
        sy += 0.4
    page_no(s, n, total)


def slide_demo(prs, n, total):
    """9: デモ — フルブリードのセクション扉."""
    s = add_dark_slide(prs)
    add_text(s, "DEMO", x=0.6, y=2.4, w=12, h=1.2,
             size=110, color=ACCENT, font=FONT_HEAD, bold=True,
             align=PP_ALIGN.CENTER)
    add_text(s, "実際の画面で動かしてみます",
             x=0.6, y=3.9, w=12, h=0.6, size=24, color=TEXT,
             italic=True, align=PP_ALIGN.CENTER)
    add_text(s, "サンプルログを読み込み、調査の流れを見ていただきます。",
             x=0.6, y=4.7, w=12, h=0.5, size=15, color=MUTED,
             align=PP_ALIGN.CENTER)
    page_no(s, n, total)


def slide_numbers(prs, n, total):
    """10: 規模感 — 親しみやすい 4 つの数字."""
    s = add_dark_slide(prs)
    slide_header_strip(s, "数字で見ると", kicker="07  規模感")

    stats = [
        ("82,679", "件",  "既知の悪いものリスト",  ACCENT_2),
        ("30+",   "種類", "対応する攻撃の手口",   HIGH),
        ("4,000",  "行", "プログラムの規模",     LOW),
        ("0",      "件", "外部に必要な追加ソフト", OK),
    ]
    card_w = 2.95
    for i, (num, unit, label, color) in enumerate(stats):
        x = 0.6 + i * (card_w + 0.2)
        y = 2.5
        add_card(s, x, y, card_w, 4.0, fill=BG_PANEL, accent_left=color)
        # 数字
        add_text(s, num, x=x, y=y + 0.5, w=card_w, h=1.6,
                 size=72, color=color, font=FONT_HEAD, bold=True,
                 align=PP_ALIGN.CENTER)
        # 単位
        add_text(s, unit, x=x, y=y + 2.0, w=card_w, h=0.5,
                 size=24, color=TEXT, font=FONT_HEAD,
                 align=PP_ALIGN.CENTER)
        # ラベル
        add_text(s, label, x=x + 0.2, y=y + 2.95, w=card_w - 0.4, h=0.9,
                 size=14, color=MUTED, align=PP_ALIGN.CENTER,
                 line_spacing=1.4)

    add_text(s, "個人で開発、すべて公開しています。",
             x=0.6, y=6.85, w=12, h=0.4, size=13, color=MUTED,
             italic=True, align=PP_ALIGN.CENTER)
    page_no(s, n, total)


def slide_thanks(prs, n, total):
    s = add_dark_slide(prs)
    add_text(s, "ありがとうございました",
             x=0.6, y=1.7, w=12, h=1.2,
             size=56, color=TEXT_BRIGHT, font=FONT_HEAD, bold=True,
             align=PP_ALIGN.CENTER)
    add_text(s, "ご質問・フィードバックをお願いします",
             x=0.6, y=2.9, w=12, h=0.6, size=22, color=ACCENT_2,
             italic=True, align=PP_ALIGN.CENTER)

    add_card(s, 3.0, 4.0, 7.3, 1.7, fill=BG_PANEL, accent_left=ACCENT)
    add_text(s, "GitHub で公開中", x=3.3, y=4.15, w=6.8, h=0.4,
             size=12, color=MUTED)
    add_text(s, "github.com/Assy2005/hayabusa-plus",
             x=3.3, y=4.5, w=6.8, h=0.6, size=24,
             color=ACCENT_2, font=FONT_MONO, bold=True)
    add_text(s, "どなたでも自由にお使いいただけます (OSS)",
             x=3.3, y=5.15, w=6.8, h=0.4, size=13, color=MUTED, italic=True)

    add_text(s, "今、お手元の PC でも試せます。",
             x=0.6, y=6.85, w=12, h=0.4, size=12, color=MUTED,
             italic=True, align=PP_ALIGN.CENTER)


# ===========================================================================
# main
# ===========================================================================

def main():
    prs = new_pres()
    prs.title  = "hayabusa-plus (一般向け)"
    prs.author = "hayabusa-plus"

    total = 10
    slide_title(prs, total)               # 1 — タイトル (番号なし)
    slide_question(prs, 2, total)         # 2 — 問いかけ
    slide_problem(prs, 3, total)          # 3 — 課題
    slide_solution(prs, 4, total)         # 4 — 解決策
    slide_feature_priority(prs, 5, total) # 5 — 機能 ①
    slide_feature_explain(prs, 6, total)  # 6 — 機能 ②
    slide_feature_anomaly(prs, 7, total)  # 7 — 機能 ③
    slide_feature_iocheck(prs, 8, total)  # 8 — 機能 ④
    slide_demo(prs, 9, total)             # 9 — デモ
    slide_numbers(prs, 10, total)         # 10 — 数字
    slide_thanks(prs, total, total)       # 11 — ありがとう

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
