# -*- coding: utf-8 -*-
"""
Aero Suite — un processo, un report.

Stadi:
    geometry   estrae la geometria del fondo da ogni .cas (FS-MetaPostDiag --geometry-only)
    tables     costruisce dataset_geom.csv e le correlazioni geometria-prestazioni
    dashboard  genera UN SOLO file brandizzato: Aero_Suite.html
               (panoramica, confronto zone, sintesi, geometria, metodo)

Solo libreria standard. Uso:
    python aero_suite.py --data "D:\\Analisi\\_dati_batch"
    python aero_suite.py --data "..." --stage geometry --force
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys
from datetime import datetime

EXCLUSIONS_FILE = "escludi.txt"
GEOM_DIR = "geom"
SUITE_HTML = "Aero_Suite.html"
GEOM_CSV = "dataset_geom.csv"
TEMPLATE_NAME = "suite_template.html"

HERE = os.path.dirname(os.path.abspath(__file__))


def _tools_dir(tools_dir=None) -> str:
    if tools_dir:
        return os.path.abspath(tools_dir)
    for candidate in (os.path.join(HERE, "..", "tools"), os.path.join(HERE, "tools")):
        if os.path.isdir(candidate):
            return os.path.abspath(candidate)
    return os.path.abspath(os.path.join(HERE, "..", "tools"))


def _import_tools(tools_dir):
    path = _tools_dir(tools_dir)
    if path not in sys.path:
        sys.path.insert(0, path)
    import design_explorer  # noqa: WPS433
    import recombination  # noqa: WPS433
    return design_explorer, recombination


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
    rows = list(csv.DictReader(open(os.path.join(data_dir, "dataset.csv"),
                                    encoding="utf-8-sig", newline=""), delimiter=";"))
    cases = []
    for row in rows:
        if row["case_id"] in excluded:
            continue
        cases.append({
            "id": row["case_id"],
            "dep": to_float(row.get("deportanza_N")),
            "drag": to_float(row.get("drag_N")),
            "ld": to_float(row.get("L_D")),
            "cop": to_float(row.get("cop_x_pct")),
            "iter": row.get("iterazioni") or "",
            "wing": row.get("ala_post") or "",
            "diff": row.get("diffusore") or "",
            "cas_file": row.get("cas_file") or "",
        })
    cases.sort(key=lambda c: -(c["dep"] or 0))
    return cases


def case_json(data_dir, case_id):
    path = os.path.join(data_dir, case_id + ".json")
    if not os.path.isfile(path):
        return {}
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def case_directory(data_dir, case):
    payload = case_json(data_dir, case["id"])
    cas = payload.get("cas_file") or ""
    if cas and os.path.isfile(cas):
        return os.path.dirname(cas)
    return None


# ---------------------------------------------------------------------- stadi
def stage_geometry(data_dir, exe, cases_root=None, force=False, timeout=900):
    cases = load_cases(data_dir)
    geom_dir = os.path.join(data_dir, GEOM_DIR)
    os.makedirs(geom_dir, exist_ok=True)
    done = skipped = failed = 0
    for case in cases:
        target = os.path.join(geom_dir, case["id"] + ".json")
        if os.path.isfile(target) and not force:
            skipped += 1
            continue
        directory = case_directory(data_dir, case)
        if directory is None and cases_root:
            candidate = os.path.join(cases_root, case["id"])
            if os.path.isdir(candidate):
                directory = candidate
        if directory is None:
            print("  %-24s cartella del caso non trovata (usa --cases-root)" % case["id"])
            failed += 1
            continue
        try:
            result = subprocess.run([exe, "--geometry-only", "-w", directory],
                                    capture_output=True, text=True, errors="replace",
                                    timeout=timeout)
            output = (result.stdout or "") + (result.stderr or "")
        except (OSError, subprocess.TimeoutExpired) as exc:
            print("  %-24s errore: %s" % (case["id"], exc))
            failed += 1
            continue
        produced = os.path.join(directory, "output_diagnostics", "geometry.json")
        if not os.path.isfile(produced):
            print("  %-24s nessuna geometria prodotta" % case["id"])
            for line in output.splitlines()[-3:]:
                print("        " + line.strip())
            failed += 1
            continue
        payload = json.load(open(produced, encoding="utf-8"))
        payload["dep"] = case["dep"]
        payload["drag"] = case["drag"]
        payload["ld"] = case["ld"]
        payload["wing"] = case["wing"]
        payload["diff"] = case["diff"]
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
        try:
            os.remove(produced)
            os.rmdir(os.path.dirname(produced))
        except OSError:
            pass
        summary = payload.get("summary") or {}
        print("  %-24s minima %5.1f mm · %s %5.1f deg · espansione %.2f"
              % (case["id"], (summary.get("throat_h_m") or 0.0) * 1000.0,
                 summary.get("rise_kind") or "-", summary.get("rise_angle_deg") or 0.0,
                 summary.get("expansion_ratio") or 0.0))
        done += 1
    print("geometria: %d nuovi, %d gia' presenti, %d errori" % (done, skipped, failed))
    return done + skipped, failed


def pearson(x, y):
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    if len(pairs) < 4:
        return None
    xs = [a for a, _b in pairs]
    ys = [b for _a, b in pairs]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((a - mx) * (b - my) for a, b in pairs)
    return sxy / math.sqrt(sxx * syy)


GEOM_METRICS = [
    ("throat_h_m", "Altezza minima", "mm", 1000.0),
    ("throat_pct", "Posizione minima", "%", 1.0),
    ("rise_angle_deg", "Angolo salita", "deg", 1.0),
    ("rise_length_m", "Lunghezza salita", "mm", 1000.0),
    ("expansion_ratio", "Espansione", "x", 1.0),
    ("plan_area_m2", "Area in pianta", "m2", 1.0),
    ("floor_area_m2", "Area superficie fondo", "m2", 1.0),
]


def load_geometries(data_dir, cases):
    out = {}
    for case in cases:
        path = os.path.join(data_dir, GEOM_DIR, case["id"] + ".json")
        if not os.path.isfile(path):
            continue
        try:
            payload = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out[case["id"]] = {"payload": payload,
                           "geometry": payload.get("geometry") or {},
                           "summary": payload.get("summary") or {}}
    return out


def geometry_tables(cases, geometries):
    rows, correlations = [], []
    for case in cases:
        entry = geometries.get(case["id"])
        if not entry:
            continue
        summary = entry["summary"]
        rows.append({
            "case_id": case["id"], "dep": case["dep"], "drag": case["drag"], "ld": case["ld"],
            "throat_mm": (summary.get("throat_h_m") or 0.0) * 1000.0 if summary.get("throat_h_m") is not None else None,
            "rise_angle": summary.get("rise_angle_deg"),
            "rise_length": summary.get("rise_length_m"),
            "expansion": summary.get("expansion_ratio"),
            "floor_area": summary.get("floor_area_m2"),
            "plan_area": summary.get("plan_area_m2"),
            "kind": summary.get("rise_kind"),
        })
    for target, label in (("dep", "deportanza"), ("drag", "resistenza"), ("ld", "L/D")):
        for key, name, _unit, _scale in GEOM_METRICS:
            xs = [geometries[c["id"]]["summary"].get(key) for c in cases if c["id"] in geometries]
            ys = [c[target] for c in cases if c["id"] in geometries]
            value = pearson(xs, ys)
            if value is not None:
                correlations.append({"target": label, "metric": name,
                                     "r": round(value, 2), "n": len(xs)})
    correlations.sort(key=lambda item: -abs(item["r"]))
    return rows, correlations


def stage_tables(data_dir):
    cases = load_cases(data_dir)
    geometries = load_geometries(data_dir, cases)
    rows, correlations = geometry_tables(cases, geometries)
    header = ["case_id", "dep_N", "drag_N", "L_D", "wing", "diff"] + \
             [name for _key, name, _unit, _scale in GEOM_METRICS]
    out_rows = []
    for row in rows:
        case = next((c for c in cases if c["id"] == row["case_id"]), {})
        item = {"case_id": row["case_id"], "dep_N": row["dep"], "drag_N": row["drag"],
                "L_D": row["ld"], "wing": case.get("wing", ""), "diff": case.get("diff", "")}
        for key, name, _unit, scale in GEOM_METRICS:
            value = geometries[row["case_id"]]["summary"].get(key)
            item[name] = round(value * scale, 2) if isinstance(value, (int, float)) else ""
        out_rows.append(item)
    path = os.path.join(data_dir, GEOM_CSV)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, delimiter=";")
        writer.writeheader()
        writer.writerows(out_rows)
    print("tabelle: %d casi con geometria -> %s" % (len(out_rows), os.path.basename(path)))
    for item in correlations[:5]:
        print("  %-16s vs %-20s r = %+.2f (n=%d)"
              % (item["target"], item["metric"], item["r"], item["n"]))
    return rows, correlations


# ------------------------------------------------------------------- payload
def _noise_from_duplicates(cases):
    """Rumore: differenza fra casi con lo stesso .cas (run doppie)."""
    by_file = {}
    for case in cases:
        key = (case.get("cas_file") or "").lower()
        if key:
            by_file.setdefault(key, []).append(case)
    deltas = []
    for group in by_file.values():
        if len(group) >= 2:
            deltas.append(abs((group[1]["dep"] or 0.0) - (group[0]["dep"] or 0.0)))
    return round(sum(deltas) / len(deltas), 2) if deltas else 1.0, len(deltas)


def _model_verdict(model, noise):
    if not model.get("available"):
        return "Modello non disponibile: %s." % (model.get("reason") or "dati insufficienti")
    result = model["targets"]["dep"]
    ratio = result["rmse"] / max(noise, 1e-9)
    if ratio < 3:
        return "Errore leave-one-out %.1f N (%.1f× il rumore): il modello sa prevedere la deportanza." % (
            result["rmse"], ratio)
    if ratio < 10:
        return "Errore leave-one-out %.1f N (%.1f× il rumore): prevede la tendenza, non il singolo caso." % (
            result["rmse"], ratio)
    return ("Errore leave-one-out %.1f N (%.0f× il rumore): i dati sostengono il confronto, "
            "non la previsione. La prossima prova deve riempire i vuoti." % (result["rmse"], ratio))


def build_dashboard_payload(data_dir, tools_dir=None):
    """Un payload unico: casi, zone, modello, sintesi, geometria."""
    dx, reco = _import_tools(tools_dir)
    explorer = dx.build_payload(data_dir)
    raw_cases = explorer["cases"]
    noise = explorer.get("noise_n", 1.0)
    model = explorer.get("model") or {"available": False, "reason": "modello assente"}
    proposals = explorer.get("proposals") or []
    coverage = explorer.get("coverage") or {}
    try:
        synthesis = reco.build_payload(data_dir)
        synthesis["available"] = bool(synthesis.get("rows"))
        if not synthesis["available"]:
            synthesis["reason"] = "nessuna zona con un donatore migliore"
    except (SystemExit, Exception) as exc:  # noqa: BLE001
        synthesis = {"available": False, "reason": str(exc) or "dati insufficienti"}

    geometries = load_geometries(data_dir, load_cases(data_dir))
    geom_rows, correlations = geometry_tables(
        [{"id": c["id"], "dep": c["dep"], "drag": c["drag"], "ld": c["ld"]} for c in raw_cases],
        geometries)
    profiles = []
    for case in raw_cases:
        entry = geometries.get(case["id"])
        if not entry:
            continue
        geometry = entry["geometry"]
        if not geometry.get("available") or not geometry.get("x_m"):
            continue
        profiles.append({"case": case["id"], "x": geometry.get("x_m"),
                         "h": geometry.get("h_min_m"), "summary": entry["summary"]})
    geometry_block = {"available": bool(profiles), "profiles": profiles,
                      "rows": geom_rows, "correlations": correlations}
    cases = [{"id": c["id"], "dep": c["dep"], "drag": c["drag"], "ld": c["ld"],
              "cop": c.get("cop"), "iter": c.get("iter") or "", "wing": c.get("wing") or "",
              "diff": c.get("diff") or ""} for c in raw_cases]
    best = max((c for c in raw_cases if c["dep"] is not None), key=lambda c: c["dep"], default=None)
    best_ld = max((c for c in raw_cases if c["ld"] is not None), key=lambda c: c["ld"], default=None)
    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "noise_n": noise,
        "excluded": explorer.get("excluded") or sorted(load_exclusions(data_dir)),
        "counts": {"cases": len(cases), "geom": len(profiles),
                   "zones": len({zone for mapping in explorer.get("zones", {}).values()
                                 for zone in mapping})},
        "cases": cases,
        "zones": explorer.get("zones") or {},
        "kpis": {"best_dep": {"id": best["id"], "dep": best["dep"]} if best else None,
                 "best_ld": {"id": best_ld["id"], "ld": best_ld["ld"]} if best_ld else None},
        "model": {"available": model.get("available", False),
                  "reason": model.get("reason"),
                  "targets": model.get("targets", {}),
                  "coefficients": model.get("coefficients", []),
                  "verdict": _model_verdict(model, noise)},
        "proposals": proposals,
        "coverage": coverage,
        "synthesis": synthesis,
        "geometry": geometry_block,
    }


def render_dashboard(payload, template_path, brand=None):
    """Inserisce brand e dati nel template unico del dashboard."""
    if brand is None:
        import brand_theme as brand  # noqa: WPS433
    template = open(template_path, "r", encoding="utf-8").read()
    chips = [
        ("casi", payload["counts"]["cases"]),
        ("geometrie", payload["counts"]["geom"]),
        ("rumore", "±%.2f N" % payload["noise_n"]),
    ]
    if payload["kpis"]["best_dep"]:
        chips.append(("migliore", "%s · %.1f N" % (payload["kpis"]["best_dep"]["id"],
                                                   payload["kpis"]["best_dep"]["dep"])))
    header = brand.header_html(
        title='Aero Suite',
        subtitle=("Dal .cas al progetto in un processo: forze per zona, geometria del fondo dalla mesh, "
                  "confronto e sintesi della vettura. Un solo report, sempre lo stesso."),
        chips=chips,
    )
    footer = brand.footer_html(payload["generated"])
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    html = template
    for token, value in (("__FONT_FACES__", brand.font_faces()),
                         ("__BRAND_VARS__", brand.css_vars()),
                         ("__HEADER__", header),
                         ("__FOOTER__", footer),
                         ("__PAYLOAD__", data)):
        html = html.replace(token, value)
    return html


def stage_dashboard(data_dir, tools_dir=None):
    if not os.path.isfile(os.path.join(data_dir, "dataset.csv")):
        print("ERRORE: dataset.csv assente nella cartella dati.")
        return None
    payload = build_dashboard_payload(data_dir, tools_dir)
    template = os.path.join(HERE, TEMPLATE_NAME)
    html = render_dashboard(payload, template)
    path = os.path.join(data_dir, SUITE_HTML)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html)
    print("dashboard: %s (%.1f KB) · casi %d · geometrie %d"
          % (path, os.path.getsize(path) / 1024.0,
             payload["counts"]["cases"], payload["counts"]["geom"]))
    return path


# ------------------------------------------------------------------------ CLI
def main():
    parser = argparse.ArgumentParser(description="Aero Suite: un processo, un report.")
    parser.add_argument("--data", required=True, help="cartella _dati_batch")
    parser.add_argument("--stage", default="all",
                        choices=["geometry", "tables", "dashboard", "all"])
    parser.add_argument("--exe", default=None, help="FS-MetaPostDiag.exe per la geometria")
    parser.add_argument("--cases-root", default=None,
                        help="cartella con le sottocartelle dei casi (se i percorsi salvati non esistono)")
    parser.add_argument("--tools", default=None, help="cartella con design_explorer.py e recombination.py")
    parser.add_argument("--force", action="store_true", help="rifai la geometria anche se presente")
    args = parser.parse_args()

    data_dir = os.path.abspath(args.data)
    if not os.path.isdir(data_dir):
        print("ERRORE: cartella non trovata: %s" % data_dir)
        return 2
    exe = os.path.abspath(args.exe) if args.exe else os.path.join(HERE, "FS-MetaPostDiag.exe")
    if not os.path.isfile(exe):
        parent = os.path.join(os.path.dirname(HERE), "FS-MetaPostDiag.exe")
        if os.path.isfile(parent):
            exe = parent

    print("Aero Suite — dati: %s" % data_dir)
    failures = 0
    if args.stage in ("geometry", "all"):
        print("\n[1/3] geometria dalla mesh")
        if not os.path.isfile(exe):
            print("  eseguibile non trovato: %s" % exe)
            failures += 1
        else:
            _total, failed = stage_geometry(data_dir, exe, args.cases_root, args.force)
            failures += failed
    if args.stage in ("tables", "all"):
        print("\n[2/3] tabelle")
        stage_tables(data_dir)
    if args.stage in ("dashboard", "all"):
        print("\n[3/3] dashboard")
        stage_dashboard(data_dir, args.tools)
    print("\nFatto. Apri: %s" % os.path.join(data_dir, SUITE_HTML))
    return 0 if failures == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
