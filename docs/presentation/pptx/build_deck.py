"""
hayabusa-plus 発表用 PowerPoint (.pptx) 生成スクリプト
========================================================

10 枚構成の簡潔版。発表時間 12-15 分 (+ デモ 5 分 + Q&A 5 分) を想定。

実行:
    python build_deck.py

出力:
    hayabusa-plus.pptx  (このスクリプトと同じディレクトリ)

設計方針:
    - GUI と同じダークテーマ (#0b0d12 + #ff5722 アクセント)
    - スライドごとに異なる構図を採用、単調にしない
    - フォント: 見出し Cambria、本文 Calibri
    - 16:9 ワイドスクリーン
"""

from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn
from lxml import etree


# ---------------------------------------------------------------------------
# カラーパレット (GUI と統一)
# ---------------------------------------------------------------------------
BG_DARK    = RGBColor(0x0B, 0x0D, 0x12)   # メイン背景
BG_PANEL   = RGBColor(0x16, 0x1B, 0x26)   # カード背景
BG_PANEL2  = RGBColor(0x1F, 0x29, 0x42)   # アクティブ要素
LINE       = RGBColor(0x2A, 0x36, 0x54)
ACCENT     = RGBColor(0xFF, 0x57, 0x22)   # 主アクセント (オレンジ)
ACCENT_2   = RGBColor(0xFF, 0xAB, 0x40)   # ゴールド
TEXT       = RGBColor(0xD8, 0xDE, 0xF0)   # 本文
TEXT_BRIGHT= RGBColor(0xFF, 0xFF, 0xFF)
MUTED      = RGBColor(0x7D, 0x86, 0x9C)   # 補足

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
    """16:9 ワイドプレゼンを作る (10" x 5.625")."""
    prs = Presentation()
    prs.slide_width  = Inches(13.333)
    prs.slide_height = Inches(7.5)
    return prs


def add_dark_slide(prs, bg=BG_DARK):
    """背景を塗りつぶした空白スライドを追加。"""
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
             line_spacing=1.2):
    """テキストボックスを 1 メソッドで配置する省略形ヘルパ。"""
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


def add_multi(slide, lines, *, x, y, w, h, size=14, color=TEXT,
              font=FONT_BODY, bullet=False, line_spacing=1.4,
              space_after=4):
    """複数行テキスト。各行は str か (text, opts) のタプル。"""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Pt(0)
    for i, line in enumerate(lines):
        if isinstance(line, tuple):
            text, opts = line
        else:
            text, opts = line, {}
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = opts.get("align", PP_ALIGN.LEFT)
        p.line_spacing = line_spacing
        p.space_after = Pt(opts.get("space_after", space_after))
        if bullet or opts.get("bullet"):
            _set_bullet(p)
        run = p.add_run()
        run.text = text
        run.font.name = opts.get("font", font)
        run.font.size = Pt(opts.get("size", size))
        run.font.bold = opts.get("bold", False)
        run.font.italic = opts.get("italic", False)
        run.font.color.rgb = opts.get("color", color)
    return tb


def _set_bullet(paragraph):
    """段落に bullet を付ける (PPTX OOXML 直書き)."""
    pPr = paragraph._p.get_or_add_pPr()
    # remove any existing bullet first
    for tag in ("a:buChar", "a:buAutoNum", "a:buNone"):
        for existing in pPr.findall(qn(tag)):
            pPr.remove(existing)
    bu = etree.SubElement(pPr, qn("a:buChar"))
    bu.set("char", "•")
    pPr.set("marL", "228600")
    pPr.set("indent", "-228600")


def add_card(slide, x, y, w, h, *, fill=BG_PANEL, accent_left=None):
    """角丸カード (左に細いアクセントバーをオプションで付ける)."""
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


def add_pill(slide, text, *, x, y, w, h, color=ACCENT, text_color=TEXT_BRIGHT,
             size=11):
    """丸まったタグ風のラベル。"""
    pill = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    pill.fill.solid()
    pill.fill.fore_color.rgb = color
    pill.line.fill.background()
    pill.shadow.inherit = False
    pill.adjustments[0] = 0.5
    tf = pill.text_frame
    tf.margin_left = tf.margin_right = Pt(6)
    tf.margin_top = tf.margin_bottom = Pt(0)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = text
    run.font.name = FONT_BODY
    run.font.size = Pt(size)
    run.font.bold = True
    run.font.color.rgb = text_color
    return pill


