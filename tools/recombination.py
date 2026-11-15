# -*- coding: utf-8 -*-
"""
Aero Recombination Engine — ricompone la vettura zona per zona dai casi CFD.

Per ogni zona del fondo, dell'ala e del corpo cerca il caso che la produce
meglio e costruisce una "vettura sintetica" indicando da quale configurazione
prendere ciascun pezzo. Misura anche l'affidabilita' di ogni zona sulle run
doppie e scarta le zone che il rumore non distingue.

Solo libreria standard. Uso:
    python recombination.py --data "D:\\Analisi\\_dati_batch"
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from datetime import datetime

EXCLUSIONS_FILE = "escludi.txt"
TEMPLATE_NAME = "recombination_template.html"
RELIABILITY_SIGMA = 3.0
# pavimento sul rumore: due run identiche danno differenza 0, ma il rumore
# non e" mai esattamente zero (arrotondamenti, scrittura dei file).
RELIABILITY_FLOOR = 0.05
# se non ci sono run doppie il rumore non e' misurabile: si assume questo valore.
ASSUMED_NOISE = 0.5
DEFAULT_MIN_GAIN = 0.5


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
    cases = {}
    for row in rows:
        if row["case_id"] in excluded:
            continue
        cases[row["case_id"]] = {
            "id": row["case_id"],
            "dep": to_float(row.get("deportanza_N")),
            "drag": to_float(row.get("drag_N")),
            "ld": to_float(row.get("L_D")),
            "wing": row.get("ala_post") or "",
            "diff": row.get("diffusore") or "",
            "cas": row.get("cas_file") or "",
            "modello": row.get("modello") or "",
            "iter": row.get("iterazioni") or "",
        }
    return cases


def load_zones(data_dir):
    excluded = load_exclusions(data_dir)
    path = os.path.join(data_dir, "dataset_pid.csv")
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig", newline=""), delimiter=";"))
    zone_values = defaultdict(dict)
    for row in rows:
        if row["case_id"] in excluded:
            continue
        zone_values[row["zone_name"]][row["case_id"]] = {
            "dep": to_float(row.get("df_2x_N")) or 0.0,
            "drag": to_float(row.get("drag_2x_N")) or 0.0,
            "area": to_float(row.get("area_m2")),
            "stall": to_float(row.get("stallo_pct")),
        }
    return zone_values


def load_bboxes(data_dir):
    """xmin/xmax per zona, dai JSON di estrazione (per le interfacce)."""
    out = defaultdict(dict)
    for name in sorted(os.listdir(data_dir)):
        if not name.endswith(".json") or name.startswith("_"):
            continue
        try:
            payload = json.load(open(os.path.join(data_dir, name), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pids = (payload.get("physics_data") or {}).get("per_pid_breakdown") or []
        for pid in pids:
            bbox = pid.get("bbox") or {}
            xmin, xmax = to_float(bbox.get("xmin")), to_float(bbox.get("xmax"))
            if xmin is None or xmax is None:
                continue
            out[pid["zone_name"]][os.path.splitext(name)[0]] = (xmin, xmax)
    return out


def family_of(zone):
    name = zone.lower()
    if name.startswith(("venturi", "flat_floor", "diffusore")):
        return "fondo"
    if name.startswith(("front_main", "front_first", "front_second", "front_third",
                        "front_fourth", "front_fifth", "front_sixth", "front_midplate",
                        "front_footplate", "front_extra", "front_external", "front_internal",
                        "front_suspension", "inverted", "endplate_flap", "flap_verticali")):
        return "ala anteriore"
    if name.startswith(("rear_main", "rear_first", "rear_second", "rear_third",
                        "rear_endplate", "rear_slat", "rear_suspension")):
        return "ala posteriore"
    if name.startswith(("front_tyre", "rear_tyre", "tyrewall")):
        return "gomme"
    return "corpo"


def zone_noise(cases, zone_values):
    """
    Rumore per zona: differenza fra casi che usano lo STESSO file .cas
    (run doppie dello stesso modello). Se non ci sono doppioni, rumore ignoto.
    """
    by_file = defaultdict(list)
    for case_id, case in cases.items():
        # doppioni: stesso file .cas oppure stesso modello del workbook con la
        # stessa configurazione (run diverse dello stesso progetto)
        model = (case.get("modello") or "").strip().lower()
        base = model or case["cas"].lower()
        if base:
            key = "%s|%s|%s" % (base, case["wing"], case["diff"])
            by_file[key].append(case_id)
    pairs = [ids for ids in by_file.values() if len(ids) >= 2]
    noise = defaultdict(float)
    observations = 0
    for ids in pairs:
        left, right = ids[0], ids[1]
        for zone, values in zone_values.items():
            if left in values and right in values:
                noise[zone] = max(noise[zone],
                                  abs(values[right]["dep"] - values[left]["dep"]))
                observations += 1
    default = sum(noise.values()) / len(noise) if noise else ASSUMED_NOISE
    return noise, default, len(pairs)


def choose_group(cases, requested=None):
    groups = defaultdict(list)
    for case_id, case in cases.items():
        groups[(case["wing"], case["diff"])].append(case_id)
    if requested:
        for key, members in groups.items():
            if requested in (key[0], "%s + %s" % key, "%s|%s" % key):
                return key, members
        raise SystemExit("gruppo non trovato: %s (disponibili: %s)"
                         % (requested, "; ".join("%s + %s" % key for key in groups)))
    key = max(groups, key=lambda k: len(groups[k]))
    return key, groups[key]


def build_synthesis(cases, zone_values, bboxes, group_key, members, baseline_id,
                    min_gain, exclude_families):
    baseline = cases[baseline_id]
    rows = []
    noise, default_noise, duplicate_pairs = zone_noise(cases, zone_values)
    for zone, values in zone_values.items():
        present = {cid: value for cid, value in values.items() if cid in members}
        if baseline_id not in present or len(present) < 2:
            continue
        base = present[baseline_id]
        donor = max(present, key=lambda cid: present[cid]["dep"])
        gain = present[donor]["dep"] - base["dep"]
        if gain <= min_gain:
            continue
        zone_noise_n = max(noise.get(zone, default_noise), RELIABILITY_FLOOR)
        reliable = gain >= RELIABILITY_SIGMA * zone_noise_n
        rows.append({
            "zone": zone,
            "family": family_of(zone),
            "base_dep": round(base["dep"], 2),
            "donor": donor,
            "donor_dep": round(present[donor]["dep"], 2),
            "gain": round(gain, 2),
            "drag_delta": round(present[donor]["drag"] - base["drag"], 2),
            "zone_noise": round(zone_noise_n, 2),
            "reliable": reliable,
            "excluded_family": family_of(zone) in exclude_families,
            "x": bboxes.get(zone, {}).get(donor) or bboxes.get(zone, {}).get(baseline_id),
        })
    rows.sort(key=lambda r: -r["gain"])
    usable = [r for r in rows if r["reliable"] and not r["excluded_family"]]
    totals = {
        "base_dep": baseline["dep"], "base_drag": baseline["drag"],
        "gain_dep": round(sum(r["gain"] for r in usable), 2),
        "delta_drag": round(sum(r["drag_delta"] for r in usable), 2),
        "zones": len(usable),
    }
    totals["synth_dep"] = round(totals["base_dep"] + totals["gain_dep"], 2)
    totals["synth_drag"] = round(totals["base_drag"] + totals["delta_drag"], 2)
    totals["ld"] = round(totals["synth_dep"] / totals["synth_drag"], 3) if totals["synth_drag"] else None
    return rows, usable, totals, {"pairs": duplicate_pairs, "default": round(default_noise, 2)}


def build_proposals(usable, baseline_id, cases):
    """Tre proposte incrementali: solo fondo, fondo+ali, tutto l'affidabile."""
    def package(name, predicate):
        items = [row for row in usable if predicate(row["family"])]
        if not items:
            return None
        by_donor = defaultdict(list)
        for row in items:
            by_donor[row["donor"]].append(row)
        gain = round(sum(row["gain"] for row in items), 2)
        drag = round(sum(row["drag_delta"] for row in items), 2)
        interfaces = 0
        for i, first in enumerate(items):
            for second in items[i + 1:]:
                if first["donor"] == second["donor"]:
                    continue
                x1, x2 = first["x"], second["x"]
                if x1 and x2 and x1[1] >= x2[0] - 0.02 and x2[1] >= x1[0] - 0.02:
                    interfaces += 1
        return {
            "name": name,
            "gain": gain,
            "delta_drag": drag,
            "zones": len(items),
            "donors": sorted(by_donor, key=lambda d: -sum(r["gain"] for r in by_donor[d])),
            "interfaces": interfaces,
            "items": [{"zone": row["zone"], "donor": row["donor"], "gain": row["gain"],
                       "family": row["family"]} for row in sorted(items, key=lambda r: -r["gain"])],
        }

    return [p for p in (
        package("A · solo fondo", lambda fam: fam == "fondo"),
        package("B · fondo + ali", lambda fam: fam in ("fondo", "ala anteriore", "ala posteriore")),
        package("C · tutto l'affidabile", lambda fam: True),
    ) if p]


