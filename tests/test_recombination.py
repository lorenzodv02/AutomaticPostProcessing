# -*- coding: utf-8 -*-
"""Aero Recombination Engine: classificazione, sintesi, proposte, filtri."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import recombination as reco  # noqa: E402


def test_family_classification():
    assert reco.family_of("flat_floor") == "fondo"
    assert reco.family_of("venturi_first") == "fondo"
    assert reco.family_of("diffusore_int") == "fondo"
    assert reco.family_of("front_main") == "ala anteriore"
    assert reco.family_of("rear_main_down") == "ala posteriore"
    assert reco.family_of("front_tyre") == "gomme"
    assert reco.family_of("chassis") == "corpo"


def _cases():
    return {
        "base": {"id": "base", "dep": 500.0, "drag": 220.0, "ld": 2.27,
                 "wing": "RW1", "diff": "Completo", "cas": "a.cas", "modello": "MA"},
        "donor": {"id": "donor", "dep": 520.0, "drag": 222.0, "ld": 2.34,
                  "wing": "RW1", "diff": "Completo", "cas": "b.cas", "modello": "MB"},
        "donor2": {"id": "donor2", "dep": 505.0, "drag": 210.0, "ld": 2.40,
                   "wing": "RW1", "diff": "Completo", "cas": "c.cas", "modello": "MC"},
        # coppia doppia: stesso modello, stessi valori -> rumore misurato ~0
        "dup1": {"id": "dup1", "dep": 500.0, "drag": 220.0, "ld": 2.27,
                 "wing": "RW1", "diff": "Completo", "cas": "d.cas", "modello": "MD"},
        "dup2": {"id": "dup2", "dep": 500.0, "drag": 220.0, "ld": 2.27,
                 "wing": "RW1", "diff": "Completo", "cas": "e.cas", "modello": "MD"},
    }


def _zone(base, donor, donor2, dup1, dup2, tyre=(5.0, 20.0, 5.0, 5.0, 5.0)):
    def values(b, d, d2, u1, u2, drag=0.0):
        return [
            {"dep": b, "drag": 0.0, "area": 1.0, "stall": 0.0},
            {"dep": d, "drag": drag, "area": 1.0, "stall": 0.0},
            {"dep": d2, "drag": 0.0, "area": 1.0, "stall": 0.0},
            {"dep": u1, "drag": 0.0, "area": 1.0, "stall": 0.0},
            {"dep": u2, "drag": 0.0, "area": 1.0, "stall": 0.0},
        ]
    zones = {}
    for name, tuple_values in (
        ("flat_floor", (10.0, 25.0, 12.0, 10.0, 10.0)),
        ("venturi_first", (8.0, 8.0, 12.0, 8.0, 8.0)),
        ("front_main", (100.0, 100.0, 100.0, 100.0, 100.0)),
        ("front_tyre", tyre),
        ("chassis", (60.0, 62.0, 61.0, 60.0, 60.0)),
    ):
        values_list = values(*tuple_values, drag=1.0)
        zones[name] = dict(zip(("base", "donor", "donor2", "dup1", "dup2"), values_list))
    return zones


def test_synthesis_and_noise_filter():
    cases = _cases()
    zones = _zone(*[None] * 5)
    members = ["base", "donor", "donor2", "dup1", "dup2"]
    rows, usable, totals, noise = reco.build_synthesis(
        cases, zones, {}, ("RW1", "Completo"), members, "base", 0.5, {"gomme"})
    names = [row["zone"] for row in usable]
    assert "flat_floor" in names, usable
    assert "front_tyre" not in names, "le gomme vanno escluse"
    assert noise["pairs"] == 1, noise
    flat = next(row for row in rows if row["zone"] == "flat_floor")
    assert flat["donor"] == "donor" and abs(flat["gain"] - 15.0) < 1e-9, flat
    assert totals["gain_dep"] == round(sum(r["gain"] for r in usable), 2)
    assert totals["synth_dep"] == round(totals["base_dep"] + totals["gain_dep"], 2)


def test_noise_filters_small_gain():
    """Un guadagno sotto 3 sigma rispetto alle run doppie non e' affidabile."""
    cases = _cases()
    # le run doppie differiscono di 2 N su chassis -> 3 sigma = 6 N
    zones = _zone(*[None] * 5)
    zones["chassis"]["dup2"] = {"dep": 62.0, "drag": 0.0, "area": 1.0, "stall": 0.0}
    members = ["base", "donor", "donor2", "dup1", "dup2"]
    rows, usable, _totals, noise = reco.build_synthesis(
        cases, zones, {}, ("RW1", "Completo"), members, "base", 0.5, {"gomme"})
    chassis = next(row for row in rows if row["zone"] == "chassis")
    assert chassis["zone_noise"] >= 2.0, chassis
    assert chassis["reliable"] is False, chassis


def test_proposals_are_incremental():
    cases = _cases()
    zones = _zone(*[None] * 5)
    members = ["base", "donor", "donor2", "dup1", "dup2"]
    rows, usable, totals, _noise = reco.build_synthesis(
        cases, zones, {}, ("RW1", "Completo"), members, "base", 0.5, {"gomme"})
    proposals = reco.build_proposals(usable, "base", cases)
    assert [p["name"] for p in proposals] == ["A · solo fondo", "B · fondo + ali", "C · tutto l'affidabile"]
    gains = [p["gain"] for p in proposals]
    assert gains[0] <= gains[1] <= gains[2], gains
    assert abs(gains[-1] - totals["gain_dep"]) < 0.05
    assert proposals[0]["items"], proposals[0]
    assert all(item["zone"] and item["donor"] for item in proposals[0]["items"])


def test_payload_from_files(tmp_path=None):
    import csv
    import shutil
    import tempfile

    folder = tempfile.mkdtemp(prefix="reco_")
    try:
        header = ["case_id", "ala_post", "diffusore", "dep", "drag", "cas_file", "modello"]
        with open(os.path.join(folder, "dataset.csv"), "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["case_id", "deportanza_N", "drag_N", "L_D", "ala_post",
                             "diffusore", "cas_file", "iterazioni", "modello"])
            writer.writerow(["base", 500.0, 220.0, 2.27, "RW1", "Completo", "a.cas", 1250, "MA"])
            writer.writerow(["donor", 520.0, 222.0, 2.34, "RW1", "Completo", "b.cas", 1250, "MB"])
            writer.writerow(["dup1", 500.0, 220.0, 2.27, "RW1", "Completo", "d.cas", 1250, "MD"])
            writer.writerow(["dup2", 500.0, 220.0, 2.27, "RW1", "Completo", "e.cas", 1250, "MD"])
        with open(os.path.join(folder, "dataset_pid.csv"), "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["case_id", "zone_name", "df_2x_N", "drag_2x_N", "area_m2", "stallo_pct"])
            for case, flat in (("base", 10.0), ("donor", 25.0), ("dup1", 10.0), ("dup2", 10.0)):
                writer.writerow([case, "flat_floor", flat, 0.0, 1.0, 0.0])
                writer.writerow([case, "chassis", 60.0, 0.0, 2.0, 0.0])
        # il riferimento si puo' forzare: senza, sarebbe il caso con piu' deportanza
        payload = reco.build_payload(folder, baseline_id="base")
        assert payload["group"]["wing"] == "RW1"
        assert payload["baseline"] == "base"
        assert payload["totals"]["gain_dep"] > 0
        assert payload["proposals"]
    finally:
        shutil.rmtree(folder, ignore_errors=True)
