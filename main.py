# -*- coding: utf-8 -*-
"""
================================================================================
FS-MetaPostDiag - Main Entrypoint (main.py)
================================================================================
Programma generale per il post-processing automatico e verificato di analisi CFD
Formula Student (Undertray, Front Wing, Rear Wing, Full Car) attraverso:
  - Scompattazione diretta binaria della mesh 3D e dei campi CFD da file .cas e .dat
  - Esecuzione automatica di BETA CAE META Post v25.1+ (.ses + API Python)
  - Gate di Verifica Rigorosa (verifier.py) contro immagini vuote o dati sintetici
  - Diagnosi automatica per singolo PID e Report Interattivo HTML/PDF

Sistema di Riferimento predefinito:
  - Asse X: Longitudinale (verso dietro)
  - Asse Y: Verticale (verso l'alto)
  - Asse Z: Laterale (spanwise, Z = 0 piano di simmetria)
================================================================================
"""

import os
import sys
import argparse
import webbrowser

from meta_driver.launcher import run_postprocessing_session
from analyzer.image_diagnostics import analyze_and_annotate_images
from analyzer.aero_plots import generate_aerodynamic_plots
from analyzer.assembly_rules import evaluate_design_issues
from analyzer.ai_vision_advisor import generate_ai_vision_commentary
from reporting.report_builder import build_diagnostic_reports
from config_bridge import load_config as load_config_file
from config_bridge import validate_config
from file_discovery import NoCaseFilesFound, try_discover
from meta_driver.fluent_parser import extract_real_mesh_and_cfd_data
from meta_driver.geometry import extract_geometry
from version import __version__

# Percorso del config.yaml effettivamente usato (None = default interni)
LAST_CONFIG_PATH = None


def _launch_gui_by_default(argc: int) -> bool:
    """
    Vero quando il programma e' stato avviato senza argomenti.

    Un doppio clic sull'eseguibile passa un solo argomento (sys.argv[0]): in quel
    caso si apre la GUI. Prima invece partiva la pipeline sulla cartella corrente,
    scegliendo qualunque `*.cas`/`*.dat` presente (su un Desktop poteva essere la
    licenza di BETA CAE) e finendo in un traceback. Con `-w`, `-a` o `--config`
    resta la pipeline da riga di comando.
    """
    return argc <= 1


def load_config(config_path: str = None) -> dict:
    """
    Carica il `config.yaml` e lo fonde sopra i default di `config_bridge`.

    Ordine di ricerca (vedi `config_bridge.find_config_path`): `--config`, poi
    accanto all'eseguibile / ai sorgenti, poi il `config.yaml` incluso nel
    bundle dell'exe. Senza configurazione si usano i default interni.
    """
    global LAST_CONFIG_PATH
    config, LAST_CONFIG_PATH = load_config_file(config_path)
    return config


