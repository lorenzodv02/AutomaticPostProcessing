# -*- coding: utf-8 -*-
"""
===============================================================================
Brand identity UniNa Corse (brand.py)
===============================================================================
Fonte: cartella `BRAND IDENTITY` del team.

Palette ufficiale (PALETTE COLORI):
    PRIMARY    #11255C   navy       (C100 M81 Y0 K50)
    SECONDARY  #5B2581   viola      (C80 M100 Y2 K1)
    DETAILS    #FDEB19   giallo     (C4 M0 Y89 K0)
    DETAILS    #D8EEFC   azzurro    (C18 M0 Y0 K0)

Tipografia: **Roboto** (licenza SIL OFL, inclusa in `assets/fonts`).
Il font display "Ethnocentric" NON viene incluso: la licenza Typodermic e' una
*Desktop EULA* (installazione sulla propria postazione) e non consente la
ridistribuzione del software font dentro un'applicazione. Se e' installato sul
sistema, Tk lo usa solo se richiesto esplicitamente; qui non lo chiediamo.

I font inclusi vengono registrati come privati del processo
(`AddFontResourceExW` con `FR_PRIVATE`): nessuna installazione di sistema,
nessun residuo su Windows, e nell'exe funzionano da `sys._MEIPASS`.
===============================================================================
"""

import ctypes
import os
import sys

from config_bridge import app_dir, bundled_dir

__all__ = [
    # palette
    "NAVY", "NAVY_DEEP", "NAVY_PANEL", "NAVY_RAMP",
    "VIOLET", "VIOLET_RAMP", "VIOLET_SOFT",
    "GOLD", "GOLD_DEEP", "ICE", "WHITE", "DANGER",
    # derivati UI
    "BORDER", "BORDER_SOFT", "TEXT_MUTED", "TEXT_FAINT", "INPUT_BG",
    # servizi
    "asset_path", "fonts_dir", "register_fonts", "families",
]

# ------------------------------------------------------------------------------
# Palette ufficiale
# ------------------------------------------------------------------------------
NAVY = "#11255C"
VIOLET = "#5B2581"
GOLD = "#FDEB19"
ICE = "#D8EEFC"

# Rampa "FIRST COLOR: SHADES" e "SECOND COLOR: SHADES" del brand book
NAVY_RAMP = ("#163079", "#19378A", "#1C3E9B", "#2045AC", "#234CBE")
VIOLET_RAMP = ("#66298E", "#712E9E", "#7D32AE", "#8837BE", "#9241C8")

# ------------------------------------------------------------------------------
# Derivati (sfumature ottenute mescolando i colori di brand, documentate)
# ------------------------------------------------------------------------------
NAVY_DEEP = "#0B1B47"     # navy scurito per il fondo applicazione
NAVY_PANEL = NAVY_RAMP[0]  # #163079: superfici secondarie
GOLD_DEEP = "#F0DC00"     # giallo leggermente piu' carico per i gradienti
WHITE = "#FFFFFF"
DANGER = "#E42320"        # rosso presente nel brand book (pagina FONT)

BORDER = "#394D7C"        # mix(ICE, NAVY, 0.80)
BORDER_SOFT = "#293D6F"   # mix(ICE, NAVY, 0.88)
TEXT_MUTED = "#7E94B4"    # mix(ICE, NAVY, 0.45)
TEXT_FAINT = "#5D7199"    # mix(ICE, NAVY, 0.62)
INPUT_BG = "#0E2050"      # mix(NAVY_DEEP, NAVY, 0.45)
VIOLET_SOFT = "#A094C5"   # mix(ICE, VIOLET, 0.45)

# ------------------------------------------------------------------------------
# Risorse
# ------------------------------------------------------------------------------
_FR_PRIVATE = 0x10
_registered = None


def asset_path(name: str, subfolder: str = "") -> str:
    """
    Percorso di una risorsa in `assets/` (o `assets/<subfolder>/`).

    Cerca prima nel bundle PyInstaller (`sys._MEIPASS`) e poi accanto
    all'eseguibile / ai sorgenti; restituisce "" se non la trova.
    """
    relative = os.path.join("assets", subfolder, name) if subfolder else os.path.join("assets", name)
    for base in (bundled_dir(), app_dir()):
        candidate = os.path.join(base, relative)
        if os.path.isfile(candidate):
            return candidate
    return ""


def fonts_dir() -> str:
    """Cartella dei font inclusi ("" se assente)."""
    for base in (bundled_dir(), app_dir()):
        candidate = os.path.join(base, "assets", "fonts")
        if os.path.isdir(candidate):
            return candidate
    return ""


def register_fonts() -> int:
    """
    Registra i font di `assets/fonts` come privati del processo (solo Windows).

    Restituisce il numero di file registrati (0 su altre piattaforme o se la
    cartella non esiste). Idempotente: la registrazione avviene una sola volta.
    """
    global _registered
    if _registered is not None:
        return _registered

    count = 0
    folder = fonts_dir()
    if folder and sys.platform.startswith("win"):
        try:
            gdi32 = ctypes.windll.gdi32
        except Exception:
            gdi32 = None
        if gdi32 is not None:
            for entry in sorted(os.listdir(folder)):
                if not entry.lower().endswith((".ttf", ".otf")):
                    continue
                try:
                    if gdi32.AddFontResourceExW(os.path.join(folder, entry), _FR_PRIVATE, 0):
                        count += 1
                except Exception:
                    continue

    _registered = count
    return count


def families() -> dict:
    """
    Famiglie tipografiche da usare nell'interfaccia.

    Se i font inclusi sono stati registrati si usa **Roboto** (con la variante
    Condensed per i numeri e il log); altrimenti si ricade sui font di sistema.
    """
    if register_fonts() > 0:
        return {"ui": "Roboto", "num": "Roboto Condensed", "display": "Roboto"}
    return {"ui": "Segoe UI", "num": "Consolas", "display": "Segoe UI"}
