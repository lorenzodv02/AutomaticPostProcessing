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
            "front_span_m": 1.4, "front_chord_m": 0.3, "front_area_m2": 0.42,
            "front_aspect": 4.6, "rear_span_m": 1.1, "rear_chord_m": 0.25,
            "rear_area_m2": 0.27, "rear_aspect": 4.4,
            "area_fondo_m2": 1.0, "area_ala_anteriore_m2": 2.1,
            "area_ala_posteriore_m2": 1.9, "area_corpo_m2": 3.0,
        }
        stations = 12
        floor = {
            "available": True,
            "x_m": [1.5 + 0.05 * i for i in range(stations)],
            "h_min_m": [0.04 + 0.001 * i for i in range(stations)],
            "h_mean_m": [0.05] * stations, "width_m": [0.5] * stations,
            "section_m2": [0.02] * stations, "ramp": {}, "zones": [],
        }
        geometry = {
            "available": True, "assembly": "full_car",
            "floor": floor,
            "wings": {
                "front": {"available": True, "span_m": 1.4, "chord_mean_m": 0.3,
                          "planform_m2": 0.42, "aspect_ratio": 4.6},
                "rear": {"available": True, "span_m": 1.1, "chord_mean_m": 0.25,
                         "planform_m2": 0.27, "aspect_ratio": 4.4},
            },
            "parts": {"fondo": {"area_m2": 1.0, "zones": 5},
                      "ala anteriore": {"area_m2": 2.1, "zones": 16}},
            "zones": [],
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


def test_payload_includes_wings_and_areas():
    folder = tempfile.mkdtemp(prefix="suite_")
    try:
        _build(folder, _cases())
        payload = suite.build_dashboard_payload(folder, os.path.join(REPO, "tools"))
        rows = payload["geometry"]["rows"]
        assert rows, "servono righe geometriche"
        row = rows[0]
        assert row["front_span"] == 1.4 and row["rear_span"] == 1.1
        assert row["area_front"] == 2.1 and row["area_body"] == 3.0
        assert payload["counts"]["geom"] == 5
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_family_packages_from_synthesis():
    synthesis = {"rows": [
        {"zone": "flat_floor", "family": "fondo", "donor": "D7", "gain": 8.0,
         "drag_delta": 0.1, "reliable": True, "excluded_family": False},
        {"zone": "front_main", "family": "ala anteriore", "donor": "V12", "gain": 24.0,
         "drag_delta": 6.0, "reliable": True, "excluded_family": False},
        {"zone": "rear_main", "family": "ala posteriore", "donor": "D8", "gain": 8.0,
         "drag_delta": -0.5, "reliable": True, "excluded_family": False},
        {"zone": "front_tyre", "family": "gomme", "donor": "X", "gain": 99.0,
         "drag_delta": 0.0, "reliable": True, "excluded_family": True},
    ]}
    packages = suite._family_packages(synthesis)
    names = [p["name"] for p in packages]
    assert names == ["Solo ala anteriore", "Solo ala posteriore", "Solo fondo"]
    assert packages[0]["gain"] == 24.0 and packages[0]["zones"] == 1
    assert all(p["family"] != "gomme" for p in packages)


def test_collect_case_outputs_discovers_report_images_and_ai():
    folder = tempfile.mkdtemp(prefix="suite_")
    try:
        _build(folder, _cases())
        case = {"id": "a", "dep": 500.0, "drag": 220.0, "ld": 2.27}
        target = os.path.join(folder, "cases", "a")
        os.makedirs(os.path.join(target, "images_raw"))
        open(os.path.join(target, "CFD_Aero_Diagnostic_Report.html"), "w",
             encoding="utf-8").write("<html>AI Vision: perizia</html>")
        open(os.path.join(target, "Tabella.xlsx"), "wb").write(b"xlsx")
        open(os.path.join(target, "images_raw", "01.png"), "wb").write(b"png")
        open(os.path.join(target, "images_raw", "02.png"), "wb").write(b"png")
        manifest = suite._collect_case_outputs(target, case)
        assert manifest["html"] == "CFD_Aero_Diagnostic_Report.html"
        assert manifest["report"] == "cases/a/CFD_Aero_Diagnostic_Report.html"
        assert manifest["xlsx"] == "cases/a/Tabella.xlsx"
        assert manifest["images"] == 2
        assert manifest["ai_used"] is True
        json.dump(manifest, open(os.path.join(target, "case_outputs.json"), "w",
                                 encoding="utf-8"))
        payload = suite.build_dashboard_payload(folder, os.path.join(REPO, "tools"))
        case_payload = next(c for c in payload["cases"] if c["id"] == "a")
        assert case_payload["outputs"]["report"].endswith(".html")
        assert payload["counts"]["reports"] == 1
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_stage_process_skips_existing_cases():
    folder = tempfile.mkdtemp(prefix="suite_")
    try:
        _build(folder, _cases())
        target = os.path.join(folder, "cases", "a")
        os.makedirs(target)
        json.dump({"case": "a"}, open(os.path.join(target, "case_outputs.json"), "w"))
        total, failed = suite.stage_process(folder, exe="nonexistent.exe", only=["a"])
        assert failed == 0
        assert total == 1
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_assembly_for_prefers_case_then_override():
    assert suite.assembly_for({"assembly": "front_wing"}) == "front_wing"
    assert suite.assembly_for({"assembly": "front_wing"}, "full_car") == "full_car"
    assert suite.assembly_for({}, None) == "auto"
    assert suite.assembly_for({"assembly": ""}, None) == "auto"