def page_no(slide, n, total):
    """右下にページ番号."""
    add_text(slide, f"{n} / {total}", x=12.3, y=7.1, w=1.0, h=0.3,
             size=9, color=MUTED, align=PP_ALIGN.RIGHT)


def slide_header_strip(slide, title, *, kicker=None):
    """全画面共通のヘッダ。上部にタイトル + 細いアクセントライン。"""
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
# スライド定義
# ===========================================================================

def slide_title(prs, total):
    s = add_dark_slide(prs)
    # 上下の細いアクセント
    bar_top = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(2.6), prs.slide_width, Inches(0.04))
    bar_top.fill.solid(); bar_top.fill.fore_color.rgb = ACCENT
    bar_top.line.fill.background(); bar_top.shadow.inherit = False

    add_text(s, "🦅", x=0.6, y=1.0, w=2, h=1.2,
             size=80, color=ACCENT, align=PP_ALIGN.LEFT)
    add_text(s, "hayabusa-plus",
             x=2.0, y=1.05, w=11, h=1.3,
             size=72, color=TEXT_BRIGHT, font=FONT_HEAD, bold=True)
    add_text(s, "Hayabusa を拡張した、ブラウザで使う DFIR 解析プラットフォーム",
             x=2.0, y=2.05, w=11, h=0.6, size=22,
             color=ACCENT_2, font=FONT_BODY, italic=True)

    # サブ説明
    add_text(s, "EVTX を投げ込むだけで",
             x=0.6, y=3.4, w=12, h=0.5, size=22, color=MUTED,
             align=PP_ALIGN.CENTER)
    add_text(s, "Sigma 検知 + IoC 照合 + 攻撃の系統再構築 + 振舞い異常検知",
             x=0.6, y=3.9, w=12, h=0.6, size=24, color=TEXT_BRIGHT,
             font=FONT_HEAD, bold=True, align=PP_ALIGN.CENTER)
    add_text(s, "を一画面で",
             x=0.6, y=4.6, w=12, h=0.5, size=22, color=MUTED,
             align=PP_ALIGN.CENTER)

    # フッタ
    add_text(s, "github.com/Assy2005/hayabusa-plus",
             x=0.6, y=6.7, w=12, h=0.4, size=14, color=MUTED,
             font=FONT_MONO, align=PP_ALIGN.CENTER)


def slide_problem(prs, n, total):
    s = add_dark_slide(prs)
    slide_header_strip(s, "Hayabusa CLI 単体ではここで困る", kicker="01  PROBLEM")

    pains = [
        ("📊", "結果が CSV / JSON の山", "1 ホスト 1 日でも数万件。Excel で開いて grep…という運用"),
        ("❓", "「このホスト、危ないの?」即答できない", "誰が誰に侵入されたか、ホスト単位の優先度が見えない"),
        ("🧬", "プロセスの親子関係が分からない", "誰がこれを実行させたのか、毎回手で grep して並べる"),
        ("📉", "「いつもと違う」が見えない", "バースト / 拡散 / 沈黙 は Sigma ルールで書けない"),
        ("🧹", "攻撃者がログを消したことに気付けない", "痕跡隠蔽自体を検知するレイヤがない"),
        ("🛡️", "IoC フィードを取り込むたびにルール書換", "LOLDrivers / abuse.ch を運用に乗せる手間"),
    ]
    cols, gap = 3, 0.3
    card_w = (13.33 - 1.2 - gap * (cols - 1)) / cols
    card_h = 1.6
    for i, (icon, title, body) in enumerate(pains):
        row, col = i // cols, i % cols
        x = 0.6 + col * (card_w + gap)
        y = 1.8 + row * (card_h + 0.25)
        add_card(s, x, y, card_w, card_h, fill=BG_PANEL, accent_left=ACCENT)
        add_text(s, icon, x=x + 0.18, y=y + 0.18, w=0.6, h=0.6,
                 size=24, color=ACCENT_2)
        add_text(s, title, x=x + 0.85, y=y + 0.15, w=card_w - 1.0, h=0.5,
                 size=14, color=TEXT_BRIGHT, font=FONT_HEAD, bold=True)
        add_text(s, body, x=x + 0.85, y=y + 0.65, w=card_w - 1.0, h=0.85,
                 size=11, color=MUTED, line_spacing=1.3)
    page_no(s, n, total)


