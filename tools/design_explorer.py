# -*- coding: utf-8 -*-
"""
Aero Design Explorer — costruisce un report interattivo autonomo dal dataset
estratto con il batch (solo libreria standard di Python).

Contenuto del report:
  * mappa dei modelli (deportanza vs resistenza) con frontiera di Pareto;
  * tabella ordinabile dei casi;
  * confronto per zona tra due casi (dove si guadagna e dove si perde);
  * verifica onesta di cosa i dati permettono (modello lineare con leave-one-out);
  * copertura dei parametri e proposte di prossime simulazioni.

Uso:
    python design_explorer.py --data "D:\\Analisi\\_dati_batch" --out explorer.html
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
from datetime import datetime

EXCLUSIONS_FILE = "escludi.txt"
TEMPLATE_NAME = "explorer_template.html"

NUMERIC_PARAMS = [
    ("maxh", "Altezza max", "mm"),
    ("gola", "Altezza gola", "mm"),
    ("pos", "Posizione gola", "mm"),
]
CATEGORICAL_PARAMS = [
    ("ala_post", "Ala posteriore", "wing"),
    ("diffusore", "Diffusore", "diff"),
]

# Variabili binarie del modello: separano i due grandi gruppi di configurazione.
BINARY_FEATURES = [
    ("ala RW1", lambda case: (case.get("wing") or "").startswith("RW1")),
    ("diffusore completo", lambda case: (case.get("diff") or "").startswith("Completo")),
]


# --------------------------------------------------------------------------- dati
def load_exclusions(data_dir):
    path = os.path.join(data_dir, EXCLUSIONS_FILE)
    if not os.path.isfile(path):
        return set()
    out = set()
    for line in open(path, encoding="utf-8-sig"):
        name = line.split("#", 1)[0].strip()
        if name:
            out.add(name)
    return out


def to_float(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def load_cases(data_dir):
    excluded = load_exclusions(data_dir)
    path = os.path.join(data_dir, "dataset.csv")
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig", newline=""), delimiter=";"))
    cases = []
    for row in rows:
        if row["case_id"] in excluded:
            continue
        cases.append({
            "id": row["case_id"],
            "dep": to_float(row.get("deportanza_N")),
            "drag": to_float(row.get("drag_N")),
            "ld": to_float(row.get("L_D")),
            "cl_a": to_float(row.get("CL_A")),
            "cd_a": to_float(row.get("CD_A")),
            "cop": to_float(row.get("cop_x_pct")),
            "iter": row.get("iterazioni") or "",
            "cas": row.get("cas_file") or "",
            "modello": row.get("modello") or "",
            "nota": row.get("nota") or "",
            "wing": row.get("ala_post") or "",
            "ant": row.get("ala_ant") or "",
            "diff": row.get("diffusore") or "",
            "maxh": to_float(row.get("max_height_mm")),
            "gola": to_float(row.get("height_gola_mm")),
            "pos": to_float(row.get("pos_gola_mm")),
            "excel_dep": to_float(row.get("excel_downforce_N")),
            "excel_drag": to_float(row.get("excel_drag_N")),
        })
    cases.sort(key=lambda c: -(c["dep"] or 0))
    return cases


def load_zones(data_dir):
    excluded = load_exclusions(data_dir)
    path = os.path.join(data_dir, "dataset_pid.csv")
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig", newline=""), delimiter=";"))
    matrix = {}
    for row in rows:
        if row["case_id"] in excluded:
            continue
        value = to_float(row.get("df_2x_N"))
        if value is None:
            continue
        matrix.setdefault(row["case_id"], {})[row["zone_name"]] = round(value, 2)
    return matrix


# --------------------------------------------------------------- matematica
def mean(values):
    return sum(values) / float(len(values)) if values else 0.0


def stdev(values):
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / float(len(values) - 1))


def solve_linear(matrix, vector):
    """Gauss con pivoting parziale: sistema quadrato piccolo (6x6)."""
    n = len(vector)
    a = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return [0.0] * n
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]
        for row in range(col + 1, n):
            factor = a[row][col] / a[col][col]
            for k in range(col, n + 1):
                a[row][k] -= factor * a[col][k]
    solution = [0.0] * n
    for row in range(n - 1, -1, -1):
        total = a[row][n] - sum(a[row][k] * solution[k] for k in range(row + 1, n))
        solution[row] = total / a[row][row]
    return solution


def design_matrix(cases, numerics, binaries):
    rows, labels, used = [], [], []
    for case in cases:
        values = []
        ok = True
        for key in numerics:
            value = case.get(key)
            if value is None:
                ok = False
                break
            values.append(float(value))
        if not ok:
            continue
        for _name, predicate in binaries:
            values.append(1.0 if predicate(case) else 0.0)
        rows.append(values)
        labels.append(case["id"])
        used.append(case)
    return rows, labels, used


def ridge_fit(rows, y, lam=1.0):
    n = len(rows[0]) + 1
    ata = [[0.0] * n for _ in range(n)]
    aty = [0.0] * n
    for i, row in enumerate(rows):
        extended = [1.0] + row
        for j in range(n):
            aty[j] += extended[j] * y[i]
            for k in range(n):
                ata[j][k] += extended[j] * extended[k]
    for j in range(1, n):
        ata[j][j] += lam
    return solve_linear(ata, aty)


def ridge_predict(coef, row):
    return coef[0] + sum(coef[i + 1] * value for i, value in enumerate(row))


def loo_validate(rows, y, lam=1.0):
    predictions = []
    for i in range(len(y)):
        train_rows = [row for j, row in enumerate(rows) if j != i]
        train_y = [value for j, value in enumerate(y) if j != i]
        coef = ridge_fit(train_rows, train_y, lam)
        predictions.append(ridge_predict(coef, rows[i]))
    residuals = [predictions[i] - y[i] for i in range(len(y))]
    rmse = math.sqrt(sum(r * r for r in residuals) / len(residuals))
    avg = mean(y)
    ss_tot = sum((v - avg) ** 2 for v in y)
    ss_res = sum(r * r for r in residuals)
    return {
        "rmse": rmse,
        "r2": (1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan"),
        "max_abs": max(abs(r) for r in residuals),
        "pred": [round(v, 2) for v in predictions],
        "resid": [round(v, 2) for v in residuals],
    }


def fit_report(cases):
    numeric_keys = [key for key, _label, _unit in NUMERIC_PARAMS]
    rows, labels, used = design_matrix(cases, numeric_keys, BINARY_FEATURES)
    if len(labels) < 8:
        return {"available": False,
                "reason": "servono almeno 8 casi con metadati (trovati %d)" % len(labels)}
    means = [mean([row[i] for row in rows]) for i in range(len(numeric_keys))]
    stds = [stdev([row[i] for row in rows]) for i in range(len(numeric_keys))]
    stds = [value if value > 0 else 1.0 for value in stds]
    scaled = []
    for row in rows:
        new_row = [(row[i] - means[i]) / stds[i] for i in range(len(numeric_keys))]
        new_row.extend(row[len(numeric_keys):])
        scaled.append(new_row)

    report = {"available": True, "labels": labels, "means": means, "stds": stds,
              "targets": {}, "coefficients": []}
    # la regolarizzazione si sceglie con lo stesso leave-one-out: fra i valori
    # provati vince quello con l'errore minore (evita di sovra-adattare i 15 casi)
    lambdas = (0.01, 0.1, 0.3, 1.0, 3.0, 10.0)
    best_lambda = {}
    for target in ("dep", "drag", "ld"):
        y = [case[target] for case in used]
        best = None
        for lam in lambdas:
            result = loo_validate(scaled, y, lam)
            if best is None or result["rmse"] < best[1]["rmse"]:
                best = (lam, result)
        best_lambda[target] = best[0]
        result = dict(best[1])
        result["lambda"] = best[0]
        report["targets"][target] = result

    y_dep = [case["dep"] for case in used]
    coef = ridge_fit(scaled, y_dep, best_lambda["dep"])
    names = [label for _key, label, _unit in NUMERIC_PARAMS] + \
            [name for name, _predicate in BINARY_FEATURES]
    report["coefficients"] = [{"name": name, "value": round(value, 1)}
                              for name, value in zip(names, coef[1:])]
    return report


def propose_next(cases, count=5, seed=7):
    """Combinazioni mai provate, scelte per riempire i vuoti dello spazio."""
    labeled = [c for c in cases
               if c["maxh"] is not None and c["gola"] is not None and c["pos"] is not None]
    if len(labeled) < 5:
        return []
    values = [[c["maxh"], c["gola"], c["pos"]] for c in labeled]
    means = [mean([row[i] for row in values]) for i in range(3)]
    stds = [stdev([row[i] for row in values]) for i in range(3)]
    stds = [value if value > 0 else 1.0 for value in stds]
    scaled = [[(row[i] - means[i]) / stds[i] for i in range(3)] for row in values]
    wings = sorted({c["wing"] for c in labeled if c["wing"]}) or ["RW1"]
    diffs = sorted({c["diff"] for c in labeled if c["diff"]}) or ["Completo"]
    low = [min(row[i] for row in values) for i in range(3)]
    high = [max(row[i] for row in values) for i in range(3)]
    rng = random.Random(seed)
    candidates = []
    for _ in range(6000):
        point = [rng.uniform(low[i], high[i]) for i in range(3)]
        wing = rng.choice(wings)
        diff = rng.choice(diffs)
        scaled_point = [(point[i] - means[i]) / stds[i] for i in range(3)]
        distance = min(
            math.sqrt(sum((scaled_point[i] - row[i]) ** 2 for i in range(3)))
            for row in scaled
        )
        candidates.append((distance, point, wing, diff))
    candidates.sort(key=lambda item: -item[0])
    chosen = []
    for distance, point, wing, diff in candidates:
        if len(chosen) >= count:
            break
        if any(abs(point[i] - other[1][i]) < 0.08 * (high[i] - low[i])
               for i in range(3) for other in chosen):
            continue
        chosen.append((distance, point, wing, diff))
    return [{
        "max_h": round(point[0], 1), "gola": round(point[1], 1), "pos": round(point[2], 1),
        "wing": wing, "diff": diff, "distance": round(distance, 2),
    } for distance, point, wing, diff in chosen]


def coverage(cases):
    labeled = [c for c in cases if c["maxh"] is not None]
    out = {}
    for key, label, unit in NUMERIC_PARAMS:
        out[key] = {"label": label, "unit": unit,
                    "values": sorted({c[key] for c in labeled if c.get(key) is not None})}
    for key, label, case_key in CATEGORICAL_PARAMS:
        counts = {}
        for case in cases:
            value = case.get(case_key) or "(non indicato)"
            counts[value] = counts.get(value, 0) + 1
        out[key] = {"label": label, "counts": counts}
    return out


def build_payload(data_dir):
    cases = load_cases(data_dir)
    zones = load_zones(data_dir)
    duplicates = [("V10__1", "V10__2"), ("D8", "D8__2")]
    deltas = []
    for left, right in duplicates:
        a = next((c for c in cases if c["id"] == left), None)
        b = next((c for c in cases if c["id"] == right), None)
        if a and b and a["dep"] is not None and b["dep"] is not None:
            deltas.append(abs(b["dep"] - a["dep"]))
    noise = round(mean(deltas), 2) if deltas else 1.0
    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "noise_n": noise,
        "cases": cases,
        "zones": zones,
        "coverage": coverage(cases),
        "model": fit_report(cases),
        "proposals": propose_next(cases),
        "excluded": sorted(load_exclusions(data_dir)),
        "counts": {
            "cases": len(cases),
            "labeled": sum(1 for c in cases if c["maxh"] is not None),
            "zones": len({z for mapping in zones.values() for z in mapping}),
        },
    }


# --------------------------------------------------------------------- HTML
def render(payload, template_path):
    with open(template_path, "r", encoding="utf-8") as handle:
        template = handle.read()
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return template.replace("__PAYLOAD__", data)


def main():
    parser = argparse.ArgumentParser(description="Genera l'Aero Design Explorer dal dataset.")
    parser.add_argument("--data", required=True, help="cartella con dataset.csv e dataset_pid.csv")
    parser.add_argument("--out", default=None, help="file HTML di uscita")
    parser.add_argument("--template", default=None, help="template HTML")
    args = parser.parse_args()

    data_dir = os.path.abspath(args.data)
    out_path = os.path.abspath(args.out or os.path.join(data_dir, "Aero_Design_Explorer.html"))
    template = args.template or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             TEMPLATE_NAME)
    payload = build_payload(data_dir)
    html = render(payload, template)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(html)
    print("casi: %d | etichettati: %d | zone: %d | rumore: %.2f N"
          % (payload["counts"]["cases"], payload["counts"]["labeled"],
             payload["counts"]["zones"], payload["noise_n"]))
    model = payload["model"]
    if model.get("available"):
        for target in ("dep", "drag", "ld"):
            result = model["targets"][target]
            print("  %-5s leave-one-out: RMSE %6.2f | R2 %5.2f" % (target, result["rmse"], result["r2"]))
    else:
        print("  modello non disponibile:", model.get("reason"))
    print("proposte:", len(payload["proposals"]))
    print("HTML scritto:", out_path, "(%.1f KB)" % (os.path.getsize(out_path) / 1024.0))


if __name__ == "__main__":
    raise SystemExit(main())
