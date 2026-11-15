# -*- coding: utf-8 -*-
"""Aero Design Explorer: payload, modello leave-one-out, proposte, rendering."""
import csv
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import design_explorer as dx  # noqa: E402


def _write_dataset(folder, cases, pid_rows=None, excluded=()):
    header = ["case_id", "assieme", "cas_file", "dat_file", "iterazioni", "v_inf_ms",
              "half_car", "deportanza_N", "drag_N", "CL", "CD", "CL_A", "CD_A", "L_D",
              "cop_x_m", "cop_x_pct", "cop_passo_pct", "stallo_pct", "cp_min",
              "modello", "nota", "velocita_nominale_ms", "max_height_mm",
              "height_gola_mm", "pos_gola_mm", "pos_gola_pct_passo", "ala_post",
              "ala_ant", "diffusore", "excel_downforce_N", "excel_drag_N"]
    with open(os.path.join(folder, "dataset.csv"), "w", encoding="utf-8-sig",
              newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, delimiter=";")
        writer.writeheader()
        for case in cases:
            writer.writerow({key: case.get(key, "") for key in header})

    pid_header = ["case_id", "zone_name", "zone_id", "n_faces", "area_m2", "cp_min",
                  "cp_mean", "df_pressione_1x_N", "df_viscosa_1x_N", "df_1x_N",
                  "df_2x_N", "drag_pressione_1x_N", "drag_viscosa_1x_N", "drag_1x_N",
                  "drag_2x_N", "stallo_pct", "fonte_viscosa"]
    with open(os.path.join(folder, "dataset_pid.csv"), "w", encoding="utf-8-sig",
              newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=pid_header, delimiter=";")
        writer.writeheader()
        for row in (pid_rows or []):
            writer.writerow({key: row.get(key, "") for key in pid_header})

    if excluded:
        with open(os.path.join(folder, "escludi.txt"), "w", encoding="utf-8") as handle:
            handle.write("\n".join(excluded) + "\n")


def _case(case_id, dep, drag, maxh, gola, pos, wing="RW1", diff="Completo", ld=None):
    return {
        "case_id": case_id, "deportanza_N": dep, "drag_N": drag,
        "L_D": ld if ld is not None else round(dep / drag, 2),
        "max_height_mm": maxh, "height_gola_mm": gola, "pos_gola_mm": pos,
        "ala_post": wing, "diffusore": diff, "modello": case_id, "iterazioni": 1250,
    }


def _synthetic():
    # deportanza funzione lineare della sola altezza: gola e posizione fisse,
    # cosi' la relazione e' identificabile e il test misura davvero il modello
    cases = []
    for index, maxh in enumerate((220, 230, 240, 250, 260, 270, 280, 285, 225, 275)):
        cases.append(_case("c%d" % index, 2.0 * maxh, 200.0 + index, maxh,
                           40.0, 2100.0, wing="EW1"))
    pid_rows = []
    for case in cases:
        pid_rows.append({"case_id": case["case_id"], "zone_name": "chassis",
                         "df_2x_N": case["deportanza_N"] / 2.0})
        pid_rows.append({"case_id": case["case_id"], "zone_name": "flat_floor",
                         "df_2x_N": case["deportanza_N"] / 4.0})
    return cases, pid_rows


def test_payload_from_synthetic_dataset():
    folder = tempfile.mkdtemp(prefix="explorer_")
    try:
        cases, pid_rows = _synthetic()
        cases.append(_case("c10", 999.0, 300.0, 250, 50, 2100))
        _write_dataset(folder, cases, pid_rows, excluded=["c10"])
        payload = dx.build_payload(folder)
        assert payload["counts"]["cases"] == 10, payload["counts"]
        assert payload["excluded"] == ["c10"]
        assert payload["noise_n"] > 0
        assert payload["model"]["available"] is True
        # relazione lineare: il modello la trova (leave-one-out con lambda scelto)
        dep_fit = payload["model"]["targets"]["dep"]
        assert dep_fit["rmse"] < 5.0, dep_fit
        assert dep_fit["r2"] > 0.99, dep_fit
        assert "lambda" in dep_fit
        assert len(payload["proposals"]) == 5
        case_c0 = next(c for c in payload["cases"] if c["id"] == "c0")
        assert payload["zones"]["c0"]["chassis"] == case_c0["dep"] / 2.0
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_model_unavailable_with_few_cases():
    folder = tempfile.mkdtemp(prefix="explorer_")
    try:
        cases, pid_rows = _synthetic()
        _write_dataset(folder, cases[:4], pid_rows[:8])
        payload = dx.build_payload(folder)
        assert payload["model"]["available"] is False
        assert "8" in payload["model"]["reason"]
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_proposals_inside_the_sampled_box():
    folder = tempfile.mkdtemp(prefix="explorer_")
    try:
        cases, pid_rows = _synthetic()
        _write_dataset(folder, cases, pid_rows)
        payload = dx.build_payload(folder)
        heights = [c["max_height_mm"] for c in cases]
        for proposal in payload["proposals"]:
            for key, bound in (("max_h", heights), ("gola", [c["height_gola_mm"] for c in cases]),
                               ("pos", [c["pos_gola_mm"] for c in cases])):
                assert min(bound) <= proposal[key] <= max(bound), (key, proposal[key])
            assert proposal["wing"] == "EW1"
            assert proposal["distance"] >= 0
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_render_replaces_placeholder_only():
    folder = tempfile.mkdtemp(prefix="explorer_")
    try:
        template = os.path.join(folder, "t.html")
        with open(template, "w", encoding="utf-8") as handle:
            handle.write("<html><script>D=__PAYLOAD__;</script></html>")
        html = dx.render({"cases": [1, 2], "noise_n": 1.0}, template)
        assert "__PAYLOAD__" not in html
        assert '"noise_n":1.0' in html.replace(" ", "")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_loo_validate_detects_wrong_model():
    rows = [[0.0], [1.0], [2.0], [3.0]]
    good = dx.loo_validate(rows, [0.0, 1.0, 2.0, 3.0], lam=0.0)
    bad = dx.loo_validate(rows, [0.0, 1.0, 2.0, 100.0], lam=0.0)
    assert good["rmse"] < 1e-9, good
    assert bad["rmse"] > 10, bad
