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
import yaml

from meta_driver.launcher import run_postprocessing_session
from analyzer.image_diagnostics import analyze_and_annotate_images
from analyzer.aero_plots import generate_aerodynamic_plots
from analyzer.assembly_rules import evaluate_design_issues
from analyzer.ai_vision_advisor import generate_ai_vision_commentary
from reporting.report_builder import build_diagnostic_reports


def load_config(config_path: str = None) -> dict:
    """Carica il file config.yaml o restituisce la configurazione predefinita."""
    if config_path is None:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    if os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {
        "project": {"workspace_dir": ".", "output_dir": "./output_diagnostics", "assembly_type": "undertray"},
        "coordinate_system": {"longitudinal_axis": "X", "vertical_axis": "Y", "lateral_axis": "Z"},
        "reference_values": {"velocity_inf": 16.67, "density_air": 1.225, "pressure_inf": 0.0, "reference_area": 1.0},
        "meta": {"executable_path": "auto", "batch_mode": True, "image_width": 1920, "image_height": 1080},
        "ai_vision": {"enabled": True, "provider": "gemini", "model_gemini": "gemini-3.8-flash", "api_key": ""}
    }


def execute_full_diagnostic_pipeline(config: dict, workspace_dir: str = None, log_fn=print) -> dict:
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
    session_bundle = run_postprocessing_session(config, workspace_dir=workspace_dir, log_fn=log_fn)
    pdata = session_bundle.get("physics_data", {})
    cas_info = session_bundle.get("cas_info", {})
    target_zones = cas_info.get("target_zones", [])

    log_fn(f"  -> Assieme selezionato: {session_bundle['assembly_type'].upper()}")
    log_fn(f"  -> File .cas: {session_bundle.get('cas_file')} ({cas_info.get('cas_size_mb', 0)} MB)")
    log_fn(f"  -> File .dat: {session_bundle.get('dat_file')}")
    log_fn(f"  -> Nodi 3D reali letti: {pdata.get('nodes_read', 0):,} | Facce 3D reali lette: {pdata.get('faces_read', 0):,}")
    log_fn(f"  -> Modello Half-Car Simmetrico (symmetry Z=0): {pdata.get('is_half_car_symmetric', False)}")
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
    parser.add_argument("--meta-exe", type=str, default=None, help="Percorso all'eseguibile meta_post64.bat / meta_post.exe")
    parser.add_argument("--gui", action="store_true", help="Avvia l'interfaccia grafica desktop")
    parser.add_argument("--open-report", action="store_true", help="Apre automaticamente il report HTML nel browser")

    args = parser.parse_args()
    cfg = load_config(args.config)

    if args.workspace:
        cfg["project"]["workspace_dir"] = args.workspace
    if args.assembly:
        cfg["project"]["assembly_type"] = args.assembly
    if args.meta_exe:
        cfg["meta"]["executable_path"] = args.meta_exe

    if args.gui:
        from gui_app import launch_gui
        launch_gui(cfg, execute_full_diagnostic_pipeline)
    else:
        res = execute_full_diagnostic_pipeline(cfg, workspace_dir=args.workspace)
        if args.open_report:
            html_p = res["reports"]["html_report"]
            if os.path.isfile(html_p):
                webbrowser.open(f"file:///{html_p.replace(os.sep, '/')}")


if __name__ == "__main__":
    main()
