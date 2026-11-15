# -*- coding: utf-8 -*-
"""
Launcher interattivo di FS-MetaPostDiag.

Un solo exe, tre modi di lavorare:

    1) singolo caso  -> pipeline completa su una cartella con .cas/.dat
    2) multi-caso   -> estrazione batch dai .cas, tabelle e suite
    3) suite        -> su una cartella dati gia' pronta
    4) geometria    -> solo geometria di un caso

Si apre con `FS-MetaPostDiag.exe --launcher` (o da un collegamento sul desktop).
Niente Python esterno: i moduli batch vengono importati dall'exe quando ci sono.
"""
from __future__ import annotations

import copy
import os
import sys
from types import SimpleNamespace

ASSEMBLIES = [("undertray", "solo fondo"), ("front_wing", "ala anteriore"),
              ("rear_wing", "ala posteriore"), ("full_car", "vettura completa")]


def _frozen_exe() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "dist", "FS-MetaPostDiag.exe"))


def _add_batch_path():
    roots = []
    here = os.path.dirname(os.path.abspath(__file__))
    project = os.path.dirname(here)
    roots.extend([os.path.join(project, "batch")])
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        roots.extend([os.path.join(bundle, "batch")])
    for folder in roots:
        if os.path.isdir(folder) and folder not in sys.path:
            sys.path.insert(0, folder)
    return roots[0] if roots else ""


def _pick_folder(title, prompt, folder_picker=None):
    if folder_picker is not None:
        return folder_picker(title) or ""
    # con input rediretto (automazione, test) niente finestra: si scrive il percorso
    if not sys.stdin.isatty() or os.environ.get("FS_METAPOSTDIAG_NO_DIALOGS"):
        return prompt("Percorso (%s): " % title).strip().strip('"')
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        folder = filedialog.askdirectory(title=title)
        root.destroy()
        if folder:
            return folder
    except Exception:  # tkinter assente o senza display: si scrive il percorso
        pass
    return prompt("Percorso: ").strip().strip('"')


def _ask(prompt, question, default=""):
    hint = (" [%s]" % default) if default else ""
    try:
        answer = prompt("%s%s: " % (question, hint)).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return answer or default


def _ask_yes(prompt, question, default=False):
    hint = "S/n" if default else "s/N"
    answer = _ask(prompt, "%s (%s)" % (question, hint), "")
    if answer is None:
        return None
    return answer.lower().startswith("s") if answer else default


def _ask_assembly(prompt):
    lines = ["  1) solo fondo", "  2) ala anteriore", "  3) ala posteriore", "  4) vettura completa (default)"]
    print("\n" + "\n".join(lines))
    answer = _ask(prompt, "Assieme", "4")
    if answer is None:
        return None
    try:
        index = int(answer) - 1
    except (TypeError, ValueError):
        index = 3
    if index < 0 or index >= len(ASSEMBLIES):
        index = 3
    return ASSEMBLIES[index][0]


def _run_batch(root, out_dir, assembly, force=False, prompt=input):
    """Importa batch_extract/make_tables/check_dataset e li esegue in sequenza."""
    _add_batch_path()
    try:
        import batch_extract
        import check_dataset
        import make_tables
    except ImportError as exc:
        print("  [!] moduli batch non disponibili in questo exe: %s" % exc)
        return 2
    saved_argv = sys.argv
    try:
        sys.argv = ["batch_extract", "--root", root, "--out", out_dir,
                    "--exe", _frozen_exe(), "--assembly", assembly]
        if force:
            sys.argv.append("--force")
        try:
            code = batch_extract.main()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        if code not in (0, None):
            print("  [!] estrazione batch terminata con codice %s" % code)
            return code
        for module, name in ((make_tables, "make_tables"), (check_dataset, "check_dataset")):
            sys.argv = [name, "--data", out_dir]
            try:
                module.main()
            except SystemExit as exc:
                if exc.code not in (0, None):
                    print("  [!] %s terminato con codice %s" % (name, exc.code))
        return 0
    finally:
        sys.argv = saved_argv


