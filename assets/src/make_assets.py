"""Builds the README visuals of done-means-seen: hero.svg (animated), ladder.svg, receipt.svg, social.svg.

    python3 assets/src/make_assets.py            # writes into assets/

DM Mono (SIL OFL, see assets/OFL-DM-Mono.txt) is subset to Latin and embedded, so the SVGs render
the same everywhere, including GitHub's <img>. social.svg is rendered to assets/social.png
(1280 x 640) with a headless browser for the repository's social preview.
"""
import base64
import sys
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent
OUT.mkdir(parents=True, exist_ok=True)

FONT_R = base64.b64encode((HERE / "fonts" / "dmmono-Regular.woff2").read_bytes()).decode()
FONT_M = base64.b64encode((HERE / "fonts" / "dmmono-Medium.woff2").read_bytes()).decode()
FONTS = f"""
@font-face {{ font-family: 'DMM'; font-weight: 400; src: url(data:font/woff2;base64,{FONT_R}) format('woff2'); }}
@font-face {{ font-family: 'DMM'; font-weight: 500; src: url(data:font/woff2;base64,{FONT_M}) format('woff2'); }}
text {{ font-family: 'DMM', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
"""

BG = "#0d0d0c"
PANEL = "#121211"
RULE = "#2a2a27"
INK = "#ecebe6"
MUTED = "#85847e"
DIM = "#55544f"
RED = "#ff5a4e"
AMBER = "#ffb224"
GREEN = "#35d07f"
OFF = {"red": "#3a1916", "amber": "#3a2c10", "green": "#11301f"}
ON = {"red": RED, "amber": AMBER, "green": GREEN}


def t(x, y, s, size, fill=INK, weight=400, spacing=0, anchor="start", cls="", extra=""):
    c = f' class="{cls}"' if cls else ""
    ls = f' letter-spacing="{spacing}"' if spacing else ""
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}"{ls} '
            f'text-anchor="{anchor}"{c}{extra}>{escape(s)}</text>')


def lamp(x, y, scale=1.0, lit=None, animated=False):
    """An andon stack light: cap, three lamps, pole. `lit` = which lamp is on in the static drawing."""
    s = scale
    w, lh, gap = 22 * s, 15 * s, 3 * s
    parts = [f'<rect x="{x - 2 * s}" y="{y - 6 * s}" width="{w + 4 * s}" height="{5 * s}" fill="#2c2c29"/>']
    for i, color in enumerate(["red", "amber", "green"]):
        ly = y + i * (lh + gap)
        parts.append(f'<rect x="{x}" y="{ly}" width="{w}" height="{lh}" fill="{OFF[color]}"/>')
        on_cls = f' class="lamp-{color}"' if animated else ""
        visible = animated or lit == color
        if visible:
            op = "" if animated else ""
            parts.append(f'<rect{on_cls} x="{x}" y="{ly}" width="{w}" height="{lh}" fill="{ON[color]}" filter="url(#glow)"{op}/>')
            parts.append(f'<rect{on_cls} x="{x + 3 * s}" y="{ly + 3 * s}" width="{6 * s}" height="{3 * s}" fill="#ffffff" opacity="0.35"/>')
    base_y = y + 3 * (lh + gap)
    parts.append(f'<rect x="{x + w / 2 - 2 * s}" y="{base_y}" width="{4 * s}" height="{12 * s}" fill="#2c2c29"/>')
    parts.append(f'<rect x="{x - 4 * s}" y="{base_y + 12 * s}" width="{w + 8 * s}" height="{4 * s}" fill="#2c2c29"/>')
    return "\n".join(parts)


GLOW = """<filter id="glow" x="-80%" y="-80%" width="260%" height="260%">
  <feGaussianBlur stdDeviation="4" result="b"/>
  <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
</filter>"""