def slide_solution(prs, n, total):
    s = add_dark_slide(prs)
    slide_header_strip(s, "Hayabusa の上に DFIR 運用層を被せる", kicker="02  SOLUTION")

    add_text(s,
             "EVTX を投げ込むだけで、Sigma 検知 + IoC フィード照合 + 攻撃の系統再構築 + "
             "異常パターン抽出を行うローカル DFIR コンソール。",
             x=0.6, y=1.8, w=12, h=1.0, size=18, color=TEXT,
             italic=True, line_spacing=1.5)

    # 3 つのキーバリュー
    keys = [
        ("🔒", "ローカル完結", "外部にデータが出ない。ブラウザ 1 つで完結"),
        ("📦", "外部依存ゼロ", "Python があれば動く。pip install / npm install 不要"),
        ("🆓", "OSS", "GPL-3.0、GitHub で公開、PR / Issue 歓迎"),
    ]
    card_w = 3.9
    for i, (icon, title, body) in enumerate(keys):
        x = 0.6 + i * (card_w + 0.4)
        y = 3.5
        add_card(s, x, y, card_w, 2.4, fill=BG_PANEL2, accent_left=ACCENT)
        add_text(s, icon, x=x + 0.3, y=y + 0.3, w=1.0, h=0.8,
                 size=32, color=ACCENT_2)
        add_text(s, title, x=x + 0.3, y=y + 1.1, w=card_w - 0.5, h=0.5,
                 size=20, color=TEXT_BRIGHT, font=FONT_HEAD, bold=True)
        add_text(s, body, x=x + 0.3, y=y + 1.65, w=card_w - 0.5, h=0.7,
                 size=12, color=MUTED, line_spacing=1.4)

    page_no(s, n, total)


def slide_features(prs, n, total):
    s = add_dark_slide(prs)
    slide_header_strip(s, "6 つの主要機能", kicker="03  FEATURES")

    features = [
        ("01", "EVTX ブラウザ解析",      "ドロップ&ドロップ → リアルタイム検知ストリーム", ACCENT),
        ("02", "スレットハンティング",   "6 個の仮説プリセット / 5 種のピボット",       ACCENT),
        ("03", "プロセスツリー",         "Sysmon EID 1 から親子関係を可視化",             HIGH),
        ("04", "振舞い異常検知",         "バースト / 拡散 / 沈黙 / 時間外",               HIGH),
        ("05", "IoC フィード自動取込",   "LOLDrivers / abuse.ch — 8 万件超の IoC",        MED),
        ("06", "ホスト資産ビュー",       "リスクスコア順、TP/FP 補正、直近度補正",       MED),
    ]
    cols = 3
    card_w = 3.9
    card_h = 2.3
    for i, (num, title, body, color) in enumerate(features):
        row, col = i // cols, i % cols
        x = 0.6 + col * (card_w + 0.4)
        y = 1.85 + row * (card_h + 0.35)
        add_card(s, x, y, card_w, card_h, fill=BG_PANEL, accent_left=color)
        # ナンバー
        add_text(s, num, x=x + 0.25, y=y + 0.2, w=1.0, h=0.6,
                 size=28, color=color, font=FONT_HEAD, bold=True)
        # タイトル
        add_text(s, title, x=x + 0.25, y=y + 0.85, w=card_w - 0.4, h=0.55,
                 size=17, color=TEXT_BRIGHT, font=FONT_HEAD, bold=True)
        # 説明
        add_text(s, body, x=x + 0.25, y=y + 1.45, w=card_w - 0.4, h=0.75,
                 size=12, color=MUTED, line_spacing=1.4)

    page_no(s, n, total)


