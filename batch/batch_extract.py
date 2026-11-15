# -*- coding: utf-8 -*-
"""
Estrazione in blocco delle analisi CFD con FS-MetaPostDiag.

Trova tutte le cartelle che contengono un .cas e un .dat sotto una cartella
radice, sceglie i file delle ITERAZIONI (nome che contiene "iterazion" /
"iteration") e scarta le cartelle con i soli file di partenza.

Se in una cartella ci sono sia i file di partenza sia quelli con le iterazioni,
i secondi vengono isolati in una sottocartella temporanea (hardlink, quindi
nessuna copia dei GB) e l'analisi gira solo su quelli.

Uso:
    python batch_extract.py --root "D:\\Analisi" --exe "..\\FS-MetaPostDiag.exe"
    python batch_extract.py --root "D:\\Analisi" --dry-run

Solo libreria standard: nessuna installazione oltre a Python 3.8+.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time

SKIP_DIRS = {"output_diagnostics", "__pycache__"}
ISOLATED_DIR = "_solo_iterazioni"
REPORT_PATTERN = re.compile(r"^Report_CFD_.*\.html$", re.IGNORECASE)
# Riconosce i file delle iterazioni. Due convenzioni viste sul campo:
#   V14_3-1-01250.cas     -> nome<dash>iterazione<dash>id (V14_3.cas e' il file di partenza)
#   nome_1_iterazioni.cas -> contiene "iterazion"
# Il pattern si applica al nome SENZA estensione.
DEFAULT_ITER_PATTERN = r"iterazion|iterations?|-\d+-\d+$"


def human_time(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return "%d s" % seconds
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return "%d min %02d s" % (minutes, sec)
    hours, minutes = divmod(minutes, 60)
    return "%d h %02d min" % (hours, minutes)


def should_skip_dir(name: str) -> bool:
    """Cartelle di lavoro nostre o di output: mai considerate casi."""
    return name.lower() in SKIP_DIRS or name.startswith("_")


def find_case_dirs(root: str, out_dir: str) -> list:
    """Cartelle con almeno un .cas e un .dat (ricorsivo)."""
    root = os.path.abspath(root)
    out_dir = os.path.abspath(out_dir)
    cases = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not should_skip_dir(d)]
        if os.path.abspath(current).startswith(out_dir):
            continue
        lower = {f.lower() for f in files}
        if not any(f.endswith(".cas") for f in lower):
            continue
        if not any(f.endswith(".dat") for f in lower):
            continue
        cases.append(current)
    return sorted(cases, key=lambda p: os.path.relpath(p, root).lower())


def case_id_for(case_dir: str, root: str) -> str:
    rel = os.path.relpath(case_dir, root)
    if rel in (".", ""):
        rel = os.path.basename(case_dir)
    raw = rel.replace(os.sep, "__").replace("/", "__")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_")


def list_files(case_dir: str) -> tuple:
    cas = sorted(f for f in os.listdir(case_dir) if f.lower().endswith(".cas"))
    dat = sorted(f for f in os.listdir(case_dir) if f.lower().endswith(".dat"))
    return cas, dat


def pick_inputs(case_dir: str, iter_re: "re.Pattern") -> dict:
    """
    Decide quali file usare.

    Ritorna un dict con:
      stato: "OK" | "SCARTATO" | "AMBIGUO"
      motivo, cas, dat, modo ("in_place" | "isolato")
    """
    cas, dat = list_files(case_dir)
    cas_it = [f for f in cas if iter_re.search(os.path.splitext(f)[0])]
    dat_it = [f for f in dat if iter_re.search(os.path.splitext(f)[0])]

    if not cas_it or not dat_it:
        return {
            "stato": "SCARTATO",
            "motivo": "nessun file di iterazione riconosciuto "
                      "(cas: %s | dat: %s)" % (", ".join(cas) or "-", ", ".join(dat) or "-"),
            "cas": "", "dat": "", "modo": "",
        }

    ambiguous = ""
    if len(cas_it) > 1:
        ambiguous = "piu' .cas con iterazioni (%s): uso il piu' recente" % ", ".join(cas_it)
    chosen_cas = max(cas_it, key=lambda f: (os.path.getmtime(os.path.join(case_dir, f)), f))

    # il .dat si cerca con lo stesso nome base del .cas, altrimenti il piu' recente
    stem = os.path.splitext(chosen_cas)[0].lower()
    matching = [f for f in dat_it if os.path.splitext(f)[0].lower() == stem]
    if matching:
        chosen_dat = matching[0]
    else:
        if len(dat_it) > 1 and not ambiguous:
            ambiguous = "piu' .dat con iterazioni (%s): uso il piu' recente" % ", ".join(dat_it)
        chosen_dat = max(dat_it, key=lambda f: (os.path.getmtime(os.path.join(case_dir, f)), f))

    others = [f for f in cas + dat if f not in (chosen_cas, chosen_dat)]
    mode = "isolato" if others else "in_place"
    return {
        "stato": "AMBIGUO" if ambiguous else "OK",
        "motivo": ambiguous,
        "cas": chosen_cas,
        "dat": chosen_dat,
        "modo": mode,
    }


def prepare_run_dir(case_dir: str, choice: dict) -> str:
    """
    Cartella su cui eseguire l'analisi.

    In modalita' "isolato" crea `_solo_iterazioni` con hardlink ai soli file
    scelti: il programma non puo' piu' sbagliare file, e non si copiano i GB.
    """
    if choice["modo"] == "in_place":
        return case_dir
    run_dir = os.path.join(case_dir, ISOLATED_DIR)
    shutil.rmtree(run_dir, ignore_errors=True)
    os.makedirs(run_dir)
    for name in (choice["cas"], choice["dat"]):
        source = os.path.join(case_dir, name)
        target = os.path.join(run_dir, name)
        try:
            os.link(source, target)
        except OSError:
            # volumi diversi o filesystem senza hardlink: copia (con avviso)
            print("  [!] hardlink non riuscito per %s: copia del file" % name)
            shutil.copy2(source, target)
    return run_dir


def remove_run_dir(case_dir: str, choice: dict, keep_reports: bool) -> None:
    if choice["modo"] == "isolato":
        shutil.rmtree(os.path.join(case_dir, ISOLATED_DIR), ignore_errors=True)
        return
    diag = os.path.join(case_dir, "output_diagnostics")
    shutil.rmtree(diag, ignore_errors=True)
    if keep_reports:
        return
    for name in os.listdir(case_dir):
        if REPORT_PATTERN.match(name):
            try:
                os.remove(os.path.join(case_dir, name))
            except OSError:
                pass


def read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def run_case(exe: str, run_dir: str, assembly: str, config: str | None,
             timeout: int, env: dict) -> tuple:
    """Esegue l'exe su una cartella. Restituisce (codice, output, secondi)."""
    command = [exe, "-w", run_dir, "-a", assembly, "--no-meta-batch"]
    if config:
        command.extend(["-c", config])
    started = time.time()
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, errors="replace",
            timeout=timeout, env=env, cwd=os.path.dirname(exe) or None,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        return completed.returncode, output, time.time() - started
    except subprocess.TimeoutExpired as exc:
        output = ""
        for stream in (exc.stdout, exc.stderr):
            if stream:
                output += stream if isinstance(stream, str) else stream.decode("utf-8", "replace")
        return "timeout", output, time.time() - started


