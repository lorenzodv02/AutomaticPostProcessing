# -*- coding: utf-8 -*-
"""Geometria del fondo dalla mesh: profilo, salita, ladder, casi limite."""
import math
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from meta_driver.geometry import (  # noqa: E402
    find_ramp, floor_profile, is_floor_zone, summarize, zone_ladder,
)


def _floor_mesh(angle_deg=10.0, start=1.5, end=2.5, base=0.040, name="flat_floor"):
    """
    Fondo piatto a `base` metri fino a `start`, poi rampa di `angle_deg` fino a
    `end`. Griglia di quad nella direzione x (20 colonne) e z (4 colonne).
    """
    nx, nz = 20, 4
    xs = np.linspace(0.5, 2.7, nx + 1)
    zs = np.linspace(0.1, 0.6, nz + 1)
    slope = math.tan(math.radians(angle_deg))

    def height(x):
        return base + (max(0.0, x - start) * slope)

    p0, p1, p2, p3 = [], [], [], []
    for i in range(nx):
        for j in range(nz):
            x0, x1 = xs[i], xs[i + 1]
            z0, z1 = zs[j], zs[j + 1]
            p0.append([x0, height(x0), z0])
            p1.append([x1, height(x1), z0])
            p2.append([x1, height(x1), z1])
            p3.append([x0, height(x0), z1])
    # normali verso il basso: inverto l'ordine dei vertici
    return {
        1: {
            "id": 1, "name": name, "n_faces": len(p0),
            "p0": np.array(p0, dtype=np.float32), "p1": np.array(p2, dtype=np.float32),
            "p2": np.array(p1, dtype=np.float32), "p3": np.array(p3, dtype=np.float32),
            "areas": np.full(len(p0), 0.01, dtype=np.float32),
            "bbox": {"xmin": 0.5, "xmax": 2.7, "ymin": 0.04, "ymax": 0.2,
                     "zmin": 0.1, "zmax": 0.6},
        }
    }


def test_floor_profile_detects_flat_floor_and_ramp():
    mesh = _floor_mesh(angle_deg=10.0)
    profile = floor_profile(mesh, {"ymin": 0.0}, coord_scale=1.0, stations=40)
    assert profile["available"] is True
    assert abs(profile["h_min_m"][0] - 0.040) < 0.002, profile["h_min_m"][:3]
    assert profile["rise_kind"] == "diffusore", profile["rise_kind"]
    assert 8.0 <= profile["rise_angle_deg"] <= 12.0, profile["rise_angle_deg"]
    assert profile["expansion_ratio"] > 1.5, profile["expansion_ratio"]
    assert profile["floor_area_m2"] > 0.5


def test_floor_profile_marks_steep_step_as_cascade():
    mesh = _floor_mesh(angle_deg=60.0, start=1.0, end=1.2)
    profile = floor_profile(mesh, {"ymin": 0.0}, coord_scale=1.0, stations=40)
    assert profile["rise_kind"] == "gradino/cascata", profile.get("rise_kind")


def test_find_ramp_on_synthetic_curve():
    x = np.linspace(0.0, 1.0, 21)
    h = np.where(x < 0.5, 0.04, 0.04 + (x - 0.5) * math.tan(math.radians(12.0)))
    ramp = find_ramp(x, h)
    assert ramp["kind"] == "diffusore"
    assert 10.0 <= ramp["angle_deg"] <= 14.0
    assert ramp["x_start_m"] >= 0.45


def test_find_ramp_returns_none_on_flat_surface():
    x = np.linspace(0.0, 1.0, 11)
    h = np.full_like(x, 0.04)
    ramp = find_ramp(x, h)
    assert ramp["angle_deg"] is None and ramp["kind"] is None


def test_zone_ladder_and_family_filter():
    assert is_floor_zone("flat_floor") and is_floor_zone("diffusore_int")
    assert is_floor_zone("venturi_first") and not is_floor_zone("chassis")
    ladder = zone_ladder(_floor_mesh())
    assert len(ladder) == 1
    assert ladder[0]["zone"] == "flat_floor"
    assert ladder[0]["area_m2"] > 0.0
    assert ladder[0]["x_min_m"] < ladder[0]["x_max_m"]


def test_floor_profile_without_floor_zones():
    mesh = {1: {"id": 1, "name": "chassis", "n_faces": 1,
                "p0": np.zeros((1, 3)), "p1": np.zeros((1, 3)),
                "p2": np.zeros((1, 3)), "p3": np.zeros((1, 3)),
                "areas": np.zeros(1), "bbox": {}}}
    profile = floor_profile(mesh, {"ymin": 0.0})
    assert profile["available"] is False
    assert "fondo" in profile["reason"]
    assert summarize(profile) == {}