def slide_demo(prs, n, total):
    s = add_dark_slide(prs)
    # セクション区切り風: 大きなタイトル中央
    add_text(s, "DEMO", x=0.6, y=2.4, w=12, h=1.2,
             size=110, color=ACCENT, font=FONT_HEAD, bold=True,
             align=PP_ALIGN.CENTER)
    add_text(s, "ライブで動かします", x=0.6, y=3.9, w=12, h=0.6,
             size=24, color=TEXT, italic=True, align=PP_ALIGN.CENTER)
    add_text(s, "http://127.0.0.1:8787", x=0.6, y=4.7, w=12, h=0.5,
             size=18, color=MUTED, font=FONT_MONO, align=PP_ALIGN.CENTER)

    # 進行予告
    flow = "  スキャン → 解説 → プロセスツリー → ハント → 振舞い異常 → ホスト"
    add_text(s, flow, x=0.6, y=5.8, w=12, h=0.5,
             size=13, color=MUTED, font=FONT_MONO, align=PP_ALIGN.CENTER)
    page_no(s, n, total)


def slide_tech_lookup(prs, n, total):
    s = add_dark_slide(prs)
    slide_header_strip(s, "技術①  lookup: Sigma 拡張", kicker="04  ENGINE")

    # 左: 説明
    add_multi(s, [
        ("既存の Sigma に新しい構文を追加した。",
         {"size": 16, "color": TEXT, "italic": True, "space_after": 12}),
        ("`lookup:` ブロックで外部ファイルを宣言。",
         {"size": 14, "color": TEXT, "bullet": True}),
        ("`|lookup:` 修飾子で 1 行参照、内部は HashMap で O(1)。",
         {"size": 14, "color": TEXT, "bullet": True}),
        ("起動時にロード、ルール側に値を埋め込む必要なし。",
         {"size": 14, "color": TEXT, "bullet": True}),
        ("既存ルール無改造で IoC ベース検知を一気に増やせる。",
         {"size": 14, "color": ACCENT_2, "bullet": True, "bold": True}),
    ], x=0.6, y=1.85, w=6.0, h=4)

    add_text(s, "実装規模: 約 400 行 (Rust)",
             x=0.6, y=5.6, w=6.0, h=0.4, size=13, color=ACCENT,
             font=FONT_MONO, bold=True)
    add_text(s, "upstream へ PR 投稿を予定",
             x=0.6, y=6.0, w=6.0, h=0.4, size=12, color=MUTED, italic=True)

    # 右: YAML 例
    add_card(s, 7.1, 1.85, 5.6, 4.5, fill=RGBColor(0x08, 0x0A, 0x10),
             accent_left=ACCENT)
    add_text(s, "rules-custom/hayfx_lookup_loldriver_load.yml",
             x=7.3, y=1.95, w=5.4, h=0.3, size=10, color=MUTED,
             font=FONT_MONO)

    code_lines = [
        ("title:", "Known vulnerable driver loaded"),
        ("lookup:", ""),
        ("  - name:", "lol_drivers"),
        ("    file:", "../../../lookups/loldrivers.txt"),
        ("detection:", ""),
        ("  sel:", ""),
        ("    Channel:", "'Microsoft-Windows-Sysmon/Operational'"),
        ("    EventID:", "6"),
        ("    Hashes|lookup:", "lol_drivers"),
        ("  condition:", "sel"),
        ("level:", "critical"),
    ]
    line_y = 2.4
    for k, v in code_lines:
        # key
        add_text(s, k, x=7.3, y=line_y, w=2.2, h=0.28, size=12,
                 color=ACCENT, font=FONT_MONO)
        if v:
            add_text(s, v, x=9.5, y=line_y, w=3.2, h=0.28, size=12,
                     color=ACCENT_2, font=FONT_MONO)
        line_y += 0.33

    page_no(s, n, total)