def build_payload(data_dir, group_requested=None, baseline_id=None,
                  min_gain=DEFAULT_MIN_GAIN, exclude_families=("gomme",)):
    cases = load_cases(data_dir)
    zone_values = load_zones(data_dir)
    bboxes = load_bboxes(data_dir)
    group_key, members = choose_group(cases, group_requested)
    if baseline_id is None:
        baseline_id = max(members, key=lambda cid: cases[cid]["dep"] or 0.0)
    if baseline_id not in members:
        raise SystemExit("il riferimento %s non e' nel gruppo %s + %s"
                         % (baseline_id, group_key[0], group_key[1]))
    rows, usable, totals, noise_info = build_synthesis(
        cases, zone_values, bboxes, group_key, members, baseline_id,
        min_gain, set(exclude_families))
    proposals = build_proposals(usable, baseline_id, cases)
    families = defaultdict(lambda: {"gain": 0.0, "delta_drag": 0.0, "zones": 0})
    for row in usable:
        families[row["family"]]["gain"] += row["gain"]
        families[row["family"]]["delta_drag"] += row["drag_delta"]
        families[row["family"]]["zones"] += 1
    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "group": {"wing": group_key[0], "diff": group_key[1], "cases": len(members)},
        "baseline": baseline_id,
        "baseline_case": cases[baseline_id],
        "members": [{"id": cid, "dep": cases[cid]["dep"], "drag": cases[cid]["drag"]}
                    for cid in sorted(members, key=lambda c: -(cases[c]["dep"] or 0))],
        "rows": rows,
        "usable": usable,
        "totals": totals,
        "proposals": proposals,
        "families": families,
        "noise": noise_info,
        "exclude_families": list(exclude_families),
        "min_gain": min_gain,
        "counts": {"zones": len(rows), "usable": len(usable)},
    }


