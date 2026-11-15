# -*- coding: utf-8 -*-
"""
Aero Suite — un solo comando per: geometria dalla mesh, tabelle, Explorer,
Recombination e una pagina indice che collega tutto.

Stadi:
    geometry   estrae la geometria del fondo da ogni .cas (usa FS-MetaPostDiag --geometry-only)
    tables     costruisce dataset_geom.csv e calcola le correlazioni geometria-prestazioni
    reports    genera Aero_Design_Explorer.html, Aero_Recombination.html e Aero_Suite.html

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
import shutil
import subprocess
import sys
from datetime import datetime

EXCLUSIONS_FILE = "escludi.txt"
GEOM_DIR = "geom"
SUITE_HTML = "Aero_Suite.html"
GEOM_CSV = "dataset_geom.csv"


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
            "wing": row.get("ala_post") or "",
            "diff": row.get("diffusore") or "",
            "cas_file": row.get("cas_file") or "",
        })
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
    """Estrae la geometria del fondo per ogni caso con l'eseguibile."""
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
        command = [exe, "--geometry-only", "-w", directory]
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    errors="replace", timeout=timeout)
            output = (result.stdout or "") + (result.stderr or "")
        except (OSError, subprocess.TimeoutExpired) as exc:
            print("  %-24s errore: %s" % (case["id"], exc))
            failed += 1
            continue
        produced = os.path.join(directory, "output_diagnostics", "geometry.json")
        if not os.path.isfile(produced):
            print("  %-24s nessuna geometria prodotta" % case["id"])
            for line in output.splitlines()[-4:]:
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
        geometry = payload.get("geometry") or {}
        summary = payload.get("summary") or {}
        out[case["id"]] = {"payload": payload, "geometry": geometry, "summary": summary}
    return out


def stage_tables(data_dir, quiet=False):
    cases = load_cases(data_dir)
    geometries = load_geometries(data_dir, cases)
    header = ["case_id", "dep_N", "drag_N", "L_D", "wing", "diff"] + \
             [name for _key, name, _unit, _scale in GEOM_METRICS]
    rows = []
    for case in cases:
        entry = geometries.get(case["id"])
        if not entry:
            continue
        row = {"case_id": case["id"], "dep_N": case["dep"], "drag_N": case["drag"],
               "L_D": case["ld"], "wing": case["wing"], "diff": case["diff"]}
        for key, name, _unit, scale in GEOM_METRICS:
            value = entry["summary"].get(key)
            row[name] = round(value * scale, 2) if isinstance(value, (int, float)) else ""
        rows.append(row)
    path = os.path.join(data_dir, GEOM_CSV)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    correlations = []
    for target, label in (("dep", "deportanza"), ("drag", "resistenza"), ("ld", "L/D")):
        for key, name, _unit, _scale in GEOM_METRICS:
            xs = [geometries[c["id"]]["summary"].get(key) for c in cases if c["id"] in geometries]
            ys = [c[target] for c in cases if c["id"] in geometries]
            value = pearson(xs, ys)
            if value is not None:
                correlations.append({"target": label, "metric": name,
                                     "r": round(value, 2), "n": len(xs)})
    correlations.sort(key=lambda item: -abs(item["r"]))
    if not quiet:
        print("tabelle: %d casi con geometria -> %s" % (len(rows), os.path.basename(path)))
        for item in correlations[:5]:
            print("  %-16s vs %-20s r = %+.2f (n=%d)"
                  % (item["target"], item["metric"], item["r"], item["n"]))
    return rows, correlations


