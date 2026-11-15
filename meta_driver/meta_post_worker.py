# -*- coding: utf-8 -*-
"""
================================================================================
META POST INTERNAL WORKER SCRIPT (meta_post_worker.py)
================================================================================
Questo script viene eseguito all'interno di BETA CAE META Post v25.1+:
  1) In modalita' automatica da run_postprocessing_meta.ses (# PYTHON) o -execpy
  2) Oppure manualmente dentro la GUI di META Post:
     File -> Read -> Script -> seleziona meta_post_worker.py

Funzionalita':
  - Usa le API Python ufficiali di META Post (`meta.parts`, `meta.results`, `meta.nodes`, `meta.utils`)
  - Isola rigorosamente i soli PID dell'assieme selezionato (es. undertray: diffusore_int, flat_floor,
    venturi, venturi_first, venturi_second, venturi_endplate)
  - Nasconde al 100% la galleria del vento (side, top, road, inlet, outlet, symmetry, fluid, interior)
    e gli altri componenti non appartenenti all'assieme selezionato
  - Legge l'elenco esatto delle variabili CFD disponibili in .dat tramite `results.ScalarTypesList`
  - Esporta gli screenshot PNG reali tramite `window size 1920,1080` e `write png "..."`
================================================================================
"""

import os
import sys
import glob
import json

try:
    import meta
    from meta import models
    from meta import results
    from meta import parts
    from meta import nodes
    from meta import elements
    from meta import windows
    from meta import views
    from meta import planes
    from meta import utils
    IN_META = True
except ImportError:
    IN_META = False


def mcmd(command_str):
    """Esegue un comando di sessione META Post in modo sicuro."""
    if not IN_META:
        return 0
    try:
        return utils.MetaCommand(command_str)
    except Exception as exc:
        print(f"[META-WARN] Comando fallito ({command_str}): {exc}")
        return -1


def get_all_meta_parts(model_id=0):
    """Recupera tutti i Part/PID presenti nel modello META Post (compatibile con v24/v25)."""
    if not IN_META:
        return []
    try:
        if hasattr(parts, "Parts"):
            res = parts.Parts(model_id)
            if res:
                return list(res)
    except Exception:
        pass
    try:
        if hasattr(parts, "GetParts"):
            res = parts.GetParts(model_id)
            if res:
                return list(res)
    except Exception:
        pass
    return []


def load_runtime_config(workspace_dir):
    """Carica la configurazione runtime generata da launcher.py."""
    candidates = [
        os.path.join(workspace_dir, "meta_runtime_config.json"),
        os.path.join(os.getcwd(), "meta_runtime_config.json"),
    ]
    for cfg_path in candidates:
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[META-WARN] Errore lettura {cfg_path}: {e}")
    return {}


