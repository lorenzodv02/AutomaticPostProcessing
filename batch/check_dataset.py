# -*- coding: utf-8 -*-
"""
Controlli di coerenza sul dataset estratto, PRIMA di qualsiasi analisi.

Verifica che i casi siano confrontabili: stessa velocita', stessa convenzione,
stesso assieme, stessa selezione di PID, stessa simmetria, e che la somma dei
PID torni con i KPI (come il CHK-07 del report).

Uso:
    python check_dataset.py --data "D:\\Analisi\\_dati_batch"
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from make_tables import iterations_from_name  # noqa: E402

TOLERANCE_PCT = 0.5

# Limiti di plausibilita' fisica per un caso Formula Student a ~14 m/s.
# Servono a fermare i casi con campo di pressione sbagliato (velocita' diversa,
# run divergente, file non aggiornato) che altrimenti passerebbero tutti i CHK.
MAX_ABS_DOWNFORCE_N = 2000.0
MAX_DRAG_N = 1000.0
MAX_L_OVER_D = 20.0
CP_CLIP_FLOOR = -8.0


def plausibility_issues(kpis: dict) -> list:
    """Problemi fisici evidenti nei KPI di un caso (lista di messaggi)."""
    issues = []
    downforce = kpis.get("downforce_total_N", kpis.get("downforce_N"))
    drag = kpis.get("drag_total_N", kpis.get("drag_N"))
    l_d = kpis.get("efficiency_l_d", kpis.get("efficiency_L_over_D"))
    cp_min = kpis.get("peak_suction_cp")
    stalled = kpis.get("stalled_surface_pct", kpis.get("stalled_area_percentage"))
    if isinstance(downforce, (int, float)) and abs(downforce) > MAX_ABS_DOWNFORCE_N:
        issues.append("deportanza fuori scala: %.0f N (possibile velocita' o condizioni diverse)"
                      % downforce)
    if isinstance(drag, (int, float)) and drag <= 0:
        issues.append("drag non positivo: %.1f N (campo di pressione non valido)" % drag)
    elif isinstance(drag, (int, float)) and drag > MAX_DRAG_N:
        issues.append("drag fuori scala: %.0f N" % drag)
    if isinstance(l_d, (int, float)) and abs(l_d) > MAX_L_OVER_D:
        issues.append("efficienza fuori scala: %.1f" % l_d)
    if isinstance(cp_min, (int, float)) and cp_min <= CP_CLIP_FLOOR - 1e-6:
        issues.append("Cp_min al limite di clipping (%.2f): campo fuori intervallo" % cp_min)
    if isinstance(stalled, (int, float)) and not (0.0 <= stalled <= 100.0):
        issues.append("percentuale di superficie stallata fuori range: %.1f%%" % stalled)
    return issues


def load(data_dir: str) -> list:
    cases = []
    for path in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        name = os.path.basename(path)
        if name.startswith("_"):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            cases.append({"case_id": os.path.splitext(name)[0], "error": "JSON illeggibile"})
            continue
        physics = payload.get("physics_data") or {}
        cases.append({
            "case_id": os.path.splitext(name)[0],
            "kpis": physics.get("summary_kpis") or {},
            "pids": physics.get("per_pid_breakdown") or [],
            "assembly": payload.get("assembly_type", ""),
            "config": payload.get("config") or {},
            "n_zones": len((payload.get("cas_info") or {}).get("zones") or []),
            "cas_file": os.path.basename(payload.get("cas_file") or ""),
            "iterazioni": iterations_from_name(payload.get("cas_file") or ""),
        })
    return cases


def refs_of(config: dict) -> dict:
    refs = (config or {}).get("reference_values") or {}
    return {
        "velocity_inf": refs.get("velocity_inf"),
        "density_air": refs.get("density_air"),
        "reference_area": refs.get("reference_area"),
        "pressure_inf": refs.get("pressure_inf"),
        "report_force_convention": refs.get("report_force_convention"),
    }


def manual_ids_of(config: dict, assembly: str) -> list:
    assemblies = (config or {}).get("assemblies") or {}
    profile = assemblies.get(assembly) or {}
    return list(profile.get("manual_zone_ids") or [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlli di coerenza del dataset.")
    parser.add_argument("--data", default=None, help="cartella con i JSON")
    args = parser.parse_args()

    data_dir = args.data or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_dati_batch")
    data_dir = os.path.abspath(data_dir)
    if not os.path.isdir(data_dir):
        print("ERRORE: cartella non trovata: %s" % data_dir)
        return 2

    cases = load(data_dir)
    if not cases:
        print("Nessun JSON in: %s" % data_dir)
        return 1

    problems = []
    warnings = []
    lines = []

    def out(text=""):
        print(text)
        lines.append(text)

    out("CONTROLLI DI COERENZA — %s" % data_dir)
    out("casi: %d" % len(cases))
    out("")

    broken = [c for c in cases if c.get("error")]
    if broken:
        problems.append("%d JSON illeggibili: %s" %
                        (len(broken), ", ".join(c["case_id"] for c in broken)))
    usable = [c for c in cases if not c.get("error")]

    # ---- coerenza della configurazione ----
    refs_by_case = {c["case_id"]: refs_of(c["config"]) for c in usable}
    for key in ("velocity_inf", "density_air", "reference_area", "pressure_inf",
                "report_force_convention"):
        values = Counter(str(refs.get(key)) for refs in refs_by_case.values())
        if len(values) > 1:
            detail = ", ".join("%s=%s" % (v, n) for v, n in values.most_common())
            if key == "velocity_inf":
                warnings.append("velocita' diverse tra i casi (%s): le FORZE non sono "
                                "confrontabili, usa CL*A e CD*A" % detail)
            else:
                warnings.append("%s diversi tra i casi (%s)" % (key, detail))

    assemblies = Counter(c["assembly"] for c in usable)
    if len(assemblies) > 1:
        problems.append("assiemi diversi tra i casi: %s"
                        % ", ".join("%s=%d" % (a, n) for a, n in assemblies.most_common()))

    manual = {c["case_id"]: manual_ids_of(c["config"], c["assembly"]) for c in usable}
    if any(manual.values()):
        with_manual = [cid for cid, ids in manual.items() if ids]
        warnings.append("selezione manuale dei PID presente in %d casi (es. %s): "
                        "il confronto e' valido solo se e' la stessa per tutti"
                        % (len(with_manual), with_manual[0]))

    # ---- PID e simmetria ----
    pid_counts = Counter(len(c["pids"]) for c in usable)
    out("PID per caso: %s" % ", ".join("%d PID -> %d casi" % (n, k) for n, k in pid_counts.most_common()))
    if len(pid_counts) > 1:
        mode = pid_counts.most_common(1)[0][0]
        odd = [(c["case_id"], len(c["pids"])) for c in usable if len(c["pids"]) != mode]
        warnings.append("numero di PID diverso dal caso tipico (%d) in %d casi: %s"
                        % (mode, len(odd), ", ".join("%s (%d)" % item for item in odd[:6])))

    half = Counter(bool(c["kpis"].get("is_half_car_symmetric")) for c in usable)
    if len(half) > 1:
        problems.append("simmetria half-car incoerente: %s"
                        % ", ".join("%s -> %d casi" % (k, v) for k, v in half.items()))

    # ---- KPI vs somma dei PID (come CHK-07) ----
    mismatched = []
    for case in usable:
        kpis = case["kpis"]
        pids = case["pids"]
        if not pids:
            continue
        for pid_key, kpi_key, label in (
            ("downforce_2x_N", "downforce_total_N", "deportanza"),
            ("drag_2x_N", "drag_total_N", "drag"),
        ):
            total = kpis.get(kpi_key, kpis.get(kpi_key.replace("_total", "")))
            if not isinstance(total, (int, float)):
                continue
            try:
                summed = sum(float(p.get(pid_key) or 0.0) for p in pids)
            except (TypeError, ValueError):
                continue
            if abs(total) < 1e-9:
                continue
            delta = abs(summed - total) / abs(total) * 100.0
            if delta > TOLERANCE_PCT:
                mismatched.append((case["case_id"], label, summed, total, delta))
    if mismatched:
        problems.append("somma PID diversa dal KPI in %d voci: %s"
                        % (len(mismatched), ", ".join(
                            "%s/%s %.1f%%" % (cid, label, delta)
                            for cid, label, _s, _t, delta in mismatched[:5])))

    # ---- valori sospetti ----
    empty_kpi = [c["case_id"] for c in usable
                 if not isinstance(c["kpis"].get("downforce_total_N"), (int, float))]
    if empty_kpi:
        problems.append("deportanza mancante in %d casi: %s" % (len(empty_kpi), ", ".join(empty_kpi[:5])))

    zero = [c["case_id"] for c in usable
            if isinstance(c["kpis"].get("downforce_total_N"), (int, float))
            and abs(c["kpis"]["downforce_total_N"]) < 1e-6]
    if zero:
        warnings.append("deportanza nulla in %d casi: %s" % (len(zero), ", ".join(zero[:5])))

    # ---- plausibilita' fisica ----
    suspicious = []
    for case in usable:
        for issue in plausibility_issues(case["kpis"]):
            suspicious.append((case["case_id"], issue))
    if suspicious:
        problems.append("%d casi con numeri fisicamente sospetti (guarda il log e le "
                        "condizioni della simulazione)" % len({cid for cid, _ in suspicious}))

    # ---- iterazioni di convergenza (dal nome file) ----
    iterations = [(c["case_id"], c["iterazioni"]) for c in usable if c.get("iterazioni")]
    if iterations:
        values = [value for _cid, value in iterations]
        out("")
        out("Iterazioni di convergenza (dal nome del file): min %d | max %d"
            % (min(values), max(values)))
        low = [(cid, value) for cid, value in iterations if value < 1000]
        if low:
            warnings.append("%d casi sotto 1000 iterazioni (possono non essere convergiti): %s"
                            % (len(low), ", ".join("%s (%d)" % (cid, value) for cid, value in low[:8])))
        spread = max(values) - min(values)
        if spread > 0:
            warnings.append("iterazioni diverse tra i casi (range %d): confrontare solo a "
                            "convergenza raggiunta" % spread)

    # ---- tabella riassuntiva ----
    out("")
    out("%-40s %10s %10s %8s %6s %10s" % ("case_id", "deportanza", "drag", "|L|/D", "iter", "v_inf"))
    for case in usable:
        kpis = case["kpis"]
        df = kpis.get("downforce_total_N", kpis.get("downforce_N"))
        dr = kpis.get("drag_total_N", kpis.get("drag_N"))
        l_d = kpis.get("efficiency_l_d", kpis.get("efficiency_L_over_D"))
        v = kpis.get("velocity_inf_ms")
        out("%-40s %10s %10s %8s %6s %10s" % (
            case["case_id"][:40],
            ("%.1f" % df) if isinstance(df, (int, float)) else "n/d",
            ("%.1f" % dr) if isinstance(dr, (int, float)) else "n/d",
            ("%.2f" % l_d) if isinstance(l_d, (int, float)) else "n/d",
            str(case.get("iterazioni") or "-"),
            ("%.1f" % v) if isinstance(v, (int, float)) else "n/d"))

    if suspicious:
        out("")
        out("CASI SOSPETTI:")
        for case_id, issue in suspicious:
            out("  [X] %-24s %s" % (case_id, issue))

    out("")
    if problems:
        out("PROBLEMI (%d):" % len(problems))
        for item in problems:
            out("  [X] %s" % item)
    if warnings:
        out("ATTENZIONI (%d):" % len(warnings))
        for item in warnings:
            out("  [!] %s" % item)
    if not problems and not warnings:
        out("Tutto coerente: i casi sono confrontabili.")
    elif not problems:
        out("Nessun problema bloccante: si puo' procedere, ma leggi le attenzioni.")

    report_path = os.path.join(data_dir, "_controlli.txt")
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print("\nRapporto salvato: %s" % report_path)
    return 0 if not problems else 4


if __name__ == "__main__":
    raise SystemExit(main())