# --------------------------------------------------------------------- pagina
def svg_profiles(geometries, cases, width=1180, height=240, columns=4):
    available = [c["id"] for c in cases if c["id"] in geometries]
    if not available:
        return "<p class='note'>Nessuna geometria disponibile: esegui lo stadio geometry.</p>"
    xs_all, hs_all = [], []
    for case_id in available:
        geometry = geometries[case_id]["geometry"]
        xs_all.extend(geometry.get("x_m") or [])
        hs_all.extend(geometry.get("h_min_m") or [])
    if not xs_all:
        return "<p class='note'>Profili non disponibili.</p>"
    xmin, xmax = min(xs_all), max(xs_all)
    ymax = max(hs_all) * 1000.0 or 1.0
    rows = int(math.ceil(len(available) / float(columns)))
    cell_w = width / float(columns)
    cell_h = height / float(max(rows, 1))
    pad = 18
    parts = ['<svg viewBox="0 0 %d %d" width="100%%">' % (width, cell_h * rows + 10)]
    for index, case_id in enumerate(available):
        geometry = geometries[case_id]["geometry"]
        xs = geometry.get("x_m") or []
        hs = geometry.get("h_min_m") or []
        if len(xs) < 2:
            continue
        col = index % columns
        row = index // columns
        ox = col * cell_w + pad
        oy = row * cell_h + pad
        inner_w = cell_w - 2 * pad
        inner_h = cell_h - 2 * pad - 14
        points = []
        for x, h in zip(xs, hs):
            px = ox + (x - xmin) / max(xmax - xmin, 1e-9) * inner_w
            py = oy + inner_h - (h * 1000.0 / ymax) * inner_h
            points.append("%.1f,%.1f" % (px, py))
        summary = geometries[case_id]["summary"]
        minimum = (summary.get("throat_h_m") or 0.0) * 1000.0
        angle = summary.get("rise_angle_deg")
        parts.append('<polyline fill="none" stroke="#38bdf8" stroke-width="1.6" points="%s"/>'
                     % " ".join(points))
        parts.append('<text x="%.1f" y="%.1f" fill="#8fa8b8" font-family="monospace" '
                     'font-size="10">%s</text>' % (ox, oy + inner_h + 13, case_id))
        parts.append('<text x="%.1f" y="%.1f" fill="#e8f1f7" font-family="monospace" '
                     'font-size="10" text-anchor="end">min %.0f mm%s</text>'
                     % (ox + inner_w, oy + inner_h + 13, minimum,
                        (" · %+.0f°" % angle) if isinstance(angle, (int, float)) else ""))
    parts.append("</svg>")
    return "".join(parts)