def tag(x, y, label, size=13, fill=MUTED, sq=AMBER, anchor="end"):
    """[ ■ LABEL ] with the square drawn as a shape, right-aligned by default."""
    cw = size * 0.6
    n = 2 + 2 + len(label) + 2  # "[ " + square + " " + label + " ]"
    x0 = x - n * cw if anchor == "end" else x
    return (t(x0, y, "[", size, fill) +
            f'<rect x="{x0 + 2 * cw}" y="{y - size * 0.66}" width="{size * 0.6}" height="{size * 0.6}" fill="{sq}"/>' +
            t(x0 + 4 * cw, y, label + " ]", size, fill))


# ---------------------------------------------------------------- hero (animated)

def hero():
    W, H = 1200, 540
    CYCLE = 12.0
    size, lh = 19, 37
    x_who, x_mark, x_text = 56, 160, 186
    top = 162
    cw = size * 0.6

    lines = [
        # (who, mark, text, color, start, typed)
        ("claude", ">", "Done! The settings page now saves the user's timezone.", INK, 0.2, True),
        ("hook", "sq-red", "ERROR: the check for web-app fails after your changes.", RED, 1.6, False),
        ("", "", "npm run typecheck", MUTED, 1.8, False),
        ("", "", "src/settings.ts(4,9): Type 'string' is not assignable to type 'Timezone'.", MUTED, 2.0, False),
        ("", "", "FIX: read the output, fix the cause, hand back.   (block 1 of 3)", MUTED, 2.2, False),
        ("claude", ">", "The select returned a string. Parsing it into a Timezone.", INK, 3.2, True),
        ("hook", "sq-green", "green: web-app, typecheck 12 s", GREEN, 5.0, False),
        ("claude", ">", "Done, and seen: saved \"Europe/Paris\" on /settings, reloaded, it stuck.", INK, 5.8, True),
    ]
    css = [FONTS]
    body = []
    pct = lambda sec: f"{100 * sec / CYCLE:.2f}%"  # noqa: E731
    fade_out = pct(CYCLE - 0.6)
    for i, (who, mark, text, color, start, typed) in enumerate(lines):
        y = top + i * lh
        css.append(f"@keyframes ln{i} {{ 0%, {pct(start)} {{ opacity: 0; }} {pct(start + 0.25)}, {fade_out} {{ opacity: 1; }} 100% {{ opacity: 0; }} }}")
        css.append(f".ln{i} {{ animation: ln{i} {CYCLE}s linear infinite; }}")
        g = [f'<g class="ln{i}">']
        if who:
            g.append(t(x_who, y, who, size, MUTED if who == "claude" else DIM))
        if mark == ">":
            g.append(t(x_mark, y, ">", size, AMBER, weight=500))
        elif mark.startswith("sq-"):
            c = RED if mark == "sq-red" else GREEN
            g.append(f'<rect x="{x_mark}" y="{y - 12}" width="11" height="11" fill="{c}"/>')
        g.append(t(x_text, y, text, size, color, weight=500 if color in (RED, GREEN) else 400))
        if typed:
            n = len(text)
            dur = min(1.4, 0.02 * n)
            width = n * cw + 20
            css.append(
                f"@keyframes cv{i} {{ 0%, {pct(start)} {{ transform: translateX(0); }} "
                f"{pct(start + dur)}, 100% {{ transform: translateX({width:.0f}px); }} }}")
            css.append(f".cv{i} {{ animation: cv{i} {CYCLE}s steps({n}, end) infinite; }}")
            g.append(f'<rect class="cv{i}" x="{x_text - 2}" y="{y - size - 2}" width="{width:.0f}" height="{lh - 4}" fill="{PANEL}"/>')
        g.append("</g>")
        body.append("\n".join(g))

    # cursor after the last line
    last_y = top + (len(lines) - 1) * lh
    cur_x = x_text + len(lines[-1][2]) * cw + 6
    css.append(f"@keyframes cur {{ 0%, {pct(7.2)} {{ opacity: 0; }} {pct(7.3)}, {pct(8.0)} {{ opacity: 1; }} {pct(8.1)}, {pct(8.8)} {{ opacity: 0; }} {pct(8.9)}, {pct(9.6)} {{ opacity: 1; }} {pct(9.7)}, {pct(10.4)} {{ opacity: 0; }} {pct(10.5)}, {fade_out} {{ opacity: 1; }} 100% {{ opacity: 0; }} }}")
    css.append(f".cur {{ animation: cur {CYCLE}s linear infinite; }}")
    body.append(f'<rect class="cur" x="{cur_x:.0f}" y="{last_y - 14}" width="9" height="17" fill="{INK}"/>')

    # lamps: red while the check is red, amber while Claude fixes, green once it passes
    css.append(f"@keyframes lr {{ 0%, {pct(1.6)} {{ opacity: 0; }} {pct(1.7)}, {pct(3.1)} {{ opacity: 1; }} {pct(3.2)}, 100% {{ opacity: 0; }} }}")
    css.append(f"@keyframes la {{ 0%, {pct(3.2)} {{ opacity: 0; }} {pct(3.3)}, {pct(4.9)} {{ opacity: 1; }} {pct(5.0)}, 100% {{ opacity: 0; }} }}")
    css.append(f"@keyframes lg {{ 0%, {pct(5.0)} {{ opacity: 0; }} {pct(5.1)}, {fade_out} {{ opacity: 1; }} 100% {{ opacity: 0; }} }}")
    css.append(f".lamp-red {{ animation: lr {CYCLE}s linear infinite; }} .lamp-amber {{ animation: la {CYCLE}s linear infinite; }} .lamp-green {{ animation: lg {CYCLE}s linear infinite; }}")
    # no motion: show the end state, which tells the whole story
    css.append("@media (prefers-reduced-motion: reduce) { [class^='ln'], .cur { animation: none !important; opacity: 1 !important; } "
               "[class^='cv'] { animation: none !important; transform: translateX(2000px) !important; } "
               ".lamp-red, .lamp-amber { animation: none !important; opacity: 0 !important; } .lamp-green { animation: none !important; opacity: 1 !important; } }")

    header = [
        lamp(56, 40, 1.0, animated=True),
        t(104, 72, "DONE-MEANS-SEEN", 28, INK, weight=500, spacing=3),
        tag(W - 48, 71, "A STOP HOOK FOR CLAUDE CODE", size=16, fill="#a9a8a1"),
        f'<line x1="0" y1="114" x2="{W}" y2="114" stroke="{RULE}"/>',
    ]
    footer_y = H - 70
    footer = [
        f'<line x1="0" y1="{footer_y}" x2="{W}" y2="{footer_y}" stroke="{RULE}"/>',
        t(56, footer_y + 44, "RULE 1", 13, DIM, weight=500, spacing=2),
        t(152, footer_y + 45, "“DONE” MEANS I HAVE SEEN IT WORK.", 20, INK, weight=500, spacing=1.5),
    ]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="title desc">
