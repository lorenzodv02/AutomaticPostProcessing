# -*- coding: utf-8 -*-
"""Aero Suite: payload unico, dashboard brandizzato, tabelle geometriche."""
import csv
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "suite"))

import aero_suite as suite  # noqa: E402

TEMPLATE = os.path.join(REPO, "suite", "suite_template.html")


def _case(case_id, dep, drag, ld, wing="RW1", diff="Completo"):
    return {
        "case_id": case_id, "deportanza_N": dep, "drag_N": drag, "L_D": ld,
        "ala_post": wing, "diffusore": diff, "cas_file": case_id + ".cas",
        "modello": case_id, "iterazioni": 1250, "cop_x_pct": 63.0,
    }


def _build(tmp, cases, exclusions=(), with_geometry=True):
    header = ["case_id", "assieme", "cas_file", "dat_file", "iterazioni", "v_inf_ms",
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
    if not with_geometry:
        return
    for index, case in enumerate(cases):
        summary = {
            "throat_h_m": 0.040 + 0.001 * index, "throat_pct": 55.0,
            "rise_kind": "diffusore", "rise_length_m": 0.5, "rise_angle_deg": 10.0 + index,
            "expansion_ratio": 2.0 + 0.1 * index, "plan_area_m2": 0.5,
            "floor_area_m2": 1.0,
        }
        stations = 12
        geometry = {
            "available": True,
            "x_m": [1.5 + 0.05 * i for i in range(stations)],
            "h_min_m": [0.04 + 0.001 * i for i in range(stations)],
            "h_mean_m": [0.05] * stations, "width_m": [0.5] * stations,
            "section_m2": [0.02] * stations, "ramp": {}, "zones": [],
        }
        json.dump({"case": case["case_id"], "summary": summary, "geometry": geometry},
                  open(os.path.join(tmp, "geom", case["case_id"] + ".json"), "w",
                       encoding="utf-8"), ensure_ascii=False)


def _cases():
    return [_case("a", 500.0, 220.0, 2.27), _case("b", 510.0, 224.0, 2.28),
            _case("c", 520.0, 228.0, 2.28), _case("d", 530.0, 232.0, 2.28),
            _case("e", 505.0, 222.0, 2.27)]


def test_pearson_known_values():
    assert abs(suite.pearson([1, 2, 3, 4], [2, 4, 6, 8]) - 1.0) < 1e-9
    assert abs(suite.pearson([1, 2, 3, 4], [8, 6, 4, 2]) + 1.0) < 1e-9
    assert suite.pearson([1, 2], [1, 2]) is None
    assert suite.pearson([1, 1, 1, 1], [1, 2, 3, 4]) is None


def test_exclusions_are_respected():
    folder = tempfile.mkdtemp(prefix="suite_")
    try:
        cases = _cases() + [_case("excluded", 999.0, 240.0, 4.16)]
        _build(folder, cases, exclusions=["excluded"])
        loaded = suite.load_cases(folder)
        assert [case["id"] for case in loaded] == ["d", "c", "b", "e", "a"], [c["id"] for c in loaded]
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_tables_produce_csv_and_correlations():
    folder = tempfile.mkdtemp(prefix="suite_")
    try:
        _build(folder, _cases())
        rows, correlations = suite.stage_tables(folder)
        assert len(rows) == 5
        assert os.path.isfile(os.path.join(folder, suite.GEOM_CSV))
        assert correlations
        assert any(item["metric"] == "Altezza minima" for item in correlations)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_payload_has_all_sections():
    folder = tempfile.mkdtemp(prefix="suite_")
    try:
        _build(folder, _cases())
        payload = suite.build_dashboard_payload(folder, os.path.join(REPO, "tools"))
        assert payload["counts"]["cases"] == 5
        assert payload["counts"]["geom"] == 5
        assert payload["geometry"]["available"] is True
        assert len(payload["geometry"]["profiles"]) == 5
        assert payload["zones"], "le zone per PID devono esserci"
        assert "synthesis" in payload
        assert payload["model"]["available"] is False or isinstance(payload["model"]["targets"], dict)
        json.dumps(payload)  # serializzabile
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_dashboard_is_branded_and_complete():
    folder = tempfile.mkdtemp(prefix="suite_")
    try:
        _build(folder, _cases())
        payload = suite.build_dashboard_payload(folder, os.path.join(REPO, "tools"))
        html = suite.render_dashboard(payload, TEMPLATE)
        # brand: variabili ufficiali e tipografia
        assert "--gold: #FDEB19" in html
        assert "--navy: #11255C" in html
        assert "Roboto" in html
        assert "UniNa Corse" in html and "Aerodynamics &amp; Cooling" in html
        # struttura: cinque schede e tutte le sezioni
        for panel in ("overview", "zones", "synthesis", "geometry", "method"):
            assert 'data-tab="%s"' % panel in html, panel
        assert "Aero Suite" in html
        assert "__PAYLOAD__" not in html and "__HEADER__" not in html
        assert '"geometry":{"available":true' in html.replace(" ", "")
        # il JSON nel dashboard deve essere valido
        start = html.index("window.__SUITE__ = ") + len("window.__SUITE__ = ")
        end = html.index(";</script>", start)
        json.loads(html[start:end])
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_template_uses_proposals_key():
    template = open(TEMPLATE, encoding="utf-8").read()
    assert "S.proposals" in template
    assert "S.packages" not in template


def test_dashboard_without_geometry_says_so():
    folder = tempfile.mkdtemp(prefix="suite_")
    try:
        _build(folder, _cases(), with_geometry=False)
        payload = suite.build_dashboard_payload(folder, os.path.join(REPO, "tools"))
        assert payload["counts"]["geom"] == 0
        assert payload["geometry"]["available"] is False
        html = suite.render_dashboard(payload, TEMPLATE)
        assert "esegui lo stadio geometria" in html.lower() or "geometria" in html.lower()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