def render_suite_html(data_dir, cases, geometries, rows, correlations):
    best = max((c for c in cases if c["dep"] is not None), key=lambda c: c["dep"], default=None)
    best_ld = max((c for c in cases if c["ld"] is not None), key=lambda c: c["ld"], default=None)
    counts = {"cases": len(cases), "geom": len(geometries)}
    cards = [
        ("Casi nel dataset", str(counts["cases"]), "dopo esclusioni"),
        ("Con geometria", str(counts["geom"]), "dalla mesh del .cas"),
        ("Migliore deportanza", ("%s · %.1f N" % (best["id"], best["dep"])) if best else "n/d", ""),
        ("Miglior L/D", ("%s · %.2f" % (best_ld["id"], best_ld["ld"])) if best_ld else "n/d", ""),
    ]
    card_html = "".join(
        '<div class="card"><div class="label">%s</div><div class="value">%s</div>'
        '<div class="note">%s</div></div>' % item for item in cards)

    corr_rows = "".join(
        "<tr><td>%s</td><td>%s</td><td class='mono'>%+.2f</td><td class='mono'>%d</td></tr>"
        % (item["target"], item["metric"], item["r"], item["n"]) for item in correlations)

    metric_head = "".join("<th>%s</th>" % name for _key, name, _unit, _scale in GEOM_METRICS)
    metric_rows = ""
    for row in rows:
        cells = "".join("<td class='mono'>%s</td>" % (row.get(name, "") if row.get(name) != "" else "n/d")
                        for _key, name, _unit, _scale in GEOM_METRICS)
        metric_rows += ("<tr><td>%s</td><td class='mono'>%.1f</td>%s</tr>"
                        % (row["case_id"], row["dep_N"] or 0.0, cells))

    links = []
    for name, title, note in (
        ("Aero_Design_Explorer.html", "Aero Design Explorer", "mappa, tabella, confronto per zona, modello leave-one-out"),
        ("Aero_Recombination.html", "Aero Recombination Engine", "vettura sintetica zona per zona, con piano di prova"),
    ):
        if os.path.isfile(os.path.join(data_dir, name)):
            links.append('<a class="link" href="%s"><b>%s</b><span>%s</span></a>'
                         % (name, title, note))

    return """<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aero Suite — UniNa Corse</title>
<style>
 body { margin:0; background:#07131f; color:#e8f1f7;
        font-family:"Segoe UI",system-ui,-apple-system,sans-serif; padding:26px 30px 50px; }
 header, main, footer { max-width:1240px; margin:0 auto; }
 .kicker { color:#fdeb19; font-size:11px; letter-spacing:.22em; text-transform:uppercase; font-weight:700; }
 h1 { font-size:32px; margin:6px 0 4px; }
 h1 span { color:#fdeb19; }
 p.sub { color:#8fa8b8; font-size:13.5px; max-width:860px; }
 .cards { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:18px 0; }
 .card { background:#0d2133; border:1px solid rgba(255,255,255,.09); border-radius:13px; padding:13px 15px; }
 .card .label { font-size:10px; letter-spacing:.09em; text-transform:uppercase; color:#8fa8b8; }
 .card .value { font-family:"Cascadia Mono",Consolas,monospace; font-size:20px; font-weight:700; margin-top:3px; }
 .card .note { font-size:11px; color:#8fa8b8; }
 section { background:#0d2133; border:1px solid rgba(255,255,255,.09); border-radius:15px;
           padding:18px 20px; margin-bottom:16px; }
 section h2 { margin:0 0 4px; font-size:17px; }
 section h2 span { color:#fdeb19; font-family:monospace; margin-right:8px; }
 section p.note { margin:2px 0 12px; color:#8fa8b8; font-size:12.5px; }
 table { width:100%%; border-collapse:collapse; font-size:12px; }
 th, td { padding:6px 7px; text-align:right; border-bottom:1px solid rgba(255,255,255,.06); }
 th:first-child, td:first-child { text-align:left; }
 th { color:#8fa8b8; font-size:10px; letter-spacing:.06em; text-transform:uppercase; }
 .mono { font-family:"Cascadia Mono",Consolas,monospace; }
 .links { display:flex; gap:12px; flex-wrap:wrap; }
 .link { flex:1; min-width:240px; text-decoration:none; color:#e8f1f7; background:#10283d;
         border:1px solid rgba(255,255,255,.09); border-radius:12px; padding:13px 15px; }
 .link:hover { border-color:#fdeb19; }
 .link b { display:block; font-size:14px; margin-bottom:3px; }
 .link span { color:#8fa8b8; font-size:11.5px; }
 .warn { border-left:3px solid #fdeb19; background:rgba(253,235,25,.06); padding:9px 13px;
         border-radius:0 9px 9px 0; font-size:12px; margin-top:12px; }
 footer { color:#8fa8b8; font-size:11px; margin-top:16px; }
 @media (max-width:900px) { .cards { grid-template-columns:repeat(2,1fr); } }
</style></head><body>
<header>
 <div class="kicker">UniNa Corse · Aerodynamics &amp; Cooling</div>
 <h1>Aero <span>Suite</span></h1>
 <p class="sub">Post-processing, geometria dalla mesh, Explorer e Recombination Engine in un unico giro.
    Il profilo del fondo viene letto dai triangoli del <code>.cas</code>: nessuna misura manuale,
    nessuna tabella da compilare.</p>
</header>
<main>
 <div class="cards">%CARD%</div>

 <section>
  <h2><span>01</span>Report</h2>
  <p class="note">Apri i due report interattivi generati dallo stesso dataset.</p>
  <div class="links">%LINKS%</div>
 </section>

 <section>
  <h2><span>02</span>Profili del fondo, dalla mesh</h2>
  <p class="note">Altezza della superficie più bassa lungo X, scala comune. In etichetta l'altezza
     minima e l'angolo del tratto in salita.</p>
  %SVG%
 </section>

 <section>
  <h2><span>03</span>Geometria e prestazioni</h2>
  <p class="note">Misure derivate dal mesh per ogni caso. Le zone del fondo vengono riconosciute per nome
     (flat_floor, diffusore, venturi).</p>
  <table><thead><tr><th>caso</th><th>dep N</th>%HEAD%</tr></thead><tbody>%ROWS%</tbody></table>
 </section>

 <section>
  <h2><span>04</span>Correlazioni (con cautela)</h2>
  <p class="note">Coefficiente di Pearson fra metrica geometrica e prestazione, su tutti i casi con
     geometria disponibile.</p>
  <table><thead><tr><th>prestazione</th><th>metrica</th><th>r</th><th>n</th></tr></thead>
  <tbody>%CORR%</tbody></table>
  <div class="warn">Con 15-20 casi una correlazione serve a scegliere la prossima simulazione, non a
     dimostrare una legge. Se |r| è alto, la metrica merita una prova controllata: un caso che cambia
     solo quella geometria.</div>
 </section>
</main>
<footer>Generato il %DATE% · Aero Suite · dati: .cas/.dat reali elaborati da FS-MetaPostDiag</footer>
</body></html>""".replace("%CARD%", card_html).replace("%LINKS%", "".join(links) or
                                                   "<p class='note'>Report non ancora generati.</p>") \
                        .replace("%SVG%", svg_profiles(geometries, cases)) \
                        .replace("%HEAD%", metric_head).replace("%ROWS%", metric_rows or "<tr><td colspan='9'>nessun dato</td></tr>") \
                        .replace("%CORR%", corr_rows or "<tr><td colspan='4'>nessun dato</td></tr>") \
                        .replace("%DATE%", datetime.now().strftime("%Y-%m-%d %H:%M"))


