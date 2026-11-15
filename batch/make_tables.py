# -*- coding: utf-8 -*-
"""
Trasforma i JSON estratti in due tabelle pronte per Excel/pandas.

    dataset.csv      una riga per caso (KPI globali)
    dataset_pid.csv  una riga per caso x PID (forze per zona)

Se nella cartella dati c'e' `metadata.csv` (compilato a mano), le sue colonne
vengono aggiunte in coda a dataset.csv.

Uso:
    python make_tables.py --data "D:\\Analisi\\_dati_batch"
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re

# Fluent salva i file come <nome>-<passo>-<iterazioni>.cas (es. V14_3-1-01250.cas):
# l'ultimo numero e' l'iterazione a cui e' stato scritto il caso.
ITERATION_RE = re.compile(r"-(\d+)-(\d+)$")


def iterations_from_name(filename):
    """Numero di iterazioni letto dal nome del file, o None se non c'e'."""
    stem = os.path.splitext(str(filename or ""))[0]
    match = ITERATION_RE.search(stem)
    if not match:
        return None
    try:
        return int(match.group(2))
    except ValueError:
        return None


# colonne dei KPI globali: (nome nel JSON, intestazione CSV)
KPI_COLUMNS = [
    ("velocity_inf_ms", "v_inf_ms"),
    ("is_half_car_symmetric", "half_car"),
    ("downforce_total_N", "deportanza_N"),
    ("drag_total_N", "drag_N"),
    ("CL", "CL"),
    ("CD", "CD"),
    ("cl_a_total", "CL_A"),
    ("cd_a_total", "CD_A"),
    ("efficiency_l_d", "L_D"),
    ("cop_x_m", "cop_x_m"),
    ("cop_x_pct", "cop_x_pct"),
    ("cop_wheelbase_pct", "cop_passo_pct"),
    ("stalled_surface_pct", "stallo_pct"),
    ("peak_suction_cp", "cp_min"),
    ("peak_suction_x_pct", "cp_min_x_pct"),
    ("vortex_stability_pct", "flusso_attaccato_pct"),
    ("total_surface_area_m2", "area_superficie_m2"),
    ("total_faces_analyzed", "facce"),
    ("reference_area_m2", "area_riferimento_m2"),
    ("force_convention", "convenzione"),
    ("viscous_source", "fonte_viscosa"),
]

PID_COLUMNS = [
    ("zone_name", "zone_name"),
    ("zone_id", "zone_id"),
    ("n_faces", "n_faces"),
    ("area_m2", "area_m2"),
    ("cp_min", "cp_min"),
    ("cp_mean", "cp_mean"),
    ("downforce_pressure_1x_N", "df_pressione_1x_N"),
    ("downforce_viscous_1x_N", "df_viscosa_1x_N"),
    ("downforce_1x_N", "df_1x_N"),
    ("downforce_2x_N", "df_2x_N"),
    ("drag_pressure_1x_N", "drag_pressione_1x_N"),
    ("drag_viscous_1x_N", "drag_viscosa_1x_N"),
    ("drag_1x_N", "drag_1x_N"),
    ("drag_2x_N", "drag_2x_N"),
    ("stalled_area_pct", "stallo_pct"),
    ("viscous_source", "fonte_viscosa"),
]


def load_cases(data_dir: str) -> list:
    cases = []
    for path in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        name = os.path.basename(path)
        if name.startswith("_"):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as exc:
            print("  [!] salto %s (%s)" % (name, exc))
            continue
        physics = payload.get("physics_data") or {}
        kpis = physics.get("summary_kpis") or {}
        pids = physics.get("per_pid_breakdown") or []
        if not kpis:
            print("  [!] salto %s (nessun KPI)" % name)
            continue
        cases.append({
            "case_id": os.path.splitext(name)[0],
            "json": path,
            "kpis": kpis,
            "pids": pids,
            "assembly": payload.get("assembly_type", ""),
            "cas": os.path.basename(payload.get("cas_file") or ""),
            "dat": os.path.basename(payload.get("dat_file") or ""),
            "iterazioni": iterations_from_name(payload.get("cas_file") or ""),
            "config": payload.get("config") or {},
        })
    return cases


def read_metadata(data_dir: str) -> tuple:
    path = os.path.join(data_dir, "metadata.csv")
    if not os.path.isfile(path):
        return [], []
    for delimiter in (";", ","):
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter=delimiter))
        except OSError:
            return [], []
        if rows and len(rows[0]) > 1:
            header = list(rows[0].keys())
            return header, rows
    return [], []


def write_csv(path: str, header: list, rows: list) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(header)
        for row in rows:
            writer.writerow([row.get(key, "") for key in header])


def main() -> int:
    parser = argparse.ArgumentParser(description="Costruisce dataset.csv e dataset_pid.csv.")
    parser.add_argument("--data", default=None, help="cartella con i JSON (default: _dati_batch accanto)")
    args = parser.parse_args()

    data_dir = args.data or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_dati_batch")
    data_dir = os.path.abspath(data_dir)
    if not os.path.isdir(data_dir):
        print("ERRORE: cartella non trovata: %s" % data_dir)
        return 2

    cases = load_cases(data_dir)
    if not cases:
        print("Nessun JSON valido in: %s" % data_dir)
        return 1

    meta_header, meta_rows = read_metadata(data_dir)
    meta_by_case = {}
    for row in meta_rows:
        key = (row.get("case_id") or "").strip()
        if key:
            meta_by_case[key] = row

    # ---------------- dataset.csv (un caso per riga) ----------------
    header = ["case_id", "assieme", "cas_file", "dat_file", "iterazioni"] + [csv_name for _key, csv_name in KPI_COLUMNS]
    extra_meta = [name for name in meta_header if name != "case_id" and name not in header]
    header += extra_meta

    rows = []
    for case in cases:
        kpis = case["kpis"]
        row = {"case_id": case["case_id"], "assieme": case["assembly"],
               "cas_file": case.get("cas", ""), "dat_file": case.get("dat", ""),
               "iterazioni": "" if case.get("iterazioni") is None else case["iterazioni"]}
        for key, csv_name in KPI_COLUMNS:
            value = kpis.get(key)
            row[csv_name] = "" if value is None else value
        meta = meta_by_case.get(case["case_id"], {})
        for name in extra_meta:
            row[name] = (meta.get(name) or "").strip()
        rows.append(row)

    dataset_path = os.path.join(data_dir, "dataset.csv")
    write_csv(dataset_path, header, rows)

    # ---------------- dataset_pid.csv (un PID per riga) ----------------
    pid_header = ["case_id"] + [csv_name for _key, csv_name in PID_COLUMNS]
    pid_rows = []
    for case in cases:
        for pid in case["pids"]:
            row = {"case_id": case["case_id"]}
            for key, csv_name in PID_COLUMNS:
                value = pid.get(key)
                row[csv_name] = "" if value is None else value
            pid_rows.append(row)
    pid_path = os.path.join(data_dir, "dataset_pid.csv")
    write_csv(pid_path, pid_header, pid_rows)

    print("Casi letti      : %d" % len(cases))
    print("dataset.csv     : %d righe x %d colonne" % (len(rows), len(header)))
    print("dataset_pid.csv : %d righe x %d colonne" % (len(pid_rows), len(pid_header)))
    if meta_header:
        print("metadata.csv    : %d colonne unite" % len(extra_meta))
    else:
        print("metadata.csv    : assente (colonne parametri non unite)")

    # anteprima: ignora i casi con numeri fisicamente impossibili (li segnala check_dataset)
    ranked = [row for row in rows
              if isinstance(row.get("deportanza_N"), (int, float))
              and abs(row["deportanza_N"]) <= 2000.0
              and isinstance(row.get("drag_N"), (int, float))
              and 0.0 < row["drag_N"] <= 1000.0]
    ranked.sort(key=lambda r: r["deportanza_N"], reverse=True)
    if ranked:
        print("\nPrime 5 per deportanza:")
        print("  %-40s %10s %10s %8s" % ("case_id", "deportanza", "drag", "|L|/D"))
        for row in ranked[:5]:
            l_d = row.get("L_D")
            print("  %-40s %10.1f %10.1f %8s" % (
                row["case_id"][:40], row["deportanza_N"], row.get("drag_N") or 0.0,
                ("%.2f" % l_d) if isinstance(l_d, (int, float)) else "n/d"))
    print("\nFile scritti in: %s" % data_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
