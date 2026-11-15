# -*- coding: utf-8 -*-
"""
Assiemi aerodinamici: scelte, etichette e regola di risoluzione.

Nel programma originale l'assieme si sceglieva dalla GUI e la pipeline poteva
anche **rilevarlo** dal `.cas` (`detected_assembly`). Il default "undertray" del
config non e' una buona scelta per la suite: qui il default e' `auto`.

Priorita' (dalla piu' forte):
    1. override esplicito (scelta del launcher o `--assembly` da riga di comando)
    2. assieme scritto nella riga del dataset (colonna `assieme`)
    3. `auto` (rileva dalle zone del .cas)
"""
from __future__ import annotations

VALID_ASSEMBLIES = ("auto", "undertray", "front_wing", "rear_wing", "full_car")

ASSEMBLY_CHOICES = [
    ("auto", "Rileva dall'analisi (auto)"),
    ("undertray", "Undertray · Fondo & Diffusore"),
    ("front_wing", "Ala anteriore"),
    ("rear_wing", "Ala posteriore"),
    ("full_car", "Vettura completa"),
]

ASSEMBLY_LABELS = {value: label for value, label in ASSEMBLY_CHOICES}
LABEL_TO_ASSEMBLY = {label: value for value, label in ASSEMBLY_CHOICES}
# "Dall'analisi" per la suite: nessun override, decide la riga del dataset
CASE_DEFAULT_LABEL = "Dall'analisi (per caso)"


def normalize_assembly(value) -> str:
    """Riporta un valore all'assieme valido, o stringa vuota se non lo e'."""
    clean = str(value or "").strip().lower().replace(" ", "_")
    aliases = {
        "front": "front_wing", "ala_anteriore": "front_wing", "frontwing": "front_wing",
        "rear": "rear_wing", "ala_posteriore": "rear_wing", "rearwing": "rear_wing",
        "full": "full_car", "fullcar": "full_car", "vettura_completa": "full_car",
        "fondo": "undertray", "diffusore": "undertray", "underbody": "undertray",
        "auto_detect": "auto", "rileva": "auto", "": "",
    }
    if clean in VALID_ASSEMBLIES:
        return clean
    return aliases.get(clean, "")


def resolve_assembly(override=None, case_assembly=None, config_assembly=None) -> str:
    """
    Sceglie l'assieme con la priorita' documentata.

    Un override esplicito (anche "auto") vince; altrimenti la riga del dataset;
    altrimenti il config; in mancanza di tutto, "auto".
    """
    explicit = normalize_assembly(override)
    if explicit:
        return explicit
    from_case = normalize_assembly(case_assembly)
    if from_case:
        return from_case
    from_config = normalize_assembly(config_assembly)
    return from_config or "auto"


def is_specific(value) -> bool:
    """Vero se e' un assieme preciso (non auto e non vuoto)."""
    clean = normalize_assembly(value)
    return bool(clean) and clean != "auto"
