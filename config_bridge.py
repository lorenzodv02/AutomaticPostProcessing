# -*- coding: utf-8 -*-
"""
===============================================================================
Ponte di configurazione unico (config_bridge.py)
===============================================================================
Motivo: prima di questo modulo molte chiavi di `config.yaml` (keyword dei PID,
stazioni di taglio, soglie, cp_range, reference_area) NON erano lette da nessun
file Python: il file sembrava il pannello di controllo del software ma modificarlo
non aveva alcun effetto.

Qui vive l'unica sorgente di verità per:
  * i valori di default (allineati a `config.yaml`, non più divergenti);
  * la risoluzione del profilo di un assieme (keyword, stazioni, soglie, cp_range);
  * la sanitizzazione dei valori numerici (stazioni fuori da (0, 1] scartate).

Regola di compatibilità: se una chiave manca dal file di configurazione, si usano
i fallback storici di `fluent_parser.ASSEMBLY_RULES_KEYWORDS` e le stazioni
canoniche, così una run senza `config.yaml` si comporta come prima.
===============================================================================
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Iterable, List, Sequence, Tuple

__all__ = [
    "DEFAULT_CONFIG",
    "DEFAULT_THRESHOLDS",
    "DEFAULT_X_STATIONS",
    "DEFAULT_Z_STATIONS",
    "DEFAULT_CP_RANGE",
    "ASSEMBLY_KEYWORDS_FALLBACK",
    "merge_config",
    "assembly_profile",
    "assembly_keywords",
    "cut_stations",
    "thresholds",
    "cp_range",
    "reference_values",
]


# ------------------------------------------------------------------------------
# Default allineati a config.yaml (prima erano diversi: 16.67 m/s e area 1.0)
# ------------------------------------------------------------------------------
DEFAULT_CONFIG: Dict[str, Any] = {
    "project": {
        "name": "Formula Student CFD Aero Diagnostics",
        "workspace_dir": ".",
        "output_dir": "./output_diagnostics",
        "assembly_type": "undertray",
    },
    "coordinate_system": {
        "longitudinal_axis": "X",
        "vertical_axis": "Y",
        "lateral_axis": "Z",
        "ground_level_y": 0.0,
        "auto_ground": True,
    },
    "reference_values": {
        "velocity_inf": 14.0,
        "density_air": 1.225,
        "pressure_inf": 0.0,
        "viscosity_mu": 1.7894e-5,
        "reference_area": 1.08,
        "wheelbase": 1.535,
    },
    "meta": {
        "executable_path": "auto",
        "batch_mode": True,
        "image_width": 1920,
        "image_height": 1080,
        "background_color": "white",
    },
    "fluent_variables": {},
    "assemblies": {},
    "ai_vision": {
        "enabled": True,
        "provider": "gemini",
        "model_gemini": "gemini-3.8-flash",
        "model_openai": "gpt-4o",
        "api_key": "",
        "language": "it",
    },
}

# Soglie di fallback (equivalenti al profilo undertray di config.yaml)
DEFAULT_THRESHOLDS: Dict[str, float] = {
    "max_acceptable_stall_pct": 8.0,
    "critical_stall_pct": 18.0,
    "min_suction_cp_warning": -3.2,
    "max_asymmetry_pct": 4.5,
    "vortex_core_loss_threshold": 0.35,
}

# Griglia canonica dei KPI lungo X (10 stazioni) e stazioni di taglio Z di default.
DEFAULT_X_STATIONS: List[float] = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.98]
DEFAULT_Z_STATIONS: List[float] = [0.02, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.82, 0.94]

# Intervallo di visualizzazione del Cp di fallback (identico al renderer storico).
DEFAULT_CP_RANGE: Tuple[float, float] = (-3.0, 1.0)

# Keyword di riconoscimento PID: fallback storico, usato quando config.yaml non
# fornisce `pid_keywords` / `exclude_keywords` per l'assieme richiesto.
ASSEMBLY_KEYWORDS_FALLBACK: Dict[str, Dict[str, List[str]]] = {
    "undertray": {
        "include": [
            "undertray", "flat_floor", "floor", "diffusore", "diffuser",
            "venturi", "tray", "strake", "skid", "fondo", "bargeboard", "plank",
        ],
        "exclude": [
            "front_main", "front_first", "front_second", "front_external", "front_internal", "front_midplate",
            "rear_main", "rear_first", "rear_second", "rear_third", "rear_endplate",
            "chassis", "pilota", "main_hoop", "camicie_motore", "lidar", "suspension", "tyre", "tire",
        ],
    },
    "front_wing": {
        "include": [
            "front_main", "front_first", "front_second", "front_third",
            "front_external_endplate", "front_internal_endplate", "front_midplate",
            "front_wing", "frontwing", "fw", "footplate", "nose", "y250",
        ],
        "exclude": [
            "front_suspension", "front_tyre", "front_tire", "interior_front",
            "venturi", "flat_floor", "diffusore", "rear_", "chassis", "pilota",
        ],
    },
    "rear_wing": {
        "include": [
            "rear_main", "rear_first", "rear_second", "rear_third",
            "rear_endplate", "rear_wing", "rearwing", "rw", "beam_wing", "swan", "drs",
        ],
        "exclude": [
            "rear_suspension", "rear_tyre", "rear_tire", "interior_rear",
            "venturi", "flat_floor", "diffusore", "front_", "chassis", "pilota",
        ],
    },
    "full_car": {
        "include": [
            "wall", "venturi", "flat_floor", "diffusore", "diffuser", "undertray", "floor",
            "front_", "rear_", "chassis", "monocoque", "pilota", "driver", "sidepod",
            "suspension", "tyre", "tire", "wheel", "main_hoop", "camicie_motore",
            "lidar", "inverted", "zed",
        ],
        "exclude": [],
    },
}


# ------------------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------------------
def _as_dict(value: Any) -> Dict[str, Any]:
    """Restituisce `value` se è un dizionario, altrimenti un dizionario vuoto."""
    return value if isinstance(value, dict) else {}


def _clean_keyword_list(values: Any) -> List[str]:
    """Normalizza una lista di keyword: stringhe non vuote, minuscole, senza duplicati."""
    if not isinstance(values, (list, tuple, set)):
        return []
    out: List[str] = []
    for item in values:
        if item is None:
            continue
        text = str(item).strip().lower()
        if text and text not in out:
            out.append(text)
    return out


def _dedup_preserving_order(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for item in values:
        if item not in out:
            out.append(item)
    return out


def merge_config(config: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Fonde una configurazione parziale sopra DEFAULT_CONFIG (merge profondo).

    Serve a evitare i buchi: una config senza `reference_values.viscosity_mu`
    riceve il valore di default invece di un KeyError a metà pipeline.
    """
    base = copy.deepcopy(DEFAULT_CONFIG)
    incoming = _as_dict(config)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Merge ricorsivo: i dizionari si fondono, gli scalari/ liste vengono sostituiti."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def assembly_profile(config: Dict[str, Any], assembly_type: str) -> Dict[str, Any]:
    """Restituisce il profilo `assemblies.<assembly_type>` (vuoto se assente)."""
    assemblies = _as_dict(_as_dict(config).get("assemblies"))
    return _as_dict(assemblies.get(str(assembly_type or "").strip().lower()))


