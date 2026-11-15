# -*- coding: utf-8 -*-
"""Modalita' `--suite` dell'exe: un solo pacchetto, niente Python esterno."""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from meta_driver import suite_mode  # noqa: E402


def test_bundle_roots_include_suite_and_tools():
    roots = suite_mode._bundle_roots()
    joined = "|".join(roots)
    assert "suite" in joined
    assert "tools" in joined
    assert REPO in roots
    # l'ordine mette prima i sorgenti del progetto
    assert roots[0] == REPO


def test_run_suite_without_dataset_returns_2():
    class Args:
        workspace = tempfile.mkdtemp(prefix="suite_mode_")
        force = False
        skip_process = True
        no_meta_batch = True
        only = None

    class Cfg(dict):
        pass

    try:
        code = suite_mode.run_suite(Cfg(), Args(), pipeline=lambda *a, **k: None)
        assert code == 2
    finally:
        import shutil

        shutil.rmtree(Args.workspace, ignore_errors=True)


def test_geometry_for_workspace_raises_without_cas():
    cfg = {"project": {"assembly_type": "full_car"}, "reference_values": {}}
    folder = tempfile.mkdtemp(prefix="suite_mode_")
    try:
        try:
            suite_mode.geometry_for_workspace(cfg, folder)
        except FileNotFoundError:
            return
        raise AssertionError("doveva sollevare FileNotFoundError")
    finally:
        import shutil

        shutil.rmtree(folder, ignore_errors=True)


def test_case_processor_sets_workspace_and_assembly():
    captured = {}

    def fake_pipeline(config, workspace_dir=None, force_meta_batch=True):
        captured["dir"] = workspace_dir
        captured["assembly"] = config["project"]["assembly_type"]
        captured["meta"] = force_meta_batch
        raise RuntimeError("stop qui: non serve eseguire la pipeline vera")

    process = suite_mode._case_processor(
        {"project": {"assembly_type": "undertray"}}, fake_pipeline, no_meta=True)
    try:
        process("C:/tmp/case", {"assembly": "full_car"})
    except RuntimeError:
        pass
    assert captured["dir"] == "C:/tmp/case"
    assert captured["assembly"] == "full_car"
    assert captured["meta"] is False
