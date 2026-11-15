# -*- coding: utf-8 -*-
"""Test del modulo brand: palette ufficiale, font inclusi, risorse presenti."""

import os

import brand

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_official_palette_values():
    """I quattro colori devono essere quelli del brand book, non approssimazioni."""
    assert brand.NAVY == "#11255C"
    assert brand.VIOLET == "#5B2581"
    assert brand.GOLD == "#FDEB19"
    assert brand.ICE.lower() == "#d8eefc"


def test_palette_ramps_match_brand_book():
    assert brand.NAVY_RAMP[0].upper() == "#163079"
    assert brand.NAVY_RAMP[-1].upper() == "#234CBE"
    assert brand.VIOLET_RAMP[0].upper() == "#66298E"
    assert brand.VIOLET_RAMP[-1].upper() == "#9241C8"


def test_derived_shades_are_hex():
    for token in (brand.BORDER, brand.BORDER_SOFT, brand.TEXT_MUTED, brand.TEXT_FAINT,
                  brand.INPUT_BG, brand.VIOLET_SOFT, brand.NAVY_DEEP, brand.NAVY_PANEL):
        assert token.startswith("#") and len(token) == 7, token


def test_brand_assets_are_present():
    for name in ("uc-monogram-white.png", "uc-monogram-navy.png",
                 "wordmark-white.png", "FS-MetaPostDiag.png", "FS-MetaPostDiag.ico"):
        path = brand.asset_path(name)
        assert path and os.path.isfile(path), name


def test_bundled_fonts_and_license():
    """Roboto e' SIL OFL: va incluso con la sua licenza."""
    folder = brand.fonts_dir()
    assert folder and os.path.isdir(folder)
    ttfs = [name for name in os.listdir(folder) if name.lower().endswith(".ttf")]
    assert len(ttfs) >= 5, ttfs
    assert any("roboto" in name.lower() for name in ttfs)
    assert os.path.isfile(os.path.join(folder, "OFL.txt"))


def test_families_are_consistent():
    families = brand.families()
    assert set(families) == {"ui", "num", "display"}
    for value in families.values():
        assert isinstance(value, str) and value
    # la registrazione dei font e' idempotente
    assert brand.register_fonts() == brand.register_fonts()