<title id="title">done-means-seen</title>
<desc id="desc">A terminal. Claude says the settings page is done. The Stop hook runs the typecheck, finds an error and sends Claude back to work: the andon light turns red. Claude fixes it (amber), the check turns green, and Claude reports done again, this time having saved a value, reloaded the page and seen it stick. Footer: rule 1, "done" means I have seen it work.</desc>
<defs><style>{"".join(css)}</style>{GLOW}</defs>
<rect width="{W}" height="{H}" fill="{BG}"/>
<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" fill="none" stroke="{RULE}"/>
<rect x="1" y="115" width="{W - 2}" height="{footer_y - 116}" fill="{PANEL}"/>
{chr(10).join(header)}
{chr(10).join(body)}
{chr(10).join(footer)}
</svg>
"""
    (OUT / "hero.svg").write_text(svg)


# ---------------------------------------------------------------- ladder

def ladder():
    W, H = 1200, 480
    levels = [
        ("1", "INSTRUCTION", "a prompt, a skill,", "a CLAUDE.md line"),
        ("2", "EXAMPLE", "a test that fails", "if it comes back"),
        ("3", "GUARDRAIL", "the mistake can't", "happen in code"),
        ("4", "MECHANISM", "the system itself", "works differently"),
        ("5", "STANDARD", "every system follows", "the same rule"),
    ]
    x0, col = 56, 220
    base = 322
    parts = [
        t(56, 62, "ANDON", 13, DIM, weight=500, spacing=2),
        t(150, 63, "A COMPLAINT THAT COMES BACK GOES ONE LEVEL UP.", 20, INK, weight=500, spacing=1.5),
        f'<line x1="0" y1="96" x2="{W}" y2="96" stroke="{RULE}"/>',
    ]
    block = 18
    for i, (n, name, a, b) in enumerate(levels):
        x = x0 + i * col
        cols = i + 1
        color = AMBER if i < 2 else GREEN
        # a staircase of pixel blocks: level i has i+1 rows
        for r in range(cols):
            for c in range(6):
                bx = x + c * (block + 4)
                by = base - (r + 1) * (block + 4)
                op = 1.0 if r == cols - 1 else 0.38
                parts.append(f'<rect x="{bx}" y="{by}" width="{block}" height="{block}" fill="{color}" opacity="{op}"/>')
        parts.append(t(x, base + 40, f"{n}  {name}", 17, INK, weight=500, spacing=1))
        parts.append(t(x, base + 68, a, 16, MUTED))
        parts.append(t(x, base + 92, b, 16, MUTED))
    # brackets: words vs code
    def bracket(xa, xb, y, label, color):
        return (f'<path d="M{xa} {y + 8} V{y} H{xb} V{y + 8}" fill="none" stroke="{color}" stroke-width="1.5"/>' +
                t((xa + xb) / 2, y - 12, label, 14, color, weight=500, spacing=2, anchor="middle"))
    parts.append(bracket(x0, x0 + col + 128, 150, "WORDS: A MODEL CAN IGNORE THEM", AMBER))
    parts.append(bracket(x0 + 2 * col, x0 + 4 * col + 128, 150 - 0, "CODE: IT CANNOT", GREEN))
    parts.append(f'<line x1="0" y1="{H - 1}" x2="{W}" y2="{H - 1}" stroke="{RULE}"/>')
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="title desc">
<title id="title">The Andon ladder</title>
<desc id="desc">Five levels of countermeasure, weakest first: 1 instruction (a prompt, a skill, a CLAUDE.md line), 2 example (a test that fails if it comes back), 3 guardrail (the mistake can't happen in code), 4 mechanism (the system itself works differently), 5 standard (every system follows the same rule). Levels 1 and 2 are words a model can ignore; 3 to 5 are code. A complaint that comes back has to go one level up.</desc>
<defs><style>{FONTS}</style></defs>
<rect width="{W}" height="{H}" fill="{BG}"/>
<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" fill="none" stroke="{RULE}"/>
{chr(10).join(parts)}
</svg>
"""
    (OUT / "ladder.svg").write_text(svg)


