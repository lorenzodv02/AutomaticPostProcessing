# -*- coding: utf-8 -*-
"""
Modalita' suite dell'eseguibile (`FS-MetaPostDiag.exe --suite -w <cartella dati>`).

Fa quello che fa il pacchetto `Aero-Suite.zip`, ma **dentro un unico exe**:
per ogni caso esegue la pipeline completa in-process (niente sotto-processi per
caso), raccoglie gli output in `cases/<caso>/`, calcola la geometria, costruisce
le tabelle e genera `Aero_Suite.html`.

I moduli della suite (`aero_suite.py`, `brand_theme.py`, `design_explorer.py`,
`recombination.py`) vengono inclusi nell'exe come dati e importati da qui.
"""
from __future__ import annotations

import copy
import json
import os
import sys


def _bundle_roots():
    """Cartelle in cui cercare i moduli della suite (sorgenti o _MEIPASS)."""
    roots = []
    here = os.path.dirname(os.path.abspath(__file__))
    project = os.path.dirname(here)
    roots.extend([project, os.path.join(project, "suite"), os.path.join(project, "tools")])
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        roots.extend([bundle, os.path.join(bundle, "suite"), os.path.join(bundle, "tools")])
    return roots


def _ensure_paths():
    for folder in _bundle_roots():
        if os.path.isdir(folder) and folder not in sys.path:
            sys.path.insert(0, folder)


def _import_suite():
    _ensure_paths()
    import aero_suite  # noqa: WPS433

    return aero_suite


def _tools_dir():
    for folder in _bundle_roots():
        if folder.endswith(os.sep + "tools") and os.path.isdir(folder):
            return folder
    return None


def geometry_for_workspace(cfg: dict, workspace_dir: str, assembly: str = None) -> dict:
    """
    Geometria di un caso dal suo .cas, senza immagini ne report.
    Usata sia da `--geometry-only` sia dallo stadio geometria della suite.
    """
    from file_discovery import try_discover
    from meta_driver.fluent_parser import extract_real_mesh_and_cfd_data
    from meta_driver.geometry import extract_geometry

    cas_file, dat_file, discovery_error = try_discover(workspace_dir)
    if not cas_file:
        raise FileNotFoundError(discovery_error or ("nessun .cas in " + workspace_dir))
    chosen = assembly or ((cfg.get("project") or {}).get("assembly_type") or "undertray")
    convention = ((cfg.get("reference_values") or {}).get("report_force_convention") or "lift")
    data = extract_real_mesh_and_cfd_data(
        cas_path=cas_file, dat_path=dat_file, assembly_type=chosen,
        ref_values=cfg.get("reference_values", {}), config=cfg,
        force_convention=convention, log_fn=lambda message: None,
    )
    bbox = data.get("bounding_box") or {}
    scale = float(bbox.get("coord_scale_to_m") or 1.0)
    half_car = bool(data.get("is_half_car_symmetric"))
    geometry = extract_geometry(data.get("zone_meshes") or {}, bbox, coord_scale=scale,
                                assembly=data.get("assembly_type") or chosen,
                                half_car=half_car)
    payload = {
        "case": os.path.splitext(os.path.basename(cas_file))[0],
        "cas_file": cas_file,
        "assembly": data.get("assembly_type") or chosen,
        "half_car": half_car,
        "bounding_box": bbox,
        "summary": geometry.get("summary") or {},
        "geometry": geometry,
    }
    output_dir = os.path.join(workspace_dir, "output_diagnostics")
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "geometry.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return {"payload": payload, "path": path}


def _case_processor(cfg: dict, pipeline, no_meta: bool):
    """Restituisce il callable che esegue la pipeline completa su un caso."""

    def process(case_dir: str, case: dict):
        local = copy.deepcopy(cfg)
        project = local.setdefault("project", {})
        project["workspace_dir"] = case_dir
        if case.get("assembly"):
            project["assembly_type"] = case["assembly"]
        tries = 2
        last_error = None
        for _attempt in range(tries):
            try:
                pipeline(local, workspace_dir=case_dir, force_meta_batch=not no_meta)
                return True
            except (FileNotFoundError, RuntimeError, OSError) as exc:  # un caso non ferma la suite
                last_error = exc
        raise RuntimeError(str(last_error))

    return process


def _geometry_processor(cfg: dict):
    def process(case_dir: str, case: dict):
        local = copy.deepcopy(cfg)
        return geometry_for_workspace(local, case_dir, case.get("assembly"))

    return process


def run_suite(cfg: dict, args, pipeline) -> int:
    """
    Modalita' `--suite`: tutti gli stadi dentro l'exe, nessun Python esterno.
    `args.workspace` e' la cartella dati (quella con dataset.csv).
    """
    suite = _import_suite()
    data_dir = os.path.abspath(args.workspace or (cfg.get("project") or {}).get("workspace_dir") or ".")
    if not os.path.isfile(os.path.join(data_dir, "dataset.csv")):
        print("[SUITE] nella cartella non c'e' dataset.csv: %s" % data_dir)
        print("[SUITE] usa batch\\01_Estrai_tutti.bat per generarlo dai .cas, oppure passa la cartella giusta con -w.")
        return 2
    tools = _tools_dir()
    no_meta = bool(getattr(args, "no_meta_batch", False))
    only = [name.strip() for name in (getattr(args, "only", None) or "").split(",") if name.strip()] or None
    print("[SUITE] cartella dati: %s" % data_dir)
    failures = 0
    if not getattr(args, "skip_process", False):
        print("\n[1/4] report completi per ogni caso (in-process)")
        _total, failed = suite.stage_process(
            data_dir, exe=None, force=getattr(args, "force", False),
            processor=_case_processor(cfg, pipeline, no_meta), only=only)
        failures += failed
    else:
        print("\n[1/4] report completi saltati (--skip-process)")
    print("\n[2/4] geometria dalla mesh")
    _total, failed = suite.stage_geometry(
        data_dir, exe=None, force=getattr(args, "force", False), only=only,
        processor=_geometry_processor(cfg))
    failures += failed
    print("\n[3/4] tabelle")
    suite.stage_tables(data_dir)
    print("\n[4/4] dashboard")
    suite.stage_dashboard(data_dir, tools)
    print("\nFatto. Apri: %s" % os.path.join(data_dir, "Aero_Suite.html"))
    return 0 if failures == 0 else 3
