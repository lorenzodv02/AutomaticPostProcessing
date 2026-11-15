# -*- coding: utf-8 -*-
"""
Estrazione in blocco delle analisi CFD con FS-MetaPostDiag.

Trova tutte le cartelle che contengono un .cas e un .dat sotto una cartella
radice, esegue il post-processing su ciascuna e salva solo il JSON dei dati
estratti (poche centinaia di KB per caso) piu' il log.

Uso:
    python batch_extract.py --root "D:\\Analisi" --exe "..\\FS-MetaPostDiag.exe"

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

SKIP_DIRS = {"output_diagnostics", "_tmp", "_dati", "_dati_batch", "__pycache__"}
REPORT_PATTERN = re.compile(r"^Report_CFD_.*\.html$", re.IGNORECASE)


def human_time(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return "%d s" % seconds
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return "%d min %02d s" % (minutes, sec)
    hours, minutes = divmod(minutes, 60)
    return "%d h %02d min" % (hours, minutes)


def find_case_dirs(root: str, out_dir: str) -> list:
    """Cartelle con almeno un .cas e un .dat (ricorsivo)."""
    root = os.path.abspath(root)
    out_dir = os.path.abspath(out_dir)
    cases = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]
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


def list_inputs(case_dir: str) -> tuple:
    cas = sorted(f for f in os.listdir(case_dir) if f.lower().endswith(".cas"))
    dat = sorted(f for f in os.listdir(case_dir) if f.lower().endswith(".dat"))
    return cas, dat


def read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def clean_outputs(case_dir: str, keep_reports: bool) -> None:
    """Toglie i file pesanti generati nel caso, tenendo quelli piccoli."""
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


def run_case(exe: str, case_dir: str, assembly: str, config: str | None,
             timeout: int, env: dict) -> tuple:
    """Esegue l'exe su un caso. Restituisce (codice, output, secondi)."""
    command = [exe, "-w", case_dir, "-a", assembly, "--no-meta-batch"]
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
    """(stato, motivo) leggibile, basato sul JSON e sull'output."""
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
        description="Estrae i dati di tutte le analisi CFD (.cas/.dat) sotto una cartella.",
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
    args = parser.parse_args()

    if sys.version_info < (3, 8):
        print("ERRORE: serve Python 3.8 o superiore (trovato %s)." % sys.version.split()[0])
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

    print("Cartella radice : %s" % root)
    print("Eseguibile      : %s" % exe)
    print("Risultati in    : %s" % out_dir)
    print("Assieme         : %s" % args.assembly)
    print("Casi trovati    : %d" % len(cases))
    print("")

    plan = []
    for case_dir in cases:
        cas, dat = list_inputs(case_dir)
        plan.append({
            "case_id": case_id_for(case_dir, root),
            "relpath": os.path.relpath(case_dir, root),
            "dir": case_dir,
            "cas": "; ".join(cas),
            "dat": "; ".join(dat),
            "n_cas": len(cas),
            "n_dat": len(dat),
        })

    for row in plan:
        flag = "" if row["n_cas"] == 1 and row["n_dat"] == 1 else "  [!] piu' file nella cartella"
        print("  %-45s  (%s)%s" % (row["case_id"][:45], row["relpath"], flag))

    if args.dry_run:
        print("\n--dry-run: nessuna esecuzione. Togli il flag per partire.")
        return 0

    index_path = os.path.join(out_dir, "index.csv")
    summary_path = os.path.join(out_dir, "run_summary.txt")
    metadata_path = os.path.join(out_dir, "metadata.csv")
    if not os.path.isfile(metadata_path):
        with open(metadata_path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["case_id", "nota", "velocita_nominale_ms", "parametro_1",
                             "parametro_2", "parametro_3", "parametro_4"])
            for row in plan:
                writer.writerow([row["case_id"], "", "", "", "", "", ""])
        print("\nTemplate metadati creato: %s (compilalo quando puoi)" % metadata_path)

    rows = []
    failures = []
    started_all = time.time()
    for position, row in enumerate(plan, 1):
        target = os.path.join(out_dir, row["case_id"] + ".json")
        log_path = os.path.join(out_dir, row["case_id"] + ".log")
        cas, dat = list_inputs(row["dir"])
        row.update({"cas": "; ".join(cas), "dat": "; ".join(dat),
                    "n_cas": len(cas), "n_dat": len(dat)})

        if os.path.isfile(target) and not args.force:
            payload = read_json(target)
            kpis = (payload.get("physics_data") or {}).get("summary_kpis") or {}
            rows.append({
                "case_id": row["case_id"], "relpath": row["relpath"],
                "stato": "GIA_FATTO", "motivo": "", "secondi": 0,
                "n_pid": len((payload.get("physics_data") or {}).get("per_pid_breakdown") or []),
                "downforce_N": kpis.get("downforce_total_N", kpis.get("downforce_N")),
                "drag_N": kpis.get("drag_total_N", kpis.get("drag_N")),
                "v_inf": kpis.get("velocity_inf_ms"),
                "cas": row["cas"], "dat": row["dat"],
            })
            print("[%d/%d] %-40s salto (gia' fatto)" % (position, len(plan), row["case_id"][:40]))
            continue

        print("[%d/%d] %-40s avvio..." % (position, len(plan), row["case_id"][:40]), flush=True)
        code, output, seconds = run_case(
            exe, row["dir"], args.assembly, args.config, args.timeout, env)

        diag_json = os.path.join(row["dir"], "output_diagnostics", "cfd_extracted_data.json")
        payload = {}
        if os.path.isfile(diag_json):
            payload = read_json(diag_json)

        with open(log_path, "w", encoding="utf-8", errors="replace") as handle:
            handle.write("== %s ==\n" % row["case_id"])
            handle.write("cartella: %s\n" % row["dir"])
            handle.write("comando: %s -w \"%s\" -a %s --no-meta-batch\n"
                         % (exe, row["dir"], args.assembly))
            handle.write("codice: %s | secondi: %.1f\n\n" % (code, seconds))
            handle.write(output)

        if payload:
            with open(target, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)

        status, reason = status_from_output(code, output, payload)
        kpis = (payload.get("physics_data") or {}).get("summary_kpis") or {}
        n_pid = len((payload.get("physics_data") or {}).get("per_pid_breakdown") or [])
        rows.append({
            "case_id": row["case_id"], "relpath": row["relpath"],
            "stato": status, "motivo": reason, "secondi": round(seconds, 1),
            "n_pid": n_pid,
            "downforce_N": kpis.get("downforce_total_N", kpis.get("downforce_N")),
            "drag_N": kpis.get("drag_total_N", kpis.get("drag_N")),
            "v_inf": kpis.get("velocity_inf_ms"),
            "cas": row["cas"], "dat": row["dat"],
        })
        if status in ("ERRORE", "TIMEOUT"):
            failures.append((row["case_id"], reason))

        # tabella d'avanzamento riscritta ogni volta (sopravvive a un'interruzione)
        with open(index_path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), delimiter=";")
            writer.writeheader()
            writer.writerows(rows)

        extra = "" if not payload else "  dep %.1f N | drag %.1f N | %d PID" % (
            float(rows[-1].get("downforce_N") or 0.0),
            float(rows[-1].get("drag_N") or 0.0), n_pid)
        print("         -> %-9s %.0f s%s%s" % (status, seconds, extra,
                                               "" if not reason else "  (" + reason + ")"), flush=True)

        clean_outputs(row["dir"], args.keep_reports)

    elapsed = time.time() - started_all
    done = sum(1 for row in rows if row["stato"] in ("OK", "GIA_FATTO", "ATTENZIONE"))
    with open(summary_path, "w", encoding="utf-8") as handle:
        handle.write("RIEPILOGO ESTRAZIONE\n")
        handle.write("radice: %s\neseguibile: %s\nassieme: %s\ndata: %s\n"
                     % (root, exe, args.assembly, time.strftime("%Y-%m-%d %H:%M:%S")))
        handle.write("casi: %d | completati: %d | errori: %d | durata: %s\n"
                     % (len(plan), done, len(failures), human_time(elapsed)))
        if failures:
            handle.write("\nDA CONTROLLARE:\n")
            for case_id, reason in failures:
                handle.write("  %-45s %s\n" % (case_id, reason))
        handle.write("\nfile: index.csv, <caso>.json, <caso>.log, metadata.csv\n")

    print("")
    print("Fatto: %d casi, %d errori, durata %s" % (len(plan), len(failures), human_time(elapsed)))
    if failures:
        print("Casi da controllare (vedi run_summary.txt):")
        for case_id, reason in failures:
            print("  %-45s %s" % (case_id, reason))
    print("Risultati: %s" % out_dir)
    return 0 if not failures else 3


if __name__ == "__main__":
    raise SystemExit(main())