def slide_tech_behavioral(prs, n, total):
    s = add_dark_slide(prs)
    slide_header_strip(s, "技術②  振舞い異常検知", kicker="05  ANALYSIS")

    add_text(s,
             "Sigma が「1 イベントを見て yes/no」を出すのに対し、振舞い検知は「集合の異常」を出す。",
             x=0.6, y=1.85, w=12, h=0.6, size=15, color=TEXT, italic=True)

    types = [
        ("バースト", "BURST",
         "ルールが平常比 8 倍以上発火", "C2 / 大量 PS / ブルートフォース",
         HIGH),
        ("拡散", "SPREAD",
         "同一ルールが 3 ホスト以上",  "横展開 / 配布スクリプト",
         CRIT),
        ("沈黙", "SILENCE",
         "通常活動するホストが 6 時間以上ゼロ", "ログ抑止 / 攻撃者がログを消した",
         LOW),
        ("時間外", "OFF-HOURS",
         "深夜帯 (0-6時) の high/critical", "業務時間外を狙った攻撃",
         MED),
    ]
    card_w = 2.95
    for i, (name_ja, name_en, cond, story, c) in enumerate(types):
        x = 0.6 + i * (card_w + 0.2)
        y = 2.8
        add_card(s, x, y, card_w, 3.5, fill=BG_PANEL, accent_left=c)
        add_text(s, name_ja, x=x + 0.2, y=y + 0.15, w=card_w - 0.3, h=0.55,
                 size=22, color=c, font=FONT_HEAD, bold=True)
        add_text(s, name_en, x=x + 0.2, y=y + 0.7, w=card_w - 0.3, h=0.3,
                 size=11, color=MUTED, font=FONT_MONO)
        # 検知条件
        add_text(s, "検知条件", x=x + 0.2, y=y + 1.15, w=card_w, h=0.25,
                 size=9, color=MUTED, bold=True)
        add_text(s, cond, x=x + 0.2, y=y + 1.42, w=card_w - 0.3, h=0.8,
                 size=11, color=TEXT, line_spacing=1.3)
        # 攻撃シナリオ
        add_text(s, "シナリオ", x=x + 0.2, y=y + 2.3, w=card_w, h=0.25,
                 size=9, color=MUTED, bold=True)
        add_text(s, story, x=x + 0.2, y=y + 2.55, w=card_w - 0.3, h=0.8,
                 size=11, color=TEXT, line_spacing=1.3)

    # 実例 highlight
    add_card(s, 0.6, 6.45, 12.1, 0.85, fill=BG_PANEL2, accent_left=ACCENT)
    add_text(s, "実データで検出: ",
             x=0.85, y=6.6, w=2.5, h=0.55, size=14,
             color=MUTED, anchor=MSO_ANCHOR.MIDDLE)
    add_text(s, "Potentially Malicious PwSh が ",
             x=2.85, y=6.6, w=3.6, h=0.55, size=14,
             color=TEXT, anchor=MSO_ANCHOR.MIDDLE)
    add_text(s, "平常の 2,492 倍 ",
             x=6.0, y=6.6, w=3.0, h=0.55, size=18,
             color=ACCENT_2, font=FONT_HEAD, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    add_text(s, "バーストを自動検出",
             x=8.7, y=6.6, w=4.0, h=0.55, size=14,
             color=TEXT, anchor=MSO_ANCHOR.MIDDLE)
    page_no(s, n, total)


def slide_numbers(prs, n, total):
    s = add_dark_slide(prs)
    slide_header_strip(s, "数字で見る hayabusa-plus", kicker="06  STATS")

    # 4 つの大きな数字 callout
    stats_top = [
        ("11",      "自作 Sigma ルール"),
        ("82,679",  "統合 IoC 件数"),
        ("4",       "IoC フィード"),
        ("0",       "外部 pip / npm 依存"),
    ]
    stats_bot = [
        ("~400",    "Rust 拡張 LoC"),
        ("~3,300",  "GUI コード LoC"),
        ("30+",     "ATT&CK 技術 (日本語辞書)"),
        ("30 章",   "ARCHITECTURE.md"),
    ]
    card_w = 2.95
    card_h = 2.05
    for i, (num, label) in enumerate(stats_top):
        x = 0.6 + i * (card_w + 0.2)
        y = 2.0
        add_card(s, x, y, card_w, card_h, fill=BG_PANEL, accent_left=ACCENT)
        add_text(s, num, x=x, y=y + 0.25, w=card_w, h=1.2,
                 size=56, color=ACCENT_2, font=FONT_HEAD, bold=True,
                 align=PP_ALIGN.CENTER)
        add_text(s, label, x=x, y=y + 1.5, w=card_w, h=0.45,
                 size=13, color=TEXT, align=PP_ALIGN.CENTER)

    for i, (num, label) in enumerate(stats_bot):
        x = 0.6 + i * (card_w + 0.2)
        y = 4.4
        add_card(s, x, y, card_w, card_h, fill=BG_PANEL, accent_left=HIGH)
        add_text(s, num, x=x, y=y + 0.25, w=card_w, h=1.2,
                 size=56, color=TEXT_BRIGHT, font=FONT_HEAD, bold=True,
                 align=PP_ALIGN.CENTER)
        add_text(s, label, x=x, y=y + 1.5, w=card_w, h=0.45,
                 size=13, color=MUTED, align=PP_ALIGN.CENTER)

    page_no(s, n, total)


def slide_before_after(prs, n, total):
    s = add_dark_slide(prs)
    slide_header_strip(s, "Before / After", kicker="07  COMPARISON")

    pairs = [
        ("結果の見方", "巨大な CSV を Excel で開く", "ブラウザで多軸絞り込み + ピボット"),
        ("検知の理解", "自分で ATT&CK を調べる", "クリックで日本語解説 + 次手"),
        ("親子関係",   "手で grep して並べる", "プロセスツリー自動構築"),
        ("いつもと違う", "検出不可", "バースト / 拡散 / 沈黙 を自動抽出"),
        ("IoC 照合",   "都度ルール書き換え", "1 行で参照 + フィード自動更新"),
        ("ホスト優先", "自分で集計", "リスクスコア順で一覧"),
        ("ログ消去",   "気付かない", "沈黙検知 + 痕跡隠蔽ルール 5 本"),
    ]
    # ヘッダ
    add_text(s, "観点", x=0.7, y=1.8, w=2.5, h=0.4,
             size=11, color=ACCENT, bold=True)
    add_text(s, "Hayabusa CLI 単体", x=3.5, y=1.8, w=4.5, h=0.4,
             size=11, color=MUTED, bold=True)
    add_text(s, "hayabusa-plus", x=8.5, y=1.8, w=4.5, h=0.4,
             size=11, color=ACCENT_2, bold=True)

    y = 2.3
    row_h = 0.6
    for axis, before, after in pairs:
        # 縞模様
        bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                Inches(0.6), Inches(y),
                                Inches(12.1), Inches(row_h - 0.05))
        bg.fill.solid()
        bg.fill.fore_color.rgb = BG_PANEL
        bg.line.fill.background()
        bg.shadow.inherit = False

        add_text(s, axis, x=0.85, y=y + 0.08, w=2.5, h=row_h - 0.15,
                 size=13, color=ACCENT, bold=True,
                 anchor=MSO_ANCHOR.MIDDLE)
        add_text(s, before, x=3.5, y=y + 0.08, w=4.5, h=row_h - 0.15,
                 size=12, color=MUTED,
                 anchor=MSO_ANCHOR.MIDDLE)
        # 矢印
        add_text(s, "→", x=7.95, y=y + 0.08, w=0.5, h=row_h - 0.15,
                 size=14, color=ACCENT_2, bold=True,
                 anchor=MSO_ANCHOR.MIDDLE)
        add_text(s, after, x=8.5, y=y + 0.08, w=4.3, h=row_h - 0.15,
                 size=12, color=TEXT,
                 anchor=MSO_ANCHOR.MIDDLE, bold=True)
        y += row_h
    page_no(s, n, total)