def _run_suite(cfg, pipeline, data_dir, skip_process, no_meta=True):
    from meta_driver.suite_mode import run_suite

    args = SimpleNamespace(workspace=data_dir, force=False, skip_process=skip_process,
                           no_meta_batch=no_meta, only=None)
    return run_suite(cfg, args, pipeline)


def run_launcher(cfg: dict, args, pipeline, prompt=input, folder_picker=None) -> int:
    """Menu principale. Restituisce 0 quando si esce."""
    while True:
        print("\n" + "=" * 62)
        print("  FS-MetaPostDiag  ·  launcher")
        print("=" * 62)
        print("  1) Singolo caso      report completo (cartella con .cas/.dat)")
        print("  2) Multi-caso        estrazione batch dai .cas + tabelle + suite")
        print("  3) Suite             su una cartella dati gia' pronta")
        print("  4) Solo geometria    di un caso (nessun report)")
        print("  0) Esci")
        try:
            choice = prompt("\nScelta: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nUscita.")
            return 0
        if choice in ("0", "q", "esci", ""):
            print("Fine.")
            return 0
        if choice == "1":
            folder = _pick_folder("Cartella del caso (.cas + .dat)", prompt, folder_picker)
            if not folder or not os.path.isdir(folder):
                print("  [!] cartella non valida.")
                continue
            skip_meta = _ask_yes(prompt, "Saltare il rendering META? (piu' veloce)", False)
            if skip_meta is None:
                return 0
            local = copy.deepcopy(cfg)
            local.setdefault("project", {})["workspace_dir"] = folder
            print("\n[singolo caso] %s" % folder)
            try:
                result = pipeline(local, workspace_dir=folder, force_meta_batch=not skip_meta)
            except (FileNotFoundError, RuntimeError, OSError) as exc:
                print("  [!] errore: %s" % exc)
                continue
            reports = (result or {}).get("reports") or {}
            html = reports.get("html_report") or reports.get("standalone_html_report")
            print("  completato. Report: %s" % (html or "(vedi output_diagnostics)"))
        elif choice == "2":
            root = _pick_folder("Cartella radice delle analisi", prompt, folder_picker)
            if not root or not os.path.isdir(root):
                print("  [!] cartella non valida.")
                continue
            out = _ask(prompt, "Cartella dati di uscita", os.path.join(root, "_dati_batch"))
            if out is None:
                return 0
            assembly = _ask_assembly(prompt)
            if assembly is None:
                return 0
            force = _ask_yes(prompt, "Rifare anche i casi gia' fatti", False)
            if force is None:
                return 0
            print("\n[multi-caso] estrazione dai .cas in %s" % out)
            code = _run_batch(root, out, assembly, force, prompt)
            if code != 0:
                print("  [!] batch non completato (codice %s)." % code)
                continue
            full = _ask_yes(prompt, "Generare anche i report completi per ogni caso", False)
            if full is None:
                return 0
            _run_suite(cfg, pipeline, out, skip_process=not full, no_meta=True)
        elif choice == "3":
            data = _pick_folder("Cartella dati _dati_batch (con dataset.csv)", prompt, folder_picker)
            if not data or not os.path.isdir(data):
                print("  [!] cartella non valida.")
                continue
            done = _ask_yes(prompt, "I report completi per caso sono gia' stati fatti", True)
            if done is None:
                return 0
            _run_suite(cfg, pipeline, data, skip_process=done, no_meta=True)
        elif choice == "4":
            folder = _pick_folder("Cartella del caso (.cas + .dat)", prompt, folder_picker)
            if not folder or not os.path.isdir(folder):
                print("  [!] cartella non valida.")
                continue
            from meta_driver.suite_mode import geometry_for_workspace

            local = copy.deepcopy(cfg)
            try:
                result = geometry_for_workspace(local, folder)
            except (FileNotFoundError, RuntimeError, OSError) as exc:
                print("  [!] errore: %s" % exc)
                continue
            payload = result["payload"]
            summary = payload.get("summary") or {}
            print("  %s: %d zone | fondo %s | scritto %s"
                  % (payload["case"], len((payload.get("geometry") or {}).get("zones") or []),
                     "sì" if (payload.get("geometry") or {}).get("floor", {}).get("available") else "no",
                     result["path"]))
        else:
            print("  [!] scelta non valida: %s" % choice)