def render(payload, template_path):
    template = open(template_path, "r", encoding="utf-8").read()
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return template.replace("__PAYLOAD__", data)


def main():
    parser = argparse.ArgumentParser(description="Genera l'Aero Recombination Engine.")
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--template", default=None)
    parser.add_argument("--group", default=None, help="configurazione (es. 'RW1')")
    parser.add_argument("--baseline", default=None, help="caso di riferimento")
    parser.add_argument("--min-gain", type=float, default=DEFAULT_MIN_GAIN)
    parser.add_argument("--exclude-family", default="gomme",
                        help="famiglie escluse (separate da virgola, default: gomme)")
    args = parser.parse_args()

    data_dir = os.path.abspath(args.data)
    out_path = os.path.abspath(args.out or os.path.join(data_dir, "Aero_Recombination.html"))
    template = args.template or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             TEMPLATE_NAME)
    exclude = tuple(part.strip() for part in args.exclude_family.split(",") if part.strip())
    payload = build_payload(data_dir, args.group, args.baseline, args.min_gain, exclude)
    html = render(payload, template)
    open(out_path, "w", encoding="utf-8").write(html)

    totals = payload["totals"]
    print("gruppo: %s + %s (%d casi) | riferimento %s"
          % (payload["group"]["wing"], payload["group"]["diff"],
             payload["group"]["cases"], payload["baseline"]))
    print("base   : %.1f N dep / %.1f N drag" % (totals["base_dep"], totals["base_drag"]))
    print("sintesi: %.1f N dep / %.1f N drag  (%+0.1f N, %+0.1f N) su %d zone"
          % (totals["synth_dep"], totals["synth_drag"], totals["gain_dep"],
             totals["delta_drag"], totals["zones"]))
    print("rumore per zona: %.2f N (da %d coppie doppie) | famiglie escluse: %s"
          % (payload["noise"]["default"], payload["noise"]["pairs"],
             ", ".join(payload["exclude_families"]) or "-"))
    for proposal in payload["proposals"]:
        print("  %-24s %+6.1f N | drag %+5.1f N | %2d zone | donatori: %s"
              % (proposal["name"], proposal["gain"], proposal["delta_drag"],
                 proposal["zones"], ", ".join(proposal["donors"][:4])))
    print("HTML scritto:", out_path, "(%.1f KB)" % (os.path.getsize(out_path) / 1024.0))


if __name__ == "__main__":
    raise SystemExit(main())
