# -*- coding: utf-8 -*-
"""Launcher: menu, singolo caso, geometria, scelte annidate."""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from meta_driver import launcher_menu  # noqa: E402


def _prompt_from(answers):
    queue = list(answers)

    def prompt(text=""):
        if not queue:
            raise EOFError
        return queue.pop(0)

    return prompt


def _picker(folders):
    queue = list(folders)

    def picker(title=""):
        return queue.pop(0) if queue else ""

    return picker


def test_menu_exits_on_zero():
    code = launcher_menu.run_launcher({}, None, pipeline=lambda *a, **k: {},
                                      prompt=_prompt_from(["0"]))
    assert code == 0


def test_menu_invalid_choice_reprompts_then_exits():
    code = launcher_menu.run_launcher({}, None, pipeline=lambda *a, **k: {},
                                      prompt=_prompt_from(["x", "0"]))
    assert code == 0


def test_single_case_calls_pipeline_with_folder():
    calls = {}

    def pipeline(config, workspace_dir=None, force_meta_batch=True):
        calls["dir"] = workspace_dir
        calls["meta"] = force_meta_batch
        calls["assembly"] = (config.get("project") or {}).get("assembly_type")
        return {"reports": {"html_report": "C:/out/report.html"}}

    folder = tempfile.mkdtemp(prefix="launcher_")
    try:
        code = launcher_menu.run_launcher(
            {"project": {"assembly_type": "full_car"}}, None,
            pipeline=pipeline,
            prompt=_prompt_from(["1", "", "0"]),   # scelta, META non saltato, esci
            folder_picker=_picker([folder]))
        assert code == 0
        assert calls["dir"] == folder
        assert calls["meta"] is True
    finally:
        import shutil

        shutil.rmtree(folder, ignore_errors=True)


def test_single_case_can_skip_meta():
    calls = {}

    def pipeline(config, workspace_dir=None, force_meta_batch=True):
        calls["meta"] = force_meta_batch
        return {"reports": {}}

    folder = tempfile.mkdtemp(prefix="launcher_")
    try:
        launcher_menu.run_launcher(
            {}, None, pipeline=pipeline,
            prompt=_prompt_from(["1", "s", "0"]),
            folder_picker=_picker([folder]))
        assert calls["meta"] is False
    finally:
        import shutil

        shutil.rmtree(folder, ignore_errors=True)


def test_geometry_option_calls_geometry(monkeypatch=None):
    seen = {}

    def fake_geometry(cfg, folder, assembly=None):
        seen["dir"] = folder
        return {"payload": {"case": "X", "summary": {}, "geometry": {"zones": [], "floor": {}}},
                "path": "out/geometry.json"}

    original = launcher_menu.geometry_for_workspace if hasattr(launcher_menu, "geometry_for_workspace") else None
    # la funzione viene importata dentro il menu: la si sostituisce nel modulo suite_mode
    import meta_driver.suite_mode as suite_mode

    saved = suite_mode.geometry_for_workspace
    suite_mode.geometry_for_workspace = fake_geometry
    folder = tempfile.mkdtemp(prefix="launcher_")
    try:
        code = launcher_menu.run_launcher({}, None, pipeline=lambda *a, **k: {},
                                          prompt=_prompt_from(["4", "0"]),
                                          folder_picker=_picker([folder]))
        assert code == 0
        assert seen.get("dir") == folder
    finally:
        suite_mode.geometry_for_workspace = saved
        import shutil

        shutil.rmtree(folder, ignore_errors=True)


def test_assembly_choice_defaults_to_full_car():
    assert launcher_menu._ask_assembly(_prompt_from([""])) == "full_car"
    assert launcher_menu._ask_assembly(_prompt_from(["1"])) == "undertray"
    assert launcher_menu._ask_assembly(_prompt_from(["9"])) == "full_car"


def test_yes_answers():
    assert launcher_menu._ask_yes(_prompt_from(["s"]), "?", False) is True
    assert launcher_menu._ask_yes(_prompt_from(["n"]), "?", True) is False
    assert launcher_menu._ask_yes(_prompt_from([""]), "?", True) is True