# ---------------------------------------------------------------- receipt

def receipt():
    W = 560
    paper, ink, faint = "#f4f2ea", "#1a1a18", "#8b897f"
    size = 16
    cw = size * 0.6
    cols = 44
    x = 40
    rows = []

    def line(left="", right="", color=ink, weight=400, center=False):
        rows.append((left, right, color, weight, center))

    def dashes():
        rows.append(("-" * cols, "", faint, 400, False))

    line("DONE-MEANS-SEEN", "", ink, 500, True)
    line("RECEIPT  OCT 21 - NOV 23, 2026", "", faint, 400, True)
    line("")
    dashes()
    line("STOP HOOK", "", faint)
    line("SESSIONS THROUGH THE HOOK", "171")
    line("CHECKS GREEN AT END OF TURN", "386")
    line("RED WHEN CLAUDE TRIED TO STOP", "16")
    line("SENT BACK TO WORK", "8")
    line("COULD NOT JUDGE, LET THROUGH", "198")
    dashes()
    line("ANDON", "", faint)
    line("COMPLAINTS LOGGED", "71")
    line("FIXES THAT ARE JUST A PROMPT", "0")
    line("CAME BACK, FORCED UP A LEVEL", "8")
    line("COMPLAINTS ABOUT CLAUDE ITSELF", "7")
    dashes()
    line("")
    line("SILENCE IS NOT PROOF", "", ink, 500, True)
    line("THANK YOU FOR NOT BABYSITTING", "", faint, 400, True)

    lh = 27
    top = 54
    H = top + len(rows) * lh + 40
    parts = []
    for i, (left, right, color, weight, center) in enumerate(rows):
        y = top + i * lh
        if center:
            parts.append(t(W / 2, y, left, size, color, weight=weight, anchor="middle", spacing=1))
            continue
        if right:
            dots = cols - len(left) - len(right) - 2
            parts.append(t(x, y, left, size, color, weight=weight))
            parts.append(t(x + (len(left) + 1) * cw, y, "." * max(dots, 1), size, faint))
            parts.append(t(x + cols * cw, y, right, size, ink, weight=500, anchor="end"))
        else:
            parts.append(t(x, y, left, size, color, weight=weight))
    # torn bottom edge
    teeth = []
    step = 14
    for k in range(int(W / step) + 1):
        xk = k * step
        teeth.append(f"L{xk} {H - (10 if k % 2 else 0)}")
    torn = f'<path d="M0 0 H{W} V{H} ' + " ".join(reversed(teeth)) + ' Z" fill="' + paper + '"/>'
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="-20 -20 {W + 40} {H + 40}" width="{W + 40}" height="{H + 40}" role="img" aria-labelledby="title desc">
<title id="title">Receipt, first 33 days</title>
<desc id="desc">Receipt from Oct 21 to Nov 23, 2026. Stop hook: 171 sessions through the hook, 386 checks green at end of turn, 16 red when Claude tried to stop, 8 sent back to work, 198 could not judge and let through. Andon: 71 complaints logged, 0 fixes that are just a prompt, 8 came back and were forced up a level, hold rate: first checks due. Silence is not proof.</desc>
<defs><style>{FONTS}</style>
<filter id="shadow" x="-10%" y="-10%" width="120%" height="120%"><feDropShadow dx="0" dy="6" stdDeviation="8" flood-color="#000" flood-opacity="0.18"/></filter></defs>
<g filter="url(#shadow)">{torn}</g>
{chr(10).join(parts)}
</svg>
"""
    (OUT / "receipt.svg").write_text(svg)


# ---------------------------------------------------------------- social preview (1280 x 640, rendered to PNG)

def social():
    W, H = 1280, 640
    parts = [
        lamp(80, 96, 2.2, lit="green"),
        t(80, 380, "DONE-MEANS-SEEN", 64, INK, weight=500, spacing=5),
        t(80, 450, "Claude doesn't get to say “done”", 34, MUTED),
        t(80, 498, "until it has seen the thing work.", 34, MUTED),
        f'<line x1="0" y1="560" x2="{W}" y2="560" stroke="{RULE}"/>',
        t(80, 606, "A STOP HOOK + ANDON FOR CLAUDE CODE", 18, DIM, weight=500, spacing=2),
        t(W - 80, 606, "github.com/VicKayro/done-means-seen", 18, DIM, anchor="end"),
        # a few terminal lines on the right
        f'<rect x="640" y="80" width="560" height="220" fill="{PANEL}" stroke="{RULE}"/>',
        t(668, 124, "claude", 18, MUTED), t(752, 124, ">", 18, AMBER, weight=500), t(776, 124, "Done!", 18, INK),
        t(668, 164, "hook", 18, DIM), f'<rect x="752" y="151" width="12" height="12" fill="{RED}"/>', t(776, 164, "ERROR: the check fails", 18, RED, weight=500),
        t(668, 204, "hook", 18, DIM), f'<rect x="752" y="191" width="12" height="12" fill="{GREEN}"/>', t(776, 204, "green", 18, GREEN, weight=500),
        t(668, 244, "claude", 18, MUTED), t(752, 244, ">", 18, AMBER, weight=500), t(776, 244, "Done, and seen.", 18, INK),
    ]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
<defs><style>{FONTS}</style>{GLOW}</defs>
<rect width="{W}" height="{H}" fill="{BG}"/>
{chr(10).join(parts)}
</svg>
"""
    (OUT / "social.svg").write_text(svg)


hero()
ladder()
receipt()
social()
print("ok", sorted(p.name for p in OUT.iterdir()))
