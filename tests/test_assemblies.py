# -*- coding: utf-8 -*-
"""Assiemi: normalizzazione, priorita' di scelta, default auto."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from meta_driver.assemblies import (  # noqa: E402
    ASSEMBLY_CHOICES, is_specific, normalize_assembly, resolve_assembly,
)


def test_normalize_and_aliases():
    assert normalize_assembly("FULL_CAR") == "full_car"
    assert normalize_assembly(" vettura completa ") == "full_car"
    assert normalize_assembly("ala anteriore") == "front_wing"
    assert normalize_assembly("fondo") == "undertray"
    assert normalize_assembly("auto") == "auto"
    assert normalize_assembly("") == ""
    assert normalize_assembly(None) == ""
    assert normalize_assembly("boh") == ""


def test_priority_override_then_case_then_auto():
    # override esplicito vince su tutto (anche auto)
    assert resolve_assembly(override="full_car", case_assembly="undertray") == "full_car"
    assert resolve_assembly(override="auto", case_assembly="full_car") == "auto"
    # senza override decide la riga del dataset
    assert resolve_assembly(case_assembly="front_wing") == "front_wing"
    # senza nulla: auto, NON undertray
    assert resolve_assembly() == "auto"
    assert resolve_assembly(config_assembly="auto") == "auto"


def test_specific_means_not_auto():
    assert is_specific("full_car") is True
    assert is_specific("auto") is False
    assert is_specific("") is False


def test_choices_include_auto_first():
    assert ASSEMBLY_CHOICES[0][0] == "auto"
    values = [value for value, _label in ASSEMBLY_CHOICES]
    assert set(values) == {"auto", "undertray", "front_wing", "rear_wing", "full_car"}
