# -*- coding: utf-8 -*-
"""Aero Suite: tabelle geometriche, correlazioni, pagina indice."""
import csv
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "suite"))

import aero_suite as suite  # noqa: E402


def _case(case_id, dep, drag, ld, kind="diffusore", angle=10.0):
    return {
        "case_id": case_id, "deportanza_N": dep, "drag_N": drag, "L_D": ld,
        "ala_post": "RW1", "diffusore": "Completo", "cas_file": "",
        "modello": case_id, "iterazioni": 1250,
    }


def _build(tmp, cases, exclusions=()):
    header = ["case_id", "assemble", "cas_file", "dat_file", "iterazioni", "v_inf_ms",
              "half_car", "deportanza_N", "drag_N", "CL", "CD", "CL_A", "CD_A", "L_D",
              "cop_x_m", "cop_x_pct", "cop_passo_pct", "stallo_pct", "cp_min", "modello",
              "nota", "velocita_nominale_ms", "max_height_mm", "height_gola_mm",
              "pos_gola_mm", "pos_gola_pct_passo", "ala_post", "ala_ant", "diffusore",
              "excel_downforce_N", "excel_drag_N"]
    with open(os.path.join(tmp, "dataset.csv"), "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, delimiter=";")
        writer.writeheader()
        for case in cases:
            writer.writerow({key: case.get(key, "") for key in header})
    with open(os.path.join(tmp, "dataset_pid.csv"), "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["case_id", "zone_name", "zone_id", "n_faces", "area_m2", "cp_min",
                         "cp_mean", "df_pressione_1x_N", "df_viscosa_1x_N", "df_1x_N",
                         "df_2x_N", "drag_pressione_1x_N", "drag_viscosa_1x_N", "drag_1x_N",
                         "drag_2x_N", "stallo_pct", "fonte_viscosa"])
        for case in cases:
            writer.writerow([case["case_id"], "flat_floor", 1, 10, 0.1, -1.5, -0.5,
                             case["deportanza_N"] * 0.1, 0, case["deportanza_N"] * 0.1,
                             case["deportanza_N"] * 0.1, 1.0, 0, 1.0, 1.0, 10, "fluent"])
    if exclusions:
        with open(os.path.join(tmp, "escludi.txt"), "w", encoding="utf-8") as handle:
            handle.write("\n".join(exclusions) + "\n")
    os.makedirs(os.path.join(tmp, "geom"), exist_ok=True)
    for index, case in enumerate(cases):
        summary = {
            "throat_h_m": 0.040 + 0.001 * index, "throat_pct": 55.0,
            "rise_kind": "diffusore", "rise_length_m": 0.5, "rise_angle_deg": 10.0 + index,
            "expansion_ratio": 2.0 + 0.1 * index, "plan_area_m2": 0.5,
            "floor_area_m2": 1.0, "diffuser_angle_deg": 0.0,
        }
        stations = 20
        geometry = {
            "available": True, "x_m": [1.5 + 0.05 * i for i in range(stations)],
            "h_min_m": [0.04 + 0.001 * i for i in range(stations)],
            "h_mean_m": [0.05] * stations, "width_m": [0.5] * stations,
            "section_m2": [0.02] * stations, "ramp": {}, "zones": [],
        }
        json.dump({"case": case["case_id"], "summary": summary, "geometry": geometry},
                  open(os.path.join(tmp, "geom", case["case_id"] + ".json"), "w",
                       encoding="utf-8"), ensure_ascii=False)


def test_pearson_known_values():
    assert abs(suite.pearson([1, 2, 3, 4], [2, 4, 6, 8]) - 1.0) < 1e-9
    assert abs(suite.pearson([1, 2, 3, 4], [8, 6, 4, 2]) + 1.0) < 1e-9
    assert suite.pearson([1, 2], [1, 2]) is None          # meno di 4 punti
    assert suite.pearson([1, 1, 1, 1], [1, 2, 3, 4]) is None  # varianza nulla


def test_tables_and_correlations(tmp_path=None):
    folder = tempfile.mkdtemp(prefix="suite_")
    try:
        cases = [_case("a", 500.0, 220.0, 2.27), _case("b", 510.0, 224.0, 2.28),
                 _case("c", 520.0, 228.0, 2.28), _case("d", 530.0, 232.0, 2.28)]
        _build(folder, cases)
        rows, correlations = suite.stage_tables(folder)
        assert len(rows) == 4
        csv_path = os.path.join(folder, suite.GEOM_CSV)
        assert os.path.isfile(csv_path)
        header = open(csv_path, encoding="utf-8-sig").readline()
        assert "Altezza minima" in header
        assert correlations, "servono correlazioni"
        assert any(item["metric"] == "Altezza minima" for item in correlations)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_exclusions_are_respected():
    folder = tempfile.mkdtemp(prefix="suite_")
    try:
        cases = [_case("a", 500.0, 220.0, 2.27), _case("b", 510.0, 224.0, 2.28),
                 _case("c", 520.0, 228.0, 2.28), _case("d", 530.0, 232.0, 2.28),
                 _case("excluded", 999.0, 240.0, 4.16)]
        _build(folder, cases, exclusions=["excluded"])
        loaded = suite.load_cases(folder)
        assert [case["id"] for case in loaded] == ["a", "b", "c", "d"]
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_suite_html_has_links_profiles_and_caveat():
    folder = tempfile.mkdtemp(prefix="suite_")
    try:
        cases = [_case("a", 500.0, 220.0, 2.27), _case("b", 510.0, 224.0, 2.28),
                 _case("c", 520.0, 228.0, 2.28), _case("d", 530.0, 232.0, 2.28)]
        _build(folder, cases)
        for name in ("Aero_Design_Explorer.html", "Aero_Recombination.html"):
            open(os.path.join(folder, name), "w", encoding="utf-8").write("<html></html>")
        rows, correlations = suite.stage_tables(folder)
        geometries = suite.load_geometries(folder, suite.load_cases(folder))
        html = suite.render_suite_html(folder, suite.load_cases(folder), geometries,
                                       rows, correlations)
        assert "Aero Design Explorer" in html and "Aero_Recombination.html" in html
        assert "<svg" in html and "polyline" in html
        assert "Con 15-20 casi una correlazione serve" in html
        assert "Altezza minima" in html
    finally:
        shutil.rmtree(folder, ignore_errors=True)
