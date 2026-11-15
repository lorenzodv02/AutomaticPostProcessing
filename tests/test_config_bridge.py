# -*- coding: utf-8 -*-
"""Test del ponte di configurazione: le chiavi di config.yaml devono essere VIVE."""

import os

import yaml

import config_bridge as cb

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _real_config():
    with open(os.path.join(REPO_ROOT, "config.yaml"), "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_defaults_match_config_file():
    """I default non devono piu' divergere dai valori del file (16.67 vs 14, 1.0 vs 1.08)."""
    merged = cb.merge_config({})
    refs = merged["reference_values"]
    assert refs["velocity_inf"] == 14.0
    assert refs["reference_area"] == 1.08
    assert refs["density_air"] == 1.225


def test_keywords_are_additive():
    """Le keyword del file si sommano al fallback storico: nessun PID gia' noto va perso."""
    config = _real_config()
    include, exclude = cb.assembly_keywords(config, "undertray")
    assert "diffusore" in include       # solo dal fallback storico
    assert "tunnel" in include          # solo dal config.yaml
    assert "flat_floor" in include
    assert "chassis" in exclude


def test_undertray_zone_selection_regression():
    """I PID reali del modello (flat_floor, diffusore_int, venturi*) restano selezionati."""
    config = _real_config()
    include, exclude = cb.assembly_keywords(config, "undertray")
    zones = ["flat_floor", "diffusore_int", "venturi", "venturi_endplate", "front_main", "rear_main", "tyre"]

    selected = [zone for zone in zones if not any(key in zone for key in exclude)]
    selected = [zone for zone in selected if any(key in zone for key in include)]

    assert selected == ["flat_floor", "diffusore_int", "venturi", "venturi_endplate"], selected


def test_thresholds_come_from_config():
    config = _real_config()
    undertray = cb.thresholds(config, "undertray")
    assert undertray["max_acceptable_stall_pct"] == 8.0
    assert undertray["critical_stall_pct"] == 18.0
    front = cb.thresholds(config, "front_wing")
    assert front["max_acceptable_stall_pct"] == 6.0
    assert front["critical_stall_pct"] == 14.0


def test_thresholds_override_and_fallback():
    custom = {"assemblies": {"undertray": {"thresholds": {"critical_stall_pct": 12.0}}}}
    resolved = cb.thresholds(custom, "undertray")
    assert resolved["critical_stall_pct"] == 12.0
    assert resolved["max_acceptable_stall_pct"] == cb.DEFAULT_THRESHOLDS["max_acceptable_stall_pct"]

    broken = {"assemblies": {"undertray": {"thresholds": {"critical_stall_pct": "non-numerico"}}}}
    assert cb.thresholds(broken, "undertray")["critical_stall_pct"] == cb.DEFAULT_THRESHOLDS["critical_stall_pct"]


def test_cp_range_is_per_assembly():
    config = _real_config()
    assert cb.cp_range(config, "undertray") == (-3.5, 1.0)
    assert cb.cp_range(config, "front_wing") == (-4.0, 1.0)
    assert cb.cp_range({}, "undertray") == cb.DEFAULT_CP_RANGE
    assert cb.cp_range({"assemblies": {"undertray": {"cp_range": [1.0, -1.0]}}}, "undertray") == cb.DEFAULT_CP_RANGE


def test_cut_stations_are_sanitized():
    """Le stazioni > 1.0 cadono fuori dal bounding box e vengono scartate."""
    config = _real_config()
    x_stations, z_stations = cb.cut_stations(config, "undertray")
    assert all(0.0 < value <= 1.0 for value in x_stations)
    assert 1.05 not in x_stations
    assert x_stations == sorted(x_stations)
    assert len(x_stations) >= 2
    assert all(0.0 < value <= 1.0 for value in z_stations)

    # Assieme sconosciuto o config parziale: griglia canonica
    fallback_x, _ = cb.cut_stations({}, "sconosciuto")
    assert fallback_x == cb.DEFAULT_X_STATIONS

    # Config troppo povera: si usa il fallback invece di disegnare 1 sola sezione
    poor = {"assemblies": {"undertray": {"x_cuts_normalized": [0.5]}}}
    assert cb.cut_stations(poor, "undertray")[0] == cb.DEFAULT_X_STATIONS


def test_removed_dead_keys_are_gone():
    """Le chiavi che nessun codice leggeva (e che confondevano) sono state rimosse dal file."""
    config = _real_config()
    for assembly in ("undertray", "front_wing", "rear_wing", "full_car"):
        profile = config["assemblies"][assembly]
        assert "y_cuts_normalized" not in profile
        assert "primary_suction_view" not in profile


def test_unwired_keys_are_declared_as_documentation():
    """coordinate_system/fluent_variables/wheelbase restano come documentazione, non come promesse."""
    config = _real_config()
    assert "fluent_variables" in config
    assert "coordinate_system" in config
    assert config["reference_values"]["wheelbase"] == 1.535
