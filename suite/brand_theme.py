# -*- coding: utf-8 -*-
"""
Brand identity UniNa Corse per i report HTML (autonomo, sola stdlib).

Fonte: `brand.py` dell'applicazione e il brand book del team.
Palette ufficiale: NAVY #11255C, VIOLET #5B2581, GOLD #FDEB19, ICE #D8EEFC.
Tipografia: Roboto / Roboto Condensed (SIL OFL), registrati @font-face quando
i file sono disponibili accanto a questo modulo (`assets/fonts`).
"""
from __future__ import annotations

import base64
import os
from html import escape

NAVY = "#11255C"
VIOLET = "#5B2581"
GOLD = "#FDEB19"
ICE = "#D8EEFC"

NAVY_RAMP = ("#163079", "#19378A", "#1C3E9B", "#2045AC", "#234CBE")
VIOLET_RAMP = ("#66298E", "#712E9E", "#7D32AE", "#8837BE", "#9241C8")

NAVY_DEEP = "#0B1B47"
NAVY_PANEL = "#163079"
GOLD_DEEP = "#F0DC00"
WHITE = "#FFFFFF"
DANGER = "#E42320"

BORDER = "#394D7C"
BORDER_SOFT = "#293D6F"
TEXT_MUTED = "#7E94B4"
TEXT_FAINT = "#5D7199"
INPUT_BG = "#0E2050"
VIOLET_SOFT = "#A094C5"

TEAM = "UniNa Corse"
DEPARTMENT = "Aerodynamics & Cooling"

FONT_FILES = (
    ("Roboto", "Roboto-Regular.ttf", "400"),
    ("Roboto", "Roboto-Medium.ttf", "500"),
    ("Roboto", "Roboto-Bold.ttf", "700"),
    ("Roboto", "Roboto-Black.ttf", "900"),
    ("Roboto Condensed", "Roboto_Condensed-Regular.ttf", "400"),
    ("Roboto Condensed", "Roboto_Condensed-Bold.ttf", "700"),
)


def _assets_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (os.path.join(here, "assets"),
                      os.path.join(os.path.dirname(here), "assets"),
                      os.path.join(here, "..", "..", "assets")):
        if os.path.isdir(candidate):
            return os.path.abspath(candidate)
    return ""


def data_uri(path: str, mime: str) -> str:
    try:
        with open(path, "rb") as handle:
            encoded = base64.b64encode(handle.read()).decode("ascii")
    except OSError:
        return ""
    return "data:%s;base64,%s" % (mime, encoded)


def logo_uri(white: bool = True) -> str:
    name = "uc-monogram-white.png" if white else "uc-monogram-navy.png"
    directory = _assets_dir()
    if not directory:
        return ""
    return data_uri(os.path.join(directory, name), "image/png")


def wordmark_uri() -> str:
    directory = _assets_dir()
    if not directory:
        return ""
    path = os.path.join(directory, "wordmark-white.png")
    return data_uri(path, "image/png")


def font_faces() -> str:
    """Regole @font-face con i font di brand in base64 (se presenti)."""
    directory = _assets_dir()
    if not directory:
        return ""
    fonts_dir = os.path.join(directory, "fonts")
    rules = []
    for family, filename, weight in FONT_FILES:
        path = os.path.join(fonts_dir, filename)
        uri = data_uri(path, "font/ttf")
        if not uri:
            continue
        rules.append(
            "@font-face { font-family: '%s'; font-weight: %s; font-style: normal; "
            "font-display: swap; src: url(%s) format('truetype'); }" % (family, weight, uri)
        )
    return "\n".join(rules)


def css_vars() -> str:
    """Variabili CSS del brand, con i nomi usati dai report."""
    return """  :root {
    --navy: %(navy)s; --navy-deep: %(navy_deep)s; --navy-panel: %(navy_panel)s;
    --violet: %(violet)s; --violet-soft: %(violet_soft)s;
    --gold: %(gold)s; --gold-deep: %(gold_deep)s;
    --ice: %(ice)s; --white: %(white)s; --danger: %(danger)s;
    --border: %(border)s; --border-soft: %(border_soft)s;
    --text: %(ice)s; --muted: %(muted)s; --faint: %(faint)s; --input: %(input)s;
    --font-ui: 'Roboto', 'Segoe UI', system-ui, sans-serif;
    --font-data: 'Roboto Condensed', 'Cascadia Mono', Consolas, monospace;
  }""" % {
        "navy": NAVY, "navy_deep": NAVY_DEEP, "navy_panel": NAVY_PANEL,
        "violet": VIOLET, "violet_soft": VIOLET_SOFT,
        "gold": GOLD, "gold_deep": GOLD_DEEP,
        "ice": ICE, "white": WHITE, "danger": DANGER,
        "border": BORDER, "border_soft": BORDER_SOFT,
        "muted": TEXT_MUTED, "faint": TEXT_FAINT, "input": INPUT_BG,
    }


def header_html(title: str, subtitle: str, chips: list) -> str:
    """Header di brand: monogramma, titolo, striscia a tre accenti, chips."""
    logo = logo_uri()
    logo_html = ('<img class="monogram" src="%s" alt="UC" />' % logo) if logo else ""
    bars = "".join('<i class="bar bar-%d"></i>' % index for index in range(3))
    chip_html = "".join(
        '<span class="chip">%s <b>%s</b></span>' % (label, value) for label, value in chips
    )
    return ('<header class="brand-head">'
            '<div class="brand-row">%s<div><div class="kicker">%s · %s</div>'
            '<h1>%s</h1><p class="sub">%s</p></div>'
            '<div class="stripe">%s</div></div>'
            '<div class="chips">%s</div>'
            '</header>') % (logo_html, escape(TEAM), escape(DEPARTMENT), title, subtitle,
                            bars, chip_html)


def footer_html(generated: str) -> str:
    mark = wordmark_uri()
    mark_html = ('<img class="wordmark" src="%s" alt="UniNa Corse" />' % mark) if mark else ""
    return ('<footer class="brand-foot">%s<span class="foot-brand">%s · %s</span>'
            '<span>Generato il %s · dati reali .cas/.dat elaborati da FS-MetaPostDiag</span>'
            '</footer>') % (mark_html, escape(TEAM), escape(DEPARTMENT), generated)