def slide_roadmap(prs, n, total):
    s = add_dark_slide(prs)
    slide_header_strip(s, "ロードマップ", kicker="08  WHAT'S NEXT")

    # 完了済み (上段)
    add_text(s, "完了済み", x=0.6, y=1.85, w=4, h=0.4,
             size=14, color=OK, font=FONT_HEAD, bold=True)
    done = [
        "EVTX ブラウザ解析・ライブフィード",
        "スレットハンティング (6 プリセット / 5 ピボット)",
        "プロセスツリー再構築",
        "振舞い異常検知 (4 種)",
        "IoC フィード自動取込 (4 フィード)",
        "ホスト資産ビュー + リスクスコア",
        "lookup: Sigma 拡張 (Rust)",
        "セキュリティ強化 (DNS rebind / CSRF / CSP)",
    ]
    for i, item in enumerate(done):
        row, col = i // 4, i % 4
        x = 0.6 + col * 3.1
        y = 2.3 + row * 0.5
        # チェックマーク
        add_text(s, "✓", x=x, y=y, w=0.3, h=0.4,
                 size=15, color=OK, bold=True)
        add_text(s, item, x=x + 0.35, y=y + 0.02, w=2.8, h=0.4,
                 size=11, color=TEXT)

    # 区切り
    sep = s.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                             Inches(0.6), Inches(3.9), Inches(12.1), Inches(0.02))
    sep.fill.solid(); sep.fill.fore_color.rgb = LINE
    sep.line.fill.background(); sep.shadow.inherit = False

    # これから
    add_text(s, "これから", x=0.6, y=4.15, w=4, h=0.4,
             size=14, color=ACCENT, font=FONT_HEAD, bold=True)

    todos = [
        ("週次レポート / ヒートマップ", "アラート分析の高度化"),
        ("`correlate:` Sigma 拡張", "時系列相関 (Rust)"),
        ("`behavioral:` Sigma 拡張", "ルートレベルでレート異常を書ける"),
        ("AI 補助ルール生成", "脅威レポート → Sigma 半自動"),
        ("集合ホスト比較ビュー", "フリート横断の異常検知"),
        ("`eid-metrics` 統合", "真のギャップ分析"),
    ]
    for i, (title, desc) in enumerate(todos):
        row, col = i // 3, i % 3
        x = 0.6 + col * 4.1
        y = 4.6 + row * 1.05
        add_card(s, x, y, 4.0, 0.9, fill=BG_PANEL, accent_left=ACCENT)
        add_text(s, title, x=x + 0.2, y=y + 0.1, w=3.7, h=0.4,
                 size=12, color=TEXT_BRIGHT, font=FONT_HEAD, bold=True)
        add_text(s, desc, x=x + 0.2, y=y + 0.5, w=3.7, h=0.4,
                 size=10, color=MUTED)
    page_no(s, n, total)


