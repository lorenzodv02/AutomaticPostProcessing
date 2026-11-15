# -*- coding: utf-8 -*-
"""Gli script di estrazione in blocco devono funzionare senza dipendenze."""
import json
import os
import re
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


def _case_files(base, name, files):
    case = os.path.join(base, name)
    os.makedirs(case)
    for item in files:
        open(os.path.join(case, item), "wb").close()
    return case


def test_pick_inputs_prefers_iteration_files():
    """Con file di partenza e file iterati nella stessa cartella, sceglie gli iterati."""
    base = tempfile.mkdtemp(prefix="batch_pick_")
    try:
        case = _case_files(base, "analisi 1", [
            "base.cas", "base.dat", "nome_1_iterazioni.cas", "nome_1_iterazioni.dat",
        ])
        pattern = re.compile(batch_extract.DEFAULT_ITER_PATTERN, re.IGNORECASE)
        choice = batch_extract.pick_inputs(case, pattern)
        assert choice["stato"] == "OK"
        assert choice["cas"] == "nome_1_iterazioni.cas"
        assert choice["dat"] == "nome_1_iterazioni.dat"
        # ci sono altri file: la coppia va isolata per non sbagliare file
        assert choice["modo"] == "isolato"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_pick_inputs_scarta_i_file_di_partenza():
    base = tempfile.mkdtemp(prefix="batch_pick_")
    try:
        case = _case_files(base, "base_only", ["avvio.cas", "avvio.dat"])
        pattern = re.compile(batch_extract.DEFAULT_ITER_PATTERN, re.IGNORECASE)
        choice = batch_extract.pick_inputs(case, pattern)
        assert choice["stato"] == "SCARTATO"
        assert not choice["cas"] and not choice["dat"]
        assert "iterazion" in choice["motivo"].lower()
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_pick_inputs_in_place_when_only_iteration_pair():
    base = tempfile.mkdtemp(prefix="batch_pick_")
    try:
        case = _case_files(base, "solo_iterati", ["nome_1_iterazioni.cas", "nome_1_iterazioni.dat"])
        pattern = re.compile(batch_extract.DEFAULT_ITER_PATTERN, re.IGNORECASE)
        choice = batch_extract.pick_inputs(case, pattern)
        assert choice["stato"] == "OK"
        assert choice["modo"] == "in_place"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_isolated_run_dir_uses_links_and_is_removed():
    """L'isolamento non deve copiare i GB: hardlink, e la cartella sparisce dopo."""
    base = tempfile.mkdtemp(prefix="batch_iso_")
    try:
        case = _case_files(base, "analisi 1", [
            "base.cas", "base.dat", "nome_1_iterazioni.cas", "nome_1_iterazioni.dat",
        ])
        pattern = re.compile(batch_extract.DEFAULT_ITER_PATTERN, re.IGNORECASE)
        choice = batch_extract.pick_inputs(case, pattern)
        run_dir = batch_extract.prepare_run_dir(case, choice)
        assert os.path.basename(run_dir) == batch_extract.ISOLATED_DIR
        assert sorted(os.listdir(run_dir)) == ["nome_1_iterazioni.cas", "nome_1_iterazioni.dat"]
        # il contenuto e' lo stesso file, non una copia (stesso inode su NTFS)
        source = os.path.join(case, "nome_1_iterazioni.cas")
        if hasattr(os.stat(source), "st_ino") and os.stat(source).st_ino:
            assert os.stat(source).st_ino == os.stat(os.path.join(run_dir, "nome_1_iterazioni.cas")).st_ino
        batch_extract.remove_run_dir(case, choice, keep_reports=False)
        assert not os.path.exists(run_dir)
        # gli originali restano
        assert os.path.isfile(source)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_find_case_dirs_ignores_underscore_folders():
    base = tempfile.mkdtemp(prefix="batch_skip_")
    try:
        _case_files(base, "buono", ["a.cas", "a.dat"])
        _case_files(base, "_solo_iterazioni", ["a.cas", "a.dat"])
        _case_files(base, "_dati_batch", ["a.cas", "a.dat"])
        found = batch_extract.find_case_dirs(base, os.path.join(base, "_dati_batch"))
        assert len(found) == 1, found
        assert found[0].endswith("buono")
    finally:
        shutil.rmtree(base, ignore_errors=True)

def test_pick_inputs_handles_real_naming_convention():
    """Nomi reali: V14_3 e' il file di partenza, V14_3-1-01250 e' l'iterato."""
    base = tempfile.mkdtemp(prefix="batch_real_")
    try:
        pattern = re.compile(batch_extract.DEFAULT_ITER_PATTERN, re.IGNORECASE)

        case = _case_files(base, "con_entrambi", [
            "V14_3.cas", "V14_3.dat", "V14_3-1-01250.cas", "V14_3-1-01250.dat",
        ])
        choice = batch_extract.pick_inputs(case, pattern)
        assert choice["stato"] == "OK"
        assert choice["cas"] == "V14_3-1-01250.cas"
        assert choice["dat"] == "V14_3-1-01250.dat"
        assert choice["modo"] == "isolato"

        solo = _case_files(base, "solo_iterato", ["V14_3-1-01250.cas", "V14_3-1-01250.dat"])
        assert batch_extract.pick_inputs(solo, pattern)["modo"] == "in_place"

        partenza = _case_files(base, "solo_partenza", ["V14_3.cas", "V14_3.dat"])
        assert batch_extract.pick_inputs(partenza, pattern)["stato"] == "SCARTATO"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_pick_inputs_marks_ambiguous_and_takes_newest():
    """Con due iterazioni sceglie la piu' recente e lo dichiara."""
    base = tempfile.mkdtemp(prefix="batch_amb_")
    try:
        case = _case_files(base, "due_iterazioni", [
            "V14_3-1-01250.cas", "V14_3-1-01250.dat",
            "V14_3-2-01250.cas", "V14_3-2-01250.dat",
        ])
        old = os.path.join(case, "V14_3-1-01250.cas")
        new = os.path.join(case, "V14_3-2-01250.cas")
        os.utime(old, (1_600_000_000, 1_600_000_000))
        os.utime(new, (1_700_000_000, 1_700_000_000))
        pattern = re.compile(batch_extract.DEFAULT_ITER_PATTERN, re.IGNORECASE)
        choice = batch_extract.pick_inputs(case, pattern)
        assert choice["stato"] == "AMBIGUO"
        assert choice["cas"] == "V14_3-2-01250.cas"
        assert "-1-" in choice["motivo"] and "-2-" in choice["motivo"]
    finally:
        shutil.rmtree(base, ignore_errors=True)