def assembly_keywords(config: Dict[str, Any], assembly_type: str) -> Tuple[List[str], List[str]]:
    """
    Keyword (include, exclude) per l'assieme richiesto.

    Politica additiva: si parte dal fallback storico e si AGGIUNGONO le keyword
    del file di configurazione. Così rendere configurabile il filtro non può far
    sparire un PID che prima veniva riconosciuto (rischio reale: il file omette
    sinonimi come "diffusore" o "flat_floor").
    """
    asm = str(assembly_type or "").strip().lower()
    fallback = ASSEMBLY_KEYWORDS_FALLBACK.get(asm, {"include": [], "exclude": []})
    profile = assembly_profile(config, asm)

    include = _dedup_preserving_order(
        _clean_keyword_list(fallback.get("include")) + _clean_keyword_list(profile.get("pid_keywords"))
    )
    exclude = _dedup_preserving_order(
        _clean_keyword_list(fallback.get("exclude")) + _clean_keyword_list(profile.get("exclude_keywords"))
    )
    return include, exclude


def _sanitize_stations(values: Any, fallback: Sequence[float], label: str = "stazione") -> List[float]:
    """
    Valida le stazioni normalizzate: tiene solo i valori numerici in (0, 1],
    ordinati e senza duplicati. Se il risultato è troppo povero, usa il fallback.

    Una stazione > 1 cadrebbe fuori dal bounding box dell'assieme (finestra
    vuota) ed è quindi inutile: viene scartata invece di produrre un'immagine
    vuota che poi il verifier dovrebbe eliminare.
    """
    cleaned: List[float] = []
    if isinstance(values, (list, tuple)):
        for item in values:
            try:
                value = float(item)
            except (TypeError, ValueError):
                continue
            if 0.0 < value <= 1.0 and all(abs(value - seen) > 1e-9 for seen in cleaned):
                cleaned.append(value)
    if len(cleaned) < 2:
        return list(fallback)
    return sorted(cleaned)