def slide_thanks(prs, n, total):
    s = add_dark_slide(prs)
    # 中央メッセージ
    add_text(s, "ありがとうございました",
             x=0.6, y=1.8, w=12, h=1.2,
             size=56, color=TEXT_BRIGHT, font=FONT_HEAD, bold=True,
             align=PP_ALIGN.CENTER)
    add_text(s, "ご清聴感謝します",
             x=0.6, y=3.0, w=12, h=0.6, size=22, color=ACCENT_2,
             italic=True, align=PP_ALIGN.CENTER)

    # GitHub URL カード
    add_card(s, 3.2, 4.2, 7.0, 1.5, fill=BG_PANEL, accent_left=ACCENT)
    add_text(s, "GitHub", x=3.5, y=4.35, w=6.5, h=0.4,
             size=12, color=MUTED, font=FONT_BODY)
    add_text(s, "github.com/Assy2005/hayabusa-plus",
             x=3.5, y=4.7, w=6.5, h=0.5, size=22,
             color=ACCENT_2, font=FONT_MONO, bold=True)
    add_text(s, "Issue / PR / フィードバック歓迎",
             x=3.5, y=5.25, w=6.5, h=0.35, size=12, color=MUTED, italic=True)

    # フッタ
    add_text(s, "Made with detection engineering depth, not marketing fluff.",
             x=0.6, y=6.85, w=12, h=0.4, size=11, color=MUTED,
             italic=True, align=PP_ALIGN.CENTER)


# ===========================================================================
# main
# ===========================================================================

def main():
    prs = new_pres()
    prs.title  = "hayabusa-plus"
    prs.author = "hayabusa-plus"

    total = 10
    slide_title(prs, total)                  # 1
    slide_problem(prs, 2, total)             # 2
    slide_solution(prs, 3, total)            # 3
    slide_features(prs, 4, total)            # 4
    slide_demo(prs, 5, total)                # 5  (デモ区切り)
    slide_tech_lookup(prs, 6, total)         # 6
    slide_tech_behavioral(prs, 7, total)     # 7
    slide_numbers(prs, 8, total)             # 8
    slide_before_after(prs, 9, total)        # 9
    slide_roadmap(prs, 10, total)            # 10
    slide_thanks(prs, total, total)          # 11 (thanks, no number shown)

    # 内部的には 11 枚 (Title はカウントしない流儀でも 10 + Thanks)
    out = Path(__file__).parent / "hayabusa-plus.pptx"
    prs.save(str(out))
    print(f"OK -> {out}")
    print(f"   slides: {len(prs.slides)}")


if __name__ == "__main__":
    main()
