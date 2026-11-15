# -*- coding: utf-8 -*-
"""Gli script di estrazione in blocco devono funzionare senza dipendenze."""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "batch"))

import batch_extract  # noqa: E402
import make_tables  # noqa: E402


def _make_tree(base):
    """Venturi/analisi 1/{cas,dat} + un caso piatto + una cartella da ignorare."""
    nested = os.path.join(base, "Venturi", "analisi 1")
    os.makedirs(nested)
    open(os.path.join(nested, "prova.cas"), "wb").close()
    open(os.path.join(nested, "prova.dat"), "wb").close()

    flat = os.path.join(base, "caso_piatto")
    os.makedirs(flat)
    open(os.path.join(flat, "x.CAS"), "wb").close()
    open(os.path.join(flat, "x.DAT"), "wb").close()

    # cartella con solo il .cas: non e' un caso
    half = os.path.join(base, "solo_cas")
    os.makedirs(half)
    open(os.path.join(half, "y.cas"), "wb").close()

    # cartella di output: va ignorata anche se contiene file
    ignored = os.path.join(base, "output_diagnostics")
    os.makedirs(ignored)
    open(os.path.join(ignored, "z.cas"), "wb").close()
    open(os.path.join(ignored, "z.dat"), "wb").close()
    return nested, flat


def test_find_case_dirs_is_recursive_and_ignores_output():
    base = tempfile.mkdtemp(prefix="batch_tree_")
    try:
        nested, flat = _make_tree(base)
        found = batch_extract.find_case_dirs(base, os.path.join(base, "_dati"))
        assert nested in found, found
        assert flat in found, found
        assert len(found) == 2, found
        assert not any("output_diagnostics" in path for path in found), found
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_case_id_is_stable_and_safe():
    base = tempfile.mkdtemp(prefix="batch_id_")
    try:
        nested, _flat = _make_tree(base)
        case_id = batch_extract.case_id_for(nested, base)
        assert case_id == "Venturi__analisi_1", case_id
        assert " " not in case_id
        # stesso risultato a ogni chiamata, anche con root diverse
        assert batch_extract.case_id_for(nested, base) == case_id
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_make_tables_reads_extracted_json():
    base = tempfile.mkdtemp(prefix="batch_tables_")
    try:
        payload = {
            "assembly_type": "full_car",
            "physics_data": {
                "summary_kpis": {
                    "downforce_total_N": 483.1, "drag_total_N": 222.7,
                    "velocity_inf_ms": 14.0, "is_half_car_symmetric": True,
                    "efficiency_l_d": 2.17,
                },
                "per_pid_breakdown": [
                    {"zone_name": "flat_floor", "zone_id": 3, "downforce_2x_N": 5.7,
                     "drag_2x_N": 0.5, "n_faces": 10, "area_m2": 0.1},
                ],
            },
            "config": {"reference_values": {"velocity_inf": 14}},
        }
        with open(os.path.join(base, "001_base.json"), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

        cases = make_tables.load_cases(base)
        assert len(cases) == 1
        assert cases[0]["case_id"] == "001_base"
        assert cases[0]["pids"][0]["zone_name"] == "flat_floor"

        # un JSON rotto non deve interrompere la lettura degli altri
        with open(os.path.join(base, "002_rotto.json"), "w", encoding="utf-8") as handle:
            handle.write("{ non json")
        assert len(make_tables.load_cases(base)) == 1
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_batch_scripts_have_no_third_party_imports():
    """Devono girare su un PC con solo Python: niente numpy/pandas."""
    for name in ("batch_extract.py", "make_tables.py", "check_dataset.py"):
        text = open(os.path.join(REPO, "batch", name), encoding="utf-8").read()
        for forbidden in ("import numpy", "import pandas", "import openpyxl", "import matplotlib"):
            assert forbidden not in text, (name, forbidden)