def stage_reports(data_dir, tools_dir):
    outputs = []
    for script in ("design_explorer.py", "recombination.py"):
        path = os.path.join(tools_dir, script)
        if not os.path.isfile(path):
            print("  %s non trovato in %s" % (script, tools_dir))
            continue
        try:
            result = subprocess.run([sys.executable, path, "--data", data_dir],
                                    capture_output=True, text=True, errors="replace")
        except OSError as exc:
            print("  %s: %s" % (script, exc))
            continue
        tail = [line for line in (result.stdout or "").splitlines() if line.strip()][-3:]
        for line in tail:
            print("  " + line.strip())
        if result.returncode != 0:
            print("  %s ha restituito %d" % (script, result.returncode))
        outputs.append(script)
    cases = load_cases(data_dir)
    geometries = load_geometries(data_dir, cases)
    rows, correlations = stage_tables(data_dir, quiet=True)
    html = render_suite_html(data_dir, cases, geometries, rows, correlations)
    path = os.path.join(data_dir, SUITE_HTML)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html)
    print("pagina indice: %s (%.1f KB)" % (path, os.path.getsize(path) / 1024.0))
    return path


# ------------------------------------------------------------------------ CLI
def main():
    parser = argparse.ArgumentParser(description="Aero Suite: geometria, tabelle, report.")
    parser.add_argument("--data", required=True, help="cartella _dati_batch")
    parser.add_argument("--stage", default="all",
                        choices=["geometry", "tables", "reports", "all"])
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
    here = os.path.dirname(os.path.abspath(__file__))
    exe = os.path.abspath(args.exe) if args.exe else os.path.join(here, "FS-MetaPostDiag.exe")
    tools_dir = os.path.abspath(args.tools) if args.tools else os.path.abspath(
        os.path.join(here, "..", "tools"))
    if not os.path.isdir(os.path.join(data_dir, "..")) and False:
        pass

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
    if args.stage in ("reports", "all"):
        print("\n[3/3] report")
        stage_reports(data_dir, tools_dir)
    print("\nFatto. Apri: %s" % os.path.join(data_dir, SUITE_HTML))
    return 0 if failures == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
