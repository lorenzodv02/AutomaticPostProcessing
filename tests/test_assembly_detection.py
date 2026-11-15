# -*- coding: utf-8 -*-
"""Rilevamento dell'assieme dai nomi delle zone (niente "tutto undertray")."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from meta_driver.fluent_parser import detect_assembly_from_names  # noqa: E402


def test_full_car_when_floor_and_wings_are_present():
    names = ["flat_floor", "venturi_first", "diffusore_int", "chassis",
             "front_main", "front_second_ext", "rear_main_down", "rear_first"]
    assert detect_assembly_from_names(names) == "full_car"


def test_single_families():
    assert detect_assembly_from_names(["flat_floor", "diffusore_int"]) == "undertray"
    assert detect_assembly_from_names(["front_main", "front_second_int"]) == "front_wing"
    assert detect_assembly_from_names(["rear_main", "rear_endplate"]) == "rear_wing"


def test_wheels_and_suspension_are_not_wings():
    names = ["front_tyre", "rear_tyre", "front_suspension", "rear_suspension",
             "flat_floor", "venturi_first"]
    assert detect_assembly_from_names(names) == "undertray"


def test_unknown_names_fall_back_to_full_car():
    assert detect_assembly_from_names(["chassis", "pilota", "zed"]) == "full_car"
    assert detect_assembly_from_names([]) == "full_car"