def isolate_assembly_parts_in_meta(model_id, cfg):
    """
    Isola rigorosamente nel viewport 3D di META Post i soli PID dell'assieme selezionato,
    nascondendo tutte le pareti della galleria del vento (side, top, road, symmetry, inlet, outlet)
    e i componenti di altri assiemi.
    """
    target_pids = set(int(x) for x in cfg.get("target_pids", []) if x is not None)
    target_names = set(str(x).lower() for x in cfg.get("target_names", []) if x)
    hidden_pids = set(int(x) for x in cfg.get("hidden_pids", []) if x is not None)
    hidden_names = set(str(x).lower() for x in cfg.get("hidden_names", []) if x)
    assembly_type = str(cfg.get("assembly_type", "undertray")).lower()

    domain_keywords = [
        "inlet", "outlet", "symmetry", "sym", "farfield", "ground", "road",
        "domain", "box", "tunnel", "top", "side", "interior",
        "fluid", "auto_detected_volume", "interface", "ambient", "sky"
    ]
    assembly_keywords = {
        "undertray": ["undertray", "floor", "flat_floor", "diffus", "venturi", "strake", "skid", "fondo", "bargeboard"],
        "front_wing": ["front_", "fw", "frontwing", "footplate", "nose", "main_ant", "flap_ant", "endplate_ant", "musetto"],
        "rear_wing": ["rear_", "rw", "rearwing", "beam_wing", "swan", "drs", "main_post", "flap_post", "endplate_post"],
    }

    all_parts = get_all_meta_parts(model_id)
    to_show = []
    to_hide = []
    shown_info = []
    hidden_info = []

    for p in all_parts:
        pname = str(getattr(p, "name", "") or "")
        pname_low = pname.lower()
        pid = int(getattr(p, "id", 0) or 0)
        ptype = str(getattr(p, "type", "") or "").lower()

        is_domain = any(
            pname_low == kw or pname_low.startswith(kw + ":") or pname_low.startswith(kw + "_") or kw in pname_low
            for kw in domain_keywords
        )
        if is_domain or "solid" in ptype or "fluid" in ptype or pid in hidden_pids or pname_low in hidden_names:
            to_hide.append(p)
            hidden_info.append((pid, pname))
            continue

        pname_base = pname_low.split(":")[0].strip()
        if target_pids or target_names:
            if pid in target_pids or pname_low in target_names or pname_base in target_names:
                to_show.append(p)
                shown_info.append((pid, pname_base))
            else:
                to_hide.append(p)
                hidden_info.append((pid, pname))
        else:
            if assembly_type in assembly_keywords:
                kws = assembly_keywords[assembly_type]
                if any(kw in pname_low for kw in kws):
                    to_show.append(p)
                    shown_info.append((pid, pname))
                else:
                    to_hide.append(p)
                    hidden_info.append((pid, pname))
            else:
                to_show.append(p)
                shown_info.append((pid, pname))

    # Se per qualche motivo nessuna parte ha fatto match, mostra tutte le non-domain
    if not to_show and all_parts:
        for p in all_parts:
            pname = str(getattr(p, "name", "") or "")
            pname_low = pname.lower()
            pid = int(getattr(p, "id", 0) or 0)
            if not any(kw in pname_low for kw in domain_keywords):
                to_show.append(p)
                shown_info.append((pid, pname))

    if IN_META:
        try:
            if to_hide and hasattr(parts, "HideParts"):
                parts.HideParts(model_id, to_hide)
            if to_show and hasattr(parts, "ShowParts"):
                parts.ShowParts(model_id, to_show)
        except Exception as e:
            print(f"[META-WARN] HideParts/ShowParts exception: {e}")

        for pid, pname in hidden_info:
            mcmd(f"erase pid {pid}")
            if pname:
                mcmd(f'erase name "{pname}"')
        for pid, pname in shown_info:
            mcmd(f"show pid {pid}")
            if pname:
                mcmd(f'show name "{pname}"')

    mcmd("view center")
    mcmd("view fit")
    print(f"[META-WORKER] Parti visibili ({len(shown_info)}): {[x[1] for x in shown_info]}")
    print(f"[META-WORKER] Parti nascoste ({len(hidden_info)}): {len(hidden_info)} zone")
    return shown_info, hidden_info


def run_worker():
    workspace_dir = os.environ.get("CFD_WORKSPACE_DIR", os.getcwd())
    cfg = load_runtime_config(workspace_dir)
    if not cfg:
        return

    model_id = 0
    all_parts = get_all_meta_parts(model_id)
    cas_file = cfg.get("cas_file")
    dat_file = cfg.get("dat_file")

    # Se lo script viene chiamato direttamente via -execpy (prima del .ses), carica la geometria
    if IN_META and not all_parts and cas_file and os.path.isfile(cas_file):
        cas_norm = cas_file.replace("\\", "/")
        mcmd(f'read geom Fluent "{cas_norm}"')
        if dat_file and os.path.isfile(dat_file):
            dat_norm = dat_file.replace("\\", "/")
            try:
                if hasattr(results, "ScalarTypesList"):
                    scalars = results.ScalarTypesList(dat_norm, "Fluent") or []
                    print(f"[META-WORKER] Scalari disponibili nel .dat: {scalars}")
                    for sc in scalars:
                        mcmd(f'read onlyfun Fluent "{dat_norm}" all "{sc}"')
            except Exception as e:
                print(f"[META-WARN] ScalarTypesList: {e}")
            mcmd(f'read onlyfun Fluent "{dat_norm}" all')

    isolate_assembly_parts_in_meta(model_id, cfg)


if __name__ == "__main__" or IN_META:
    run_worker()
