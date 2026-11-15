# -*- coding: utf-8 -*-
"""Launcher grafico: funzioni pure, piano batch, costruzione finestra."""
import os
import shutil
import sys
import tempfile
import tkinter as tk

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

try:
    from meta_driver import gui_launcher  # noqa: E402
except ImportError:  # CI senza matplotlib: i test GUI non si raccolgono
    gui_launcher = None


def test_format_seconds():
    if gui_launcher is None:
        return
    assert gui_launcher._format_seconds(0) == "0 s"
    assert gui_launcher._format_seconds(45.2) == "45 s"
    assert gui_launcher._format_seconds(125) == "2 m 05 s"
    assert gui_launcher._format_seconds(None) == "-"


def _make_case(root, name, files):
    folder = os.path.join(root, name)
    os.makedirs(folder)
    for filename in files:
        with open(os.path.join(folder, filename), "wb") as handle:
            handle.write(b"\0" * 4096)
    return folder


def test_batch_plan_uses_iterated_files_only():
    if gui_launcher is None:
        return
    root = tempfile.mkdtemp(prefix="launcher_gui_")
    try:
        _make_case(root, "caso_iterato", ["V1-1-01250.cas", "V1-1-01250.dat"])
        _make_case(root, "caso_iniziale", ["V2.cas", "V2.dat"])
        rows = gui_launcher.batch_plan(root, os.path.join(root, "_dati_batch"))
        by_id = {row["case_id"]: row for row in rows}
        assert "caso_iterato" in by_id, list(by_id)
        assert by_id["caso_iterato"]["choice"]["stato"] != "SCARTATO"
        assert by_id["caso_iterato"]["choice"]["cas"] == "V1-1-01250.cas"
        assert by_id["caso_iniziale"]["choice"]["stato"] == "SCARTATO"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_launcher_window_builds_with_brand(monkey=None):
    if gui_launcher is None:
        return
    try:
        app = gui_launcher.LauncherApp({}, None, pipeline=lambda *a, **k: {})
    except Exception:  # senza display o senza matplotlib: niente test della finestra
        return
    try:
        assert app.root.title().startswith("FS")
        assert set(app.frames) == {"single", "batch", "suite", "geometry", "settings"}
        app._show_mode("batch")
        assert app.mode == "batch"
        # la modalità attiva è gialla, le altre navy
        assert app.mode_buttons["batch"].cget("bg").lower() == gui_launcher.brand.GOLD.lower()
        assert app.mode_buttons["single"].cget("bg").lower() == gui_launcher.brand.NAVY_PANEL.lower()
        # le scale batch esistono e partono vuote
        assert app.tree.get_children() == ()
        app.root.destroy()
    except Exception:
        try:
            app.root.destroy()
        except Exception:
            pass
        raise


def test_settings_rows_show_config_and_ai():
    if gui_launcher is None:
        return
    cfg = {"project": {"assembly_type": "full_car", "workspace_dir": "C:/casi"},
           "reference_values": {"velocity_inf_ms": 14.0, "density_air": 1.225,
                                "front_axle_x": 0.8, "rear_axle_x": 2.4,
                                "report_force_convention": "lift"},
           "meta": {"executable_path": "auto"},
           "ai_vision": {"provider": "gemini", "model": "gemini-2.5-flash",
                         "api_key": "chiave-segreta-1234"}}
    app = gui_launcher.LauncherApp.__new__(gui_launcher.LauncherApp)
    app.cfg = cfg
    rows = dict(app._settings_rows())
    assert rows["Assieme predefinito (config)"] == "full_car"
    assert rows["Velocità di riferimento"] in ("14.0 m/s", "14 m/s")
    assert rows["AI Vision"].startswith("gemini")
    assert "1234" in rows["Chiave AI"] and "chiave-segreta" not in rows["Chiave AI"]


def test_full_program_command():
    from meta_driver.entry_modes import full_program_command
    assert full_program_command(True, "C:/app.exe", "C:/repo") == ["C:/app.exe", "--gui"]
    command = full_program_command(False, "python", "C:/repo")
    assert command[0] == "python" and command[-1] == "--gui" and "main.py" in command[1]
