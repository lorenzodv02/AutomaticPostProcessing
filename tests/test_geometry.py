# -*- coding: utf-8 -*-
"""Geometria per tutti gli assiemi: famiglia, ali, parti, half car."""
import math
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from meta_driver.geometry import (  # noqa: E402
    extract_geometry, floor_profile, is_floor_zone, summarize, wing_summary, zone_family,
    zone_descriptors,
)


def _plate_mesh(name="front_main", span=0.5, chord=0.3, x0=0.5, y=0.2, offset_z=0.1):
    """Piastra orizzontale: quads su una griglia x/z."""
    nx, nz = 2, 10
    xs = np.linspace(x0, x0 + chord, nx + 1)
    zs = np.linspace(offset_z, offset_z + span, nz + 1)
    p0, p1, p2, p3 = [], [], [], []
    for i in range(nx):
        for j in range(nz):
            p0.append([xs[i], y, zs[j]])
            p1.append([xs[i + 1], y, zs[j]])
            p2.append([xs[i + 1], y, zs[j + 1]])
            p3.append([xs[i], y, zs[j + 1]])
    return {
        1: {"id": 1, "name": name, "n_faces": len(p0),
            "p0": np.array(p0, dtype=np.float32), "p1": np.array(p2, dtype=np.float32),
            "p2": np.array(p1, dtype=np.float32), "p3": np.array(p3, dtype=np.float32),
            "areas": np.full(len(p0), 0.001, dtype=np.float32),
            "bbox": {"xmin": x0, "xmax": x0 + chord, "ymin": y, "ymax": y,
                     "zmin": offset_z, "zmax": offset_z + span}},
    }


def _floor_mesh(angle_deg=10.0, start=1.5, end=2.5, base=0.040, name="flat_floor"):
    nx, nz = 20, 4
    xs = np.linspace(0.5, 2.7, nx + 1)
    zs = np.linspace(0.1, 0.6, nz + 1)
    slope = math.tan(math.radians(angle_deg))

    def height(x):
        return base + max(0.0, x - start) * slope

    p0, p1, p2, p3 = [], [], [], []
    for i in range(nx):
        for j in range(nz):
            p0.append([xs[i], height(xs[i]), zs[j]])
            p1.append([xs[i + 1], height(xs[i + 1]), zs[j]])
            p2.append([xs[i + 1], height(xs[i + 1]), zs[j + 1]])
            p3.append([xs[i], height(xs[i]), zs[j + 1]])
    return {
        10: {"id": 10, "name": name, "n_faces": len(p0),
             "p0": np.array(p0, dtype=np.float32), "p1": np.array(p2, dtype=np.float32),
             "p2": np.array(p1, dtype=np.float32), "p3": np.array(p3, dtype=np.float32),
             "areas": np.full(len(p0), 0.01, dtype=np.float32),
             "bbox": {"xmin": 0.5, "xmax": 2.7, "ymin": base, "ymax": base + 0.3,
                      "zmin": 0.1, "zmax": 0.6}},
    }


def test_zone_family_all_assemblies():
    assert zone_family("front_main") == "ala anteriore"
    assert zone_family("front_tyre") == "gomme"
    assert zone_family("front_suspension") == "corpo"
    assert zone_family("swan_neck") == "corpo"
    assert zone_family("rear_main_down") == "ala posteriore"
    assert zone_family("flat_floor") == "fondo"
    assert zone_family("chassis") == "corpo"
    assert zone_family("qualcosa") == "altro"


def test_wing_summary_from_plate():
    wing = wing_summary(_plate_mesh(), coord_scale=1.0, family="ala anteriore", half_car=False)
    assert wing["available"] is True
    assert abs(wing["span_m"] - 0.5) < 0.02, wing["span_m"]
    assert abs(wing["planform_m2"] - 0.15) < 0.03, wing["planform_m2"]
    assert abs(wing["chord_mean_m"] - 0.3) < 0.05, wing["chord_mean_m"]
    assert abs(wing["aspect_ratio"] - (0.25 / 0.15)) < 0.3, wing["aspect_ratio"]


def test_half_car_doubles_span_and_area_only():
    solid = wing_summary(_plate_mesh(), coord_scale=1.0, family="ala anteriore", half_car=False)
    half = wing_summary(_plate_mesh(), coord_scale=1.0, family="ala anteriore", half_car=True)
    assert abs(half["span_m"] - 2 * solid["span_m"]) < 0.02
    assert abs(half["planform_m2"] - 2 * solid["planform_m2"]) < 0.03
    # con apertura e area entrambe doppie l'allungamento raddoppia
    assert abs(half["aspect_ratio"] - 2 * solid["aspect_ratio"]) < 5e-3


def test_extract_geometry_parts_floor_and_wings():
    mesh = {}
    mesh.update(_floor_mesh())
    mesh.update({key + 100: value for key, value in _plate_mesh("front_main").items()})
    mesh.update({key + 200: value for key, value in _plate_mesh("rear_main", x0=2.6,
                                                                offset_z=0.2).items()})
    geometry = extract_geometry(mesh, {"ymin": 0.0}, coord_scale=1.0, assembly="full_car",
                                half_car=False)
    assert geometry["available"] is True
    assert set(geometry["parts"]) >= {"fondo", "ala anteriore", "ala posteriore"}
    assert geometry["wings"]["front"]["available"] is True
    assert geometry["wings"]["rear"]["available"] is True
    summary = geometry["summary"]
    assert summary["front_span_m"] > 0 and summary["rear_span_m"] > 0
    assert summary["area_fondo_m2"] > 0
    assert geometry["floor"]["available"] is True


def test_zone_descriptors_cover_all_zones():
    mesh = _floor_mesh()
    rows = zone_descriptors(mesh)
    assert rows[0]["family"] == "fondo"
    assert rows[0]["area_m2"] > 0
    assert rows[0]["chord_m"] > 0.5


def test_floor_profile_still_works_for_backward_compatibility():
    profile = floor_profile(_floor_mesh(angle_deg=10.0), {"ymin": 0.0}, stations=40)
    assert profile["available"] is True
    assert summarize(profile)["throat_h_m"] >= 0.03