def status_from_output(code, output: str, payload: dict) -> tuple:
    pids = (payload.get("physics_data") or {}).get("per_pid_breakdown") or []
    if code == "timeout":
        return "TIMEOUT", "superato il tempo massimo per caso"
    checks = [line for line in output.splitlines() if "[FAIL]" in line]
    if code not in (0, None) and not pids:
        return "ERRORE", "codice %s" % code
    if not payload:
        return "ERRORE", "cfd_extracted_data.json assente o illeggibile"
    if not pids:
        return "ERRORE", "nessun PID nel JSON"
    if checks:
        return "ATTENZIONE", "%d controlli [FAIL] nel log" % len(checks)
    return "OK", ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Estrae i dati delle analisi CFD (.cas/.dat) sotto una cartella.",
    )
    parser.add_argument("--root", required=True, help="cartella radice con le analisi")
    parser.add_argument("--exe", default=None,
                        help="percorso di FS-MetaPostDiag.exe (default: accanto allo script)")
    parser.add_argument("--out", default=None,
                        help="cartella dei risultati (default: <root>/_dati_batch)")
    parser.add_argument("--assembly", default="full_car",
                        choices=["auto", "undertray", "front_wing", "rear_wing", "full_car"])
    parser.add_argument("--config", default=None, help="config.yaml alternativo")
    parser.add_argument("--timeout", type=int, default=3600, help="secondi per caso (default 3600)")
    parser.add_argument("--keep-output", action="store_true",
                        help="non cancellare output_diagnostics dopo l'estrazione")
    parser.add_argument("--keep-reports", action="store_true",
                        help="non cancellare gli HTML 'Report_CFD_*.html' accanto al caso")
    parser.add_argument("--force", action="store_true", help="riesegui anche i casi gia' fatti")
    parser.add_argument("--dry-run", action="store_true", help="elenca i casi e esci")
    parser.add_argument("--iter-keyword", default=DEFAULT_ITER_PATTERN,
                        help="espressione regolare applicata al nome SENZA estensione per "
                             "riconoscere i file delle iterazioni. "
                             "Default: %s  (copre 'V14_3-1-01250' e 'nome_1_iterazioni')"
                             % DEFAULT_ITER_PATTERN)
    parser.add_argument("--include-all", action="store_true",
                        help="non scartare le cartelle senza 'iterazioni' nel nome "
                             "(esegue tutti i .cas/.dat presenti)")
    args = parser.parse_args()

    if sys.version_info < (3, 8):
        print("ERRORE: serve Python 3.8 o superiore (trovato %s)." % sys.version.split()[0])
        return 2

    try:
        iter_re = re.compile(args.iter_keyword, re.IGNORECASE)
    except re.error as exc:
        print("ERRORE: --iter-keyword non valida: %s" % exc)
        return 2

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print("ERRORE: la cartella non esiste: %s" % root)
        return 2

    exe = os.path.abspath(args.exe) if args.exe else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "FS-MetaPostDiag.exe")
    if not args.dry_run and not os.path.isfile(exe):
        print("ERRORE: eseguibile non trovato: %s" % exe)
        print("        mettilo accanto agli script oppure passa --exe")
        return 2

    out_dir = os.path.abspath(args.out) if args.out else os.path.join(root, "_dati_batch")
    os.makedirs(out_dir, exist_ok=True)
    temp_dir = os.path.join(out_dir, "_tmp")
    os.makedirs(temp_dir, exist_ok=True)

    env = dict(os.environ)
    env["TEMP"] = temp_dir
    env["TMP"] = temp_dir

    cases = find_case_dirs(root, out_dir)
    if not cases:
        print("Nessuna cartella con .cas + .dat trovata sotto: %s" % root)
        return 1

    plan = []
    for case_dir in cases:
        cas, dat = list_files(case_dir)
        choice = pick_inputs(case_dir, iter_re)
        if choice["stato"] == "SCARTATO" and args.include_all:
            choice = {
                "stato": "OK", "motivo": "incluso con --include-all",
                "cas": cas[0] if cas else "", "dat": dat[0] if dat else "",
                "modo": "in_place" if len(cas) + len(dat) <= 2 else "isolato",
            }
        plan.append({
            "case_id": case_id_for(case_dir, root),
            "relpath": os.path.relpath(case_dir, root),
            "dir": case_dir,
            "cas_presenti": "; ".join(cas),
            "dat_presenti": "; ".join(dat),
            "choice": choice,
        })

    print("Cartella radice : %s" % root)
    print("Eseguibile      : %s" % exe)
    print("Risultati in    : %s" % out_dir)
    print("Assieme         : %s" % args.assembly)
    print("Filtro iterazioni: %s  (sul nome senza estensione)" % args.iter_keyword)
    print("Cartelle trovate: %d" % len(plan))
    print("")

    to_run = [row for row in plan if row["choice"]["stato"] != "SCARTATO"]
    skipped = [row for row in plan if row["choice"]["stato"] == "SCARTATO"]
    print("Da elaborare: %d | scartate (solo file di partenza): %d" % (len(to_run), len(skipped)))
    print("")
    for row in plan:
        choice = row["choice"]
        if choice["stato"] == "SCARTATO":
            print("  SCARTATO  %-42s  %s" % (row["case_id"][:42], choice["motivo"]))
            continue
        flag = "  [!] " + choice["motivo"] if choice["motivo"] else ""
        print("  %-9s %-42s  %s + %s  (%s)%s" % (
            choice["stato"], row["case_id"][:42], choice["cas"], choice["dat"],
            choice["modo"], flag))

    if args.dry_run:
        print("\n--dry-run: nessuna esecuzione. Togli il flag per partire.")
        return 0
    if not to_run:
        print("\nNessuna cartella con le iterazioni: non c'e' nulla da elaborare.")
        return 0

    index_path = os.path.join(out_dir, "index.csv")
    summary_path = os.path.join(out_dir, "run_summary.txt")
    metadata_path = os.path.join(out_dir, "metadata.csv")
    if not os.path.isfile(metadata_path):
        with open(metadata_path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["case_id", "nota", "velocita_nominale_ms", "parametro_1",
                             "parametro_2", "parametro_3", "parametro_4"])
            for row in to_run:
                writer.writerow([row["case_id"], "", "", "", "", "", ""])
        print("\nTemplate metadati creato: %s (compilalo quando puoi)" % metadata_path)

    rows = []
    failures = []
    started_all = time.time()
    for position, row in enumerate(to_run, 1):
        case_id = row["case_id"]
        choice = row["choice"]
        target = os.path.join(out_dir, case_id + ".json")
        log_path = os.path.join(out_dir, case_id + ".log")

        if os.path.isfile(target) and not args.force:
            payload = read_json(target)
            kpis = (payload.get("physics_data") or {}).get("summary_kpis") or {}
            rows.append({
                "case_id": case_id, "relpath": row["relpath"], "stato": "GIA_FATTO",
                "motivo": "", "secondi": 0,
                "n_pid": len((payload.get("physics_data") or {}).get("per_pid_breakdown") or []),
                "downforce_N": kpis.get("downforce_total_N", kpis.get("downforce_N")),
                "drag_N": kpis.get("drag_total_N", kpis.get("drag_N")),
                "v_inf": kpis.get("velocity_inf_ms"),
                "cas_usato": choice["cas"], "dat_usato": choice["dat"], "modo": choice["modo"],
            })
            print("[%d/%d] %-40s salto (gia' fatto)" % (position, len(to_run), case_id[:40]))
            continue

        print("[%d/%d] %-40s avvio (%s)..." % (
            position, len(to_run), case_id[:40], choice["modo"]), flush=True)
        run_dir = prepare_run_dir(row["dir"], choice)
        code, output, seconds = run_case(
            exe, run_dir, args.assembly, args.config, args.timeout, env)

        diag_json = os.path.join(run_dir, "output_diagnostics", "cfd_extracted_data.json")
        payload = read_json(diag_json) if os.path.isfile(diag_json) else {}

        with open(log_path, "w", encoding="utf-8", errors="replace") as handle:
            handle.write("== %s ==\n" % case_id)
            handle.write("cartella: %s\n" % row["dir"])
            handle.write("file usati: %s + %s (%s)\n" % (choice["cas"], choice["dat"], choice["modo"]))
            handle.write("comando: %s -w \"%s\" -a %s --no-meta-batch\n"
                         % (exe, run_dir, args.assembly))
            handle.write("codice: %s | secondi: %.1f\n\n" % (code, seconds))
            handle.write(output)

        if payload:
            with open(target, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)

        status, reason = status_from_output(code, output, payload)
        kpis = (payload.get("physics_data") or {}).get("summary_kpis") or {}
        n_pid = len((payload.get("physics_data") or {}).get("per_pid_breakdown") or [])
        rows.append({
            "case_id": case_id, "relpath": row["relpath"], "stato": status,
            "motivo": reason, "secondi": round(seconds, 1), "n_pid": n_pid,
            "downforce_N": kpis.get("downforce_total_N", kpis.get("downforce_N")),
            "drag_N": kpis.get("drag_total_N", kpis.get("drag_N")),
            "v_inf": kpis.get("velocity_inf_ms"),
            "cas_usato": choice["cas"], "dat_usato": choice["dat"], "modo": choice["modo"],
        })
        if status in ("ERRORE", "TIMEOUT"):
            failures.append((case_id, reason))

        with open(index_path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), delimiter=";")
            writer.writeheader()
            writer.writerows(rows)

        extra = "" if not payload else "  dep %.1f N | drag %.1f N | %d PID" % (
            float(rows[-1].get("downforce_N") or 0.0),
            float(rows[-1].get("drag_N") or 0.0), n_pid)
        print("         -> %-9s %.0f s%s%s" % (status, seconds, extra,
                                               "" if not reason else "  (" + reason + ")"), flush=True)

        remove_run_dir(row["dir"], choice, args.keep_reports)

    elapsed = time.time() - started_all
    done = sum(1 for row in rows if row["stato"] in ("OK", "GIA_FATTO", "ATTENZIONE"))
    with open(summary_path, "w", encoding="utf-8") as handle:
        handle.write("RIEPILOGO ESTRAZIONE\n")
        handle.write("radice: %s\neseguibile: %s\nassieme: %s\nfiltro iterazioni: %s\ndata: %s\n"
                     % (root, exe, args.assembly, args.iter_keyword,
                        time.strftime("%Y-%m-%d %H:%M:%S")))
        handle.write("cartelle: %d | da elaborare: %d | completate: %d | errori: %d | "
                     "scartate: %d | durata: %s\n"
                     % (len(plan), len(to_run), done, len(failures), len(skipped),
                        human_time(elapsed)))
        if skipped:
            handle.write("\nSCARTATE (nessuna iterazione nel nome):\n")
            for row in skipped:
                handle.write("  %-45s %s\n" % (row["case_id"], row["relpath"]))
        if failures:
            handle.write("\nDA CONTROLLARE:\n")
            for case_id, reason in failures:
                handle.write("  %-45s %s\n" % (case_id, reason))
        handle.write("\nfile: index.csv, <caso>.json, <caso>.log, metadata.csv\n")

    print("")
    print("Fatto: %d casi elaborati, %d errori, %d scartati, durata %s"
          % (len(to_run), len(failures), len(skipped), human_time(elapsed)))
    if failures:
        print("Casi da controllare (vedi run_summary.txt):")
        for case_id, reason in failures:
            print("  %-45s %s" % (case_id, reason))
    print("Risultati: %s" % out_dir)
    return 0 if not failures else 3


if __name__ == "__main__":
    raise SystemExit(main())
