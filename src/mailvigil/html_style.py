"""
The look of the HTML report: the palette as data and the stylesheet built from it (spec 008).

The colours come from the mockup the maintainer approved (WebVigil's slate palette). They are kept
as two dicts, light and dark, so the stylesheet states each one once and a test can measure the
contrast of every pair that matters (4.5:1 for text, 3:1 for a graphic that carries meaning,
RF-07) instead of trusting the eye. The dark palette applies by ``prefers-color-scheme`` alone,
with no script; printing always uses the light one, so a dark system does not print a black page.

The rest of the CSS is a constant string. It has no ``url()``, no ``@import`` and no ``<``: the
page loads nothing (ADR-8) and the text cannot close its own ``style`` element. The hatched
segment of the charts is a ``fill="url(#hatch)"`` attribute set by the chart, not a rule here.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------

#: The content security policy of the page (ADR-8). Nothing may load: there is no ``img-src``
#: because the page has no image, and ``'unsafe-inline'`` is for ``style`` only (the stylesheet and
#: the per-meter widths).
CONTENT_SECURITY_POLICY: Final = (
    "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
)

# ---------------------------------------------------------------------------
# The palette
# ---------------------------------------------------------------------------

#: The light palette. ``page`` and ``card`` are the two surfaces; ``ok``, ``warn`` and ``bad`` are
#: the three answers, each with a ``-bg`` tint; ``seg-*`` are the four situations of a message.
LIGHT: Final = {
    "page": "#f1f5f9",
    "card": "#ffffff",
    "fg": "#0f172a",
    "muted": "#475569",
    "line": "#e2e8f0",
    "subtle": "#f1f5f9",
    "ok": "#047857",
    "ok-bg": "#ecfdf5",
    "bad": "#b91c1c",
    "bad-bg": "#fef2f2",
    "bad-line": "#fca5a5",
    "warn": "#92400e",
    "warn-bg": "#fffbeb",
    "accent": "#1d4ed8",
    "track": "#e2e8f0",
    "seg-ok": "#059669",
    "seg-dkim": "#2563eb",
    "seg-spf": "#d97706",
    "seg-bad": "#b91c1c",
    "grid": "#cbd5e1",
}

#: The dark palette, with the same keys as ``LIGHT``.
DARK: Final = {
    "page": "#0b1120",
    "card": "#111a2e",
    "fg": "#e2e8f0",
    "muted": "#a3b1c6",
    "line": "#243049",
    "subtle": "#172036",
    "ok": "#34d399",
    "ok-bg": "#0d2a22",
    "bad": "#fca5a5",
    "bad-bg": "#2a1418",
    "bad-line": "#7f1d1d",
    "warn": "#fbbf24",
    "warn-bg": "#2a2010",
    "accent": "#93c5fd",
    "track": "#243049",
    "seg-ok": "#34d399",
    "seg-dkim": "#60a5fa",
    "seg-spf": "#fbbf24",
    "seg-bad": "#f87171",
    "grid": "#334155",
}

#: Text over a background, as (foreground, background) token names: each must reach 4.5:1 in both
#: palettes.
TEXT_PAIRS: Final = (
    ("fg", "page"),
    ("fg", "card"),
    ("fg", "subtle"),
    ("fg", "bad-bg"),
    ("fg", "ok-bg"),
    ("fg", "warn-bg"),
    ("muted", "page"),
    ("muted", "card"),
    ("muted", "subtle"),
    ("muted", "bad-bg"),
    ("muted", "ok-bg"),
    ("muted", "warn-bg"),
    ("ok", "card"),
    ("ok", "ok-bg"),
    ("bad", "card"),
    ("bad", "bad-bg"),
    ("warn", "card"),
    ("warn", "warn-bg"),
    ("accent", "card"),
)

#: Graphics that carry meaning, as (graphic, surface) token names: each must reach 3:1 in both
#: palettes. The limit tick and the failing marker are the two the reader cannot do without.
GRAPHIC_PAIRS: Final = (
    ("seg-ok", "card"),
    ("seg-dkim", "card"),
    ("seg-spf", "card"),
    ("seg-bad", "card"),
    ("fg", "card"),
    ("fg", "track"),
    ("fg", "bad-bg"),
    ("ok", "track"),
    ("bad", "track"),
    ("bad", "card"),
    ("muted", "card"),
    ("card", "ok"),
    ("card", "bad"),
    ("card", "warn"),
)

#: Tokens that are never the only thing telling two things apart (a hairline, a grid line, the
#: outline of a failing card), so they are not measured.
DECORATIVE: Final = ("line", "bad-line", "grid")

# ---------------------------------------------------------------------------
# The stylesheet
# ---------------------------------------------------------------------------

# Only the rules of the layouts the maintainer approved: the verdict banner, the meters of board B,
# the stacked bar of board C and the columns of timeline T1. Colours are always ``var(--token)``.
_RULES: Final = """
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--fg);font:15px/1.5 system-ui,"Segoe UI",Roboto,sans-serif}
.page{max-width:1040px;margin:0 auto;padding:24px 16px 56px;display:flex;flex-direction:column;gap:16px}
main{display:flex;flex-direction:column;gap:16px}
.top{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px 24px}
.brand{display:flex;align-items:center;gap:8px;font-weight:700;font-size:17px}
.meta{margin:0;color:var(--muted);font-size:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:20px;min-width:0}
h1,h2,h3,p{margin:0}
h2{font-size:17px;margin-bottom:12px}
.sub{color:var(--muted);font-size:14px;margin:0 0 12px}
.note{color:var(--muted);font-size:14px;margin-top:10px}
.verdict{display:flex;flex-wrap:wrap;gap:16px 24px;align-items:flex-start;background:var(--bad-bg);border:1px solid var(--bad-line);border-radius:8px;padding:24px;color:var(--fg)}
.verdict.ready{background:var(--ok-bg);border-color:var(--ok)}
.verdict.early{background:var(--warn-bg);border-color:var(--warn)}
.vmark{flex:none;width:48px;height:48px;border-radius:999px;background:var(--bad);color:var(--card);display:flex;align-items:center;justify-content:center}
.ready .vmark{background:var(--ok)}
.early .vmark{background:var(--warn)}
.vbody{flex:1 1 320px;min-width:0;display:flex;flex-direction:column;gap:6px}
.eyebrow{font-size:13px;font-weight:700;color:var(--muted)}
.verdict h1{font-size:34px;line-height:1.15;color:var(--bad)}
.ready h1{color:var(--ok)}
.early h1{color:var(--warn)}
.why{font-size:16px}
.why::first-letter{text-transform:uppercase}
.next{font-size:15px;color:var(--muted)}
.policy{flex:none;margin:0;display:flex;gap:16px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px}
.policy div{display:flex;flex-direction:column}
.policy dt{font-size:12px;color:var(--muted)}
.policy dd{margin:0;font-weight:700;font-variant-numeric:tabular-nums}
.grp{font-size:13px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin:20px 0 8px}
.grp:first-of-type{margin-top:0}
.meters{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.meter{border:1px solid var(--line);border-radius:8px;padding:12px 14px;display:flex;flex-direction:column;gap:8px}
.meter.fail{background:var(--bad-bg);border-color:var(--bad-line)}
.mhead{display:flex;align-items:center;justify-content:space-between;gap:8px}
.rname{font-weight:600}
.rstate{display:inline-flex;align-items:center;gap:4px;font-weight:700;font-size:13px;letter-spacing:.04em;text-transform:uppercase;color:var(--ok)}
.fail .rstate{color:var(--bad)}
.track{position:relative;height:12px;border-radius:999px;background:var(--track)}
.fill{height:100%;border-radius:999px;background:var(--ok)}
.fail .fill{background:var(--bad)}
.tick{position:absolute;top:-4px;bottom:-4px;width:3px;margin-left:-1px;border-radius:2px;background:var(--fg)}
.mfoot{display:flex;flex-wrap:wrap;justify-content:space-between;gap:2px 12px;font-size:14px;color:var(--muted)}
.mfoot strong{color:var(--fg);font-variant-numeric:tabular-nums}
.tickkey{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--muted);margin-top:12px}
.tickkey i{display:inline-block;width:3px;height:14px;border-radius:2px;background:var(--fg)}
.stack{display:flex;height:16px;border-radius:999px;overflow:hidden;background:var(--line);gap:2px}
.stack i{display:block;height:100%}
.legend{list-style:none;margin:12px 0;padding:0;display:flex;flex-wrap:wrap;gap:6px 20px;font-size:14px;color:var(--muted)}
.legend li{display:flex;align-items:center;gap:6px}
.legend b{display:inline-block;width:12px;height:12px;border-radius:3px;flex:none}
.legend strong{color:var(--fg);font-variant-numeric:tabular-nums}
.seg-ok{background:var(--seg-ok)}
.seg-dkim{background:var(--seg-dkim)}
.seg-spf{background:repeating-linear-gradient(45deg,var(--seg-spf) 0 3px,var(--card) 3px 5px)}
.seg-bad{background:var(--seg-bad)}
.cok{background:var(--ok-bg);border:1px solid var(--ok)}
.ghostsw{background:var(--subtle);border:1px dashed var(--muted)}
.covsw{background:var(--muted);height:4px !important;margin-top:6px}
.chart{display:flex;flex-direction:column;gap:2px}
.flags{display:flex;height:14px;align-items:flex-end}
.fl{flex:1 1 0;min-width:0;display:flex;justify-content:center;align-items:flex-end;line-height:0}
.plot{display:block;width:100%;height:150px}
.plot rect{stroke:var(--card);stroke-width:1;vector-effect:non-scaling-stroke}
.plot .seg-ok{fill:var(--seg-ok)}
.plot .seg-dkim{fill:var(--seg-dkim)}
.plot .seg-bad{fill:var(--seg-bad)}
.grid{stroke:var(--grid);stroke-width:1;stroke-dasharray:3 3;vector-effect:non-scaling-stroke}
.ghost{fill:var(--subtle);stroke:var(--muted) !important;stroke-dasharray:3 3}
.cov{fill:var(--muted)}
.bang{fill:var(--bad)}
.hatch-bg{fill:var(--seg-spf)}
.hatch-ln{stroke:var(--card);stroke-width:1.5}
.xl{display:flex;justify-content:space-between;gap:8px;font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums;margin-top:4px}
details.nums{margin-top:12px}
details.nums summary{cursor:pointer;font-weight:600;font-size:14px;color:var(--accent);padding:6px 0}
details.nums summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:8px}
.scroll:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.nums .scroll{max-height:320px;overflow-y:auto;margin-top:6px}
table{border-collapse:collapse;width:100%;min-width:560px;font-size:14px}
.nums table{min-width:480px}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line)}
.nums th,.nums td{padding:8px 12px}
thead th{font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);background:var(--subtle)}
.nums thead th{position:sticky;top:0}
tbody th{font-weight:600}
tfoot th,tfoot td{font-weight:700;border-bottom:0;background:var(--subtle)}
.n{text-align:right;font-variant-numeric:tabular-nums}
code{font:13px ui-monospace,SFMono-Regular,Consolas,monospace}
.chip{display:inline-block;margin-left:6px;padding:1px 8px;border-radius:999px;border:1px solid var(--line);font-size:12px;font-weight:600;color:var(--muted);white-space:nowrap}
.chip.bad{color:var(--bad);border-color:var(--bad-line);background:var(--bad-bg)}
.cols{display:flex;flex-wrap:wrap;gap:16px}
.cols>.card,.cols>.stackcol{flex:1 1 380px;min-width:0}
.stackcol{display:flex;flex-direction:column;gap:16px}
.fails{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px}
.fails li{border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.fhead{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px}
.fcount{margin-left:auto;font-weight:700;font-variant-numeric:tabular-nums}
.fwhy{color:var(--muted);font-size:14px;margin-top:4px}
.notes{margin:0;padding-left:20px;display:flex;flex-direction:column;gap:6px}
.quiet{background:transparent}
.quiet p{color:var(--muted);font-size:14px}
footer{color:var(--muted);font-size:13px;text-align:center;padding-top:8px}
"""  # noqa: E501  (one rule per line, as in the approved mockup)

# On paper the light palette wins even when the system is dark, the fills keep their colour, and a
# card is never split between two pages.
_PRINT: Final = """
.page{max-width:none;padding:0}
.card,.verdict,.meter,.fails li{break-inside:avoid}
.scroll,.nums .scroll{overflow:visible;max-height:none}
table,.nums table{min-width:0}
* {print-color-adjust:exact;-webkit-print-color-adjust:exact}
"""


def _tokens(palette: dict[str, str]) -> str:
    return ";".join(f"--{name}:{color}" for name, color in palette.items())


def build_stylesheet() -> str:
    """
    Build the whole stylesheet from the two palettes and the constant rules.

    The light tokens sit on ``:root``, the dark ones replace them under
    ``prefers-color-scheme: dark``, and the print block puts the light ones back.

    Returns:
        str: The CSS text, ASCII, with no ``url()``, no ``@import`` and no ``<``.
    """
    return (
        f":root{{color-scheme:light dark;{_tokens(LIGHT)}}}\n"
        f"@media (prefers-color-scheme:dark){{:root{{{_tokens(DARK)}}}}}\n"
        f"{_RULES.strip()}\n"
        f"@media print{{:root{{{_tokens(LIGHT)}}}\n{_PRINT.strip()}}}\n"
    )


#: The stylesheet of the page, built once.
STYLESHEET: Final = build_stylesheet()