def cut_stations(config: Dict[str, Any], assembly_type: str) -> Tuple[List[float], List[float]]:
    """
    Stazioni normalizzate (X, Z) per le sezioni renderizzate di questo assieme.

    Nota di progetto: queste stazioni governano le SEZIONI da disegnare. La
    griglia di campionamento dei KPI lungo X resta canonica a 10 stazioni, così
    i numeri di run diverse restano confrontabili anche se si cambiano i tagli.
    """
    profile = assembly_profile(config, assembly_type)
    x_stations = _sanitize_stations(profile.get("x_cuts_normalized"), DEFAULT_X_STATIONS)
    z_stations = _sanitize_stations(profile.get("z_cuts_normalized"), DEFAULT_Z_STATIONS)
    return x_stations, z_stations


def thresholds(config: Dict[str, Any], assembly_type: str) -> Dict[str, float]:
    """Soglie ingegneristiche dell'assieme, con fallback sui valori undertray."""
    resolved = dict(DEFAULT_THRESHOLDS)
    raw = _as_dict(assembly_profile(config, assembly_type).get("thresholds"))
    for key, default_value in DEFAULT_THRESHOLDS.items():
        if key not in raw:
            continue
        try:
            resolved[key] = float(raw[key])
        except (TypeError, ValueError):
            resolved[key] = default_value
    return resolved


def cp_range(config: Dict[str, Any], assembly_type: str) -> Tuple[float, float]:
    """Intervallo di visualizzazione del Cp: `(vmin, vmax)` dell'assieme."""
    raw = assembly_profile(config, assembly_type).get("cp_range")
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        try:
            vmin, vmax = float(raw[0]), float(raw[1])
        except (TypeError, ValueError):
            return DEFAULT_CP_RANGE
        if vmin < vmax:
            return vmin, vmax
    return DEFAULT_CP_RANGE


def reference_values(config: Dict[str, Any]) -> Dict[str, float]:
    """Grandezze di riferimento numeriche, con default allineati a config.yaml."""
    merged = _deep_merge(DEFAULT_CONFIG["reference_values"], _as_dict(_as_dict(config).get("reference_values")))
    out: Dict[str, float] = {}
    for key, value in merged.items():
        if isinstance(value, (int, float)):
            out[key] = float(value)
    return out