def execute_full_diagnostic_pipeline(config: dict, workspace_dir: str = None, log_fn=print, force_meta_batch: bool = True) -> dict:
    """
    Esegue l'intera pipeline verificata in 4 fasi:
      1) Scompattazione binaria .cas/.dat, isolamento PID, esecuzione META Post v25.1 e rendering mesh reale
      2) Audit di Verifica Rigorosa (verifier.py) + elaborazione Computer Vision sui cluster reali
      3) Generazione dei 5 grafici aerodinamici ingegneristici (incluso Riparto per Singolo PID)
      4) Valutazione problematiche di design basata sui PID reali e compilazione Report HTML/Markdown
    """
    if workspace_dir is None:
        workspace_dir = os.path.abspath(config.get("project", {}).get("workspace_dir", "."))

    log_fn("================================================================================")
    log_fn(" AVVIO PIPELINE VERIFICATA POST-PROCESSING CFD (.CAS/.DAT + BETA CAE META POST)")
    log_fn("================================================================================")

    # Fase 1: Estrazione Mesh/CFD Reale & Sessione META Post
    log_fn("[FASE 1/4] Scompattazione binaria .cas/.dat, isolamento PID ed esecuzione META Post...")
    session_bundle = run_postprocessing_session(
        config, workspace_dir=workspace_dir, force_meta_batch=force_meta_batch, log_fn=log_fn
    )
    pdata = session_bundle.get("physics_data", {})
    cas_info = session_bundle.get("cas_info", {})
    target_zones = cas_info.get("target_zones", [])

    log_fn(f"  -> Assieme selezionato: {session_bundle['assembly_type'].upper()}")
    log_fn(f"  -> File .cas: {session_bundle.get('cas_file')} ({cas_info.get('cas_size_mb', 0)} MB)")
    log_fn(f"  -> File .dat: {session_bundle.get('dat_file')}")
    log_fn(f"  -> Nodi 3D reali letti: {pdata.get('nodes_read', 0):,} | Facce 3D reali lette: {pdata.get('faces_read', 0):,}")
    log_fn(f"  -> Modello Half-Car Simmetrico (symmetry Z=0): {pdata.get('is_half_car_symmetric', False)}")
    _kpis = pdata.get("summary_kpis", {})
    log_fn(
        f"  -> Provenienza dato viscoso: {_kpis.get('viscous_source', 'n/d')} | "
        f"CL*A = {_kpis.get('CL_A', 0.0)} m^2 | CL = {_kpis.get('CL', 0.0)} | "
        f"CD = {_kpis.get('CD', 0.0)}"
    )
    log_fn(f"  -> PID isolati ({len(target_zones)}): {[z['name'] for z in target_zones]}")
    log_fn(f"  -> Eseguibile META Post: {session_bundle.get('meta_executable') or 'Non rilevato'}")
    log_fn(f"  -> Viste mesh/CFD generate: {len(session_bundle['exported_images'])}")

    # Fase 2: Audit di Verifica & Computer Vision
    log_fn("[FASE 2/4] Audit di verifica rigorosa (verifier.py) e annotazione cluster reali...")
    cv_results = analyze_and_annotate_images(session_bundle)
    ver_rep = cv_results.get("verification_report", {})
    for chk in ver_rep.get("checks", []):
        log_fn(f"  -> [{chk['status']}] {chk['id']} {chk['name']}: {chk['measured']}")
    log_fn(f"  -> Immagini verificate e annotate: {len(cv_results['annotated_images'])}")

    # Fase 3: Generazione Grafici Ingegneristici
    log_fn("[FASE 3/4] Generazione dei 5 grafici aerodinamici quantitativi (incluso riparto per PID)...")
    plots_manifest = generate_aerodynamic_plots(session_bundle)
    log_fn(f"  -> Grafici generati: {len(plots_manifest)}")

    # Fase 4: Diagnosi Problematiche Design per PID + Report HTML
    log_fn("[FASE 4/4] Diagnosi problematiche sui PID reali e compilazione Report HTML...")
    design_issues = evaluate_design_issues(session_bundle, cv_results)
    ai_review = generate_ai_vision_commentary(config, session_bundle, cv_results, design_issues, plots_manifest)
    reports = build_diagnostic_reports(
        config=config,
        session_bundle=session_bundle,
        cv_results=cv_results,
        plots_manifest=plots_manifest,
        design_issues=design_issues,
        ai_review=ai_review
    )

    log_fn("================================================================================")
    log_fn(" PIPELINE VERIFICATA COMPLETATA CON SUCCESSO!")
    log_fn(f"  * Report Interattivo HTML : {reports['html_report']}")
    log_fn(f"  * Report Tecnico Markdown : {reports['markdown_report']}")
    log_fn(f"  * Sessione Interattiva META: {session_bundle.get('interactive_ses_path')}")
    log_fn("================================================================================")

    return {
        "session_bundle": session_bundle,
        "cv_results": cv_results,
        "plots_manifest": plots_manifest,
        "design_issues": design_issues,
        "ai_review": ai_review,
        "reports": reports
    }


def _run_geometry_only(cfg: dict, args) -> int:
    """Estrae solo la geometria del fondo/assieme e scrive geometry.json."""
    from meta_driver.suite_mode import geometry_for_workspace

    workspace = args.workspace or (cfg.get("project") or {}).get("workspace_dir") or os.getcwd()
    try:
        result = geometry_for_workspace(cfg, workspace, args.assembly)
    except FileNotFoundError as exc:
        print("[GEOMETRIA] %s" % exc)
        return 2
    payload = result["payload"]
    summary = payload.get("summary") or {}
    geometry = payload.get("geometry") or {}
    print("[GEOMETRIA] caso: %s | assieme: %s | %d zone"
          % (payload["case"], payload.get("assembly") or "?",
             len(geometry.get("zones") or [])))
    floor = geometry.get("floor") or {}
    if floor.get("available"):
        ramp = floor.get("ramp") or {}
        indexes = floor.get("x_m") or [0.0]
        position = min(int(floor.get("throat_pct", 0) / 100.0 * (len(indexes) - 1)), len(indexes) - 1)
        print("[GEOMETRIA] fondo: %.2f..%.2f m | altezza minima %.1f mm | %s %.1f deg | espansione %.2f"
              % (floor["x_range_m"][0], floor["x_range_m"][1],
                 (floor.get("h_min_m") or [0.0])[position] * 1000.0,
                 ramp.get("kind") or "salita", ramp.get("angle_deg") or 0.0,
                 floor.get("expansion_ratio") or 0.0))
    wings = geometry.get("wings") or {}
    for label, wing in (("ala anteriore", wings.get("front")), ("ala posteriore", wings.get("rear"))):
        if wing and wing.get("available"):
            print("[GEOMETRIA] %s: apertura %.2f m | corda media %.3f m | area %.3f m2 | allungamento %.2f"
                  % (label, wing["span_m"], wing["chord_mean_m"] or 0.0,
                     wing["planform_m2"], wing["aspect_ratio"] or 0.0))
    print("[GEOMETRIA] scritto: %s" % result["path"])
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Post-Processing CFD Verificato & Diagnostica Design attraverso BETA CAE META Post (Formula Student)"
    )
    parser.add_argument("--workspace", "-w", type=str, default=None, help="Cartella contenente i file .cas e .dat")
    parser.add_argument(
        "--assembly", "-a", type=str, default=None,
        choices=["auto", "undertray", "front_wing", "rear_wing", "full_car"],
        help="Tipo di assieme aerodinamico (default: undertray)"
    )
    parser.add_argument("--config", "-c", type=str, default=None, help="Percorso al file config.yaml")
    parser.add_argument(
        "--version",
        action="version",
        version="FS-MetaPostDiag %s" % __version__,
        help="Mostra la versione del programma ed esce",
    )
    parser.add_argument("--meta-exe", type=str, default=None, help="Percorso all'eseguibile meta_post64.bat / meta_post.exe")
    parser.add_argument(
        "--no-meta-batch",
        action="store_true",
        help="Disabilita l'avvio batch di META Post e usa solo il motore Python autonomo",
    )
    parser.add_argument(
        "--ai-model",
        type=str,
        default=None,
        help="Modello AI Vision Advisor (default: dal config.yaml, es. gemini-3.8-flash)",
    )
    parser.add_argument(
        "--ai-key", type=str, default=None,
        help="API key AI Vision da usare in questa esecuzione (non viene salvata su disco)",
    )
    parser.add_argument(
        "--ai-provider", type=str, default=None,
        help="Provider AI Vision da usare in questa esecuzione: gemini | openai | deepseek",
    )
    parser.add_argument(
        "--ai-check", action="store_true",
        help="Verifica la configurazione AI Vision (chiave, modelli disponibili, chiamata minima) ed esce",
    )
    parser.add_argument("--gui", action="store_true", help="Avvia l'interfaccia grafica desktop")
    parser.add_argument("--open-report", action="store_true", help="Apre automaticamente il report HTML nel browser")
    parser.add_argument("--geometry-only", action="store_true",
                        help="Estrae solo la geometria del fondo dalla mesh (.cas) e scrive output_diagnostics/geometry.json, senza immagini ne report")
    parser.add_argument("--suite", action="store_true",
                        help="Modalita' suite: -w e' la cartella dati (dataset.csv). Esegue report completi, "
                             "geometria, tabelle e dashboard in un solo exe")
    parser.add_argument("--skip-process", action="store_true",
                        help="Con --suite: salta i report completi (solo geometria/tabelle/dashboard)")
    parser.add_argument("--only", type=str, default=None,
                        help="Con --suite: limita ai casi indicati (separati da virgola)")
    parser.add_argument("--force", action="store_true",
                        help="Con --suite: rifai anche i casi gia' presenti")

    args = parser.parse_args()
    cfg = load_config(args.config)
    print("[CONFIG] %s" % (LAST_CONFIG_PATH or "default interni (nessun config.yaml trovato)"))
    for _warning in validate_config(cfg):
        print("[CONFIG-WARN] %s" % _warning)

    if args.workspace:
        cfg["project"]["workspace_dir"] = args.workspace
    if args.assembly:
        cfg["project"]["assembly_type"] = args.assembly
    if args.meta_exe:
        cfg["meta"]["executable_path"] = args.meta_exe
    if args.ai_provider:
        cfg.setdefault("ai_vision", {})["provider"] = args.ai_provider.strip().lower()
    if args.ai_key:
        cfg.setdefault("ai_vision", {})["api_key"] = args.ai_key.strip()
    if args.ai_model:
        provider = str(cfg.get("ai_vision", {}).get("provider", "gemini")).strip().lower()
        model_key = {
            "openai": "model_openai",
            "deepseek": "model_deepseek",
        }.get(provider, "model_gemini")
        cfg.setdefault("ai_vision", {})[model_key] = args.ai_model

    if args.ai_check:
        from analyzer.ai_vision_advisor import deepseek_check

        ai_cfg = cfg.get("ai_vision", {})
        provider = str(ai_cfg.get("provider", "gemini") or "").strip().lower()
        print("[AI-CHECK] provider: %s" % provider)
        if provider != "deepseek":
            print("[AI-CHECK] il controllo dettagliato copre il provider 'deepseek'. "
                  "Per '%s' servono chiave e modello nel config." % provider)
        info = deepseek_check(ai_cfg)
        print("[AI-CHECK] endpoint: %s" % info["base_url"])
        print("[AI-CHECK] modello richiesto: %s" % info["model"])
        print("[AI-CHECK] chiave: %s" % (
            "presente (" + info["key_masked"] + ")" if info["key_present"]
            else "ASSENTE (passa --ai-key sk-... oppure imposta DEEPSEEK_API_KEY)"))
        if info["models_error"]:
            print("[AI-CHECK] errore su GET /models -> %s" % info["models_error"])
        elif info["models"]:
            print("[AI-CHECK] modelli disponibili per questa chiave: %s" % ", ".join(info["models"]))
            if info["model_available"] is False:
                print("[AI-CHECK] ATTENZIONE: '%s' NON e' tra i modelli disponibili: usa uno degli id elencati."
                      % info["model"])
        else:
            print("[AI-CHECK] GET /models non ha restituito modelli.")
        if info["modalities"]:
            print("[AI-CHECK] modalita' di input dichiarate: %s" % ", ".join(info["modalities"]))
        if info["thinking_call"]:
            print("[AI-CHECK] chiamata con thinking: %s" % info["thinking_call"])
        if info["vision_probe"]:
            print("[AI-CHECK] prova vision (PNG 1x1): %s" % info["vision_probe"])
            if info["vision_supported"] is False:
                print("[AI-CHECK] questo modello NON accetta immagini: la perizia sara' solo testo. "
                      "Serve un modello con input 'image'.")
        if info["text_call"]:
            print("[AI-CHECK] chiamata senza thinking: %s" % info["text_call"])
        if info["models_error"] or (info["thinking_call"] and not info["thinking_call"].startswith("ok")):
            print("[AI-CHECK] suggerimenti: verifica che la chiave sia di platform.deepseek.com, "
                  "che il modello sia tra quelli elencati e che l'account abbia credito.")
        return 0

    if args.suite:
        from meta_driver.suite_mode import run_suite

        return run_suite(cfg, args, execute_full_diagnostic_pipeline)

    if args.geometry_only:
        return _run_geometry_only(cfg, args)

    if args.gui or _launch_gui_by_default(len(sys.argv)):
        from gui_app import launch_gui

        launch_gui(cfg, execute_full_diagnostic_pipeline)
        return

    try:
        res = execute_full_diagnostic_pipeline(
            cfg, workspace_dir=args.workspace, force_meta_batch=not args.no_meta_batch
        )
    except NoCaseFilesFound as exc:
        # Errore d'uso, non un bug: messaggio chiaro invece del traceback.
        print("[ERRORE] %s" % exc)
        raise SystemExit(2)
    except (FileNotFoundError, RuntimeError) as exc:
        print("[ERRORE] %s" % exc)
        raise SystemExit(1)

    if args.open_report:
        html_p = res["reports"]["html_report"]
        if os.path.isfile(html_p):
            webbrowser.open(f"file:///{html_p.replace(os.sep, '/')}")


if __name__ == "__main__":
    main()
