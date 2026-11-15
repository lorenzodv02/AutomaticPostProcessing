# -*- coding: utf-8 -*-
"""
Test end-to-end del parser su un caso sintetico.

Copre il buco piu' pericoloso del progetto: il parser puo' sbagliare gli offset
in silenzio e ogni numero del report diventa falso. Qui i valori attesi sono
calcolati a mano (vedi `tests/fixtures.py`).
"""

import math
import shutil
import tempfile

import numpy as np

from meta_driver.fluent_parser import (
    inspect_fluent_cas_zones,
    extract_real_mesh_and_cfd_data,
)
from tests.fixtures import build_synthetic_case


def _quiet(*_args, **_kwargs):
    return None


def _extract(assembly="undertray", force_convention="lift", ref_values=None):
    folder = tempfile.mkdtemp(prefix="dsh_case_")
    cas_path, dat_path, expectations = build_synthetic_case(folder)
    result = extract_real_mesh_and_cfd_data(
        cas_path=cas_path,
        dat_path=dat_path,
        assembly_type=assembly,
        ref_values=ref_values,
        force_convention=force_convention,
        log_fn=_quiet,
    )
    return result, expectations, folder


def test_zone_table_is_read():
    folder = tempfile.mkdtemp(prefix="dsh_case_")
    try:
        cas_path, _dat, _exp = build_synthetic_case(folder)
        info = inspect_fluent_cas_zones(cas_path, requested_assembly="undertray")
        names = sorted(zone["name"] for zone in info["aero_zones"])
        assert names == ["flat_floor", "venturi"], names
        assert info["is_half_car_symmetric"] is False
        assert info["domain_zones"] == []
        target_names = sorted(zone["name"] for zone in info["target_zones"])
        assert target_names == ["flat_floor", "venturi"], target_names
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_mesh_counts_and_areas():
    result, expectations, folder = _extract()
    try:
        physics = result["physics_data"]
        assert physics["nodes_read"] == expectations["nodes"]
        assert physics["faces_read"] == expectations["faces"]

        zones = {zone["name"]: zone for zone in result["pid_breakdown"]}
        assert set(zones) == {"flat_floor", "venturi"}
        for name, expected_area in expectations["areas"].items():
            measured = zones[name]["area_m2"]
            assert math.isclose(measured, expected_area, rel_tol=1e-3), (name, measured)

        bbox = result["bounding_box"]
        assert math.isclose(bbox["dx"], 1.0, rel_tol=1e-3)
        assert math.isclose(bbox["dz"], 1.0, rel_tol=1e-3)
        assert math.isclose(bbox["dy"], 0.0, abs_tol=1e-4)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_normals_point_negative_y():
    """Le facce sono nel piano y=0 con vertici in senso orario visto da +Y."""
    result, _expectations, folder = _extract()
    try:
        for mesh in result["zone_meshes"].values():
            ny = mesh["normals"][:, 1]
            assert np.allclose(ny, -1.0, atol=1e-6), ny
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_forces_follow_the_documented_convention():
    """
    Convenzione documentata in `fluent_parser.SIGN_CONVENTION_NOTE`:
    F = p_rel * A * n. Con p = +100 Pa, A = 1.5 m^2 e n_y = -1 risulta F_y = -150 N,
    cioe' una spinta VERSO IL BASSO: coerente con "downforce_* negativo = deportanza".
    """
    result, expectations, folder = _extract()
    try:
        kpis = result["physics_data"]["summary_kpis"]
        assert math.isclose(kpis["downforce_N"], expectations["vertical_force_N"], rel_tol=1e-3), kpis["downforce_N"]
        assert kpis["downforce_N"] < 0.0
        assert math.isclose(kpis["vertical_force_y_N"], kpis["downforce_N"], rel_tol=1e-9)

        # L'integrale ricalcolato sulle stesse facce deve coincidere col KPI.
        integral = 0.0
        for mesh in result["zone_meshes"].values():
            integral += float(np.sum(mesh["pressure_pa"] * mesh["areas"] * mesh["normals"][:, 1]))
        assert math.isclose(integral, kpis["downforce_N"], abs_tol=0.1), integral
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_force_convention_downforce_inverts_the_signs():
    """
    Convenzione "downforce" (report Fluent definito come downforce): stesso
    modulo, segno invertito rispetto alla convenzione "lift" (default Fluent).
    """
    lift_res, expectations, folder_a = _extract(force_convention="lift")
    df_res, _expectations, folder_b = _extract(force_convention="downforce")
    try:
        lift = lift_res["physics_data"]["summary_kpis"]
        down = df_res["physics_data"]["summary_kpis"]

        assert lift["force_convention"] == "lift"
        assert down["force_convention"] == "downforce"

        assert math.isclose(down["downforce_N"], -lift["downforce_N"], rel_tol=1e-9)
        # la lift fisica (proiezione su +Y) non cambia con la convenzione
        assert math.isclose(down["lift_N"], lift["lift_N"], rel_tol=1e-9)
        assert math.isclose(down["downforce_N"], expectations["vertical_force_N"] * -1.0, rel_tol=1e-3)
        # i coefficienti e l'efficienza seguono la convenzione scelta
        assert math.isclose(down["CL_A"], -lift["CL_A"], rel_tol=1e-9)
        assert math.isclose(down["efficiency_L_over_D"], -lift["efficiency_L_over_D"], rel_tol=1e-9)
        # la somma per PID resta coerente con il KPI
        pid_sum = sum(p["downforce_2x_N"] for p in df_res["physics_data"]["per_pid_breakdown"])
        assert math.isclose(pid_sum, down["downforce_N"], abs_tol=0.5)
    finally:
        shutil.rmtree(folder_a, ignore_errors=True)
        shutil.rmtree(folder_b, ignore_errors=True)


def test_center_of_pressure_weights_only_downforce():
    """Il CoP pesa la sola deportanza: gli elementi in portanza non lo spostano."""
    from meta_driver.fluent_parser import center_of_pressure_x

    x = np.array([0.0, 1.0, 2.0])
    # elementi 0 e 1 spingono in basso (lift negativo), il 2 genera portanza
    cop = center_of_pressure_x(x, np.array([-100.0, -300.0, +500.0]))
    assert cop is not None
    assert math.isclose(cop, (0.0 * 100.0 + 1.0 * 300.0) / 400.0, rel_tol=1e-9)
    # nessuna deportanza -> None (il chiamante usa il centro geometrico)
    assert center_of_pressure_x(x, np.array([10.0, 20.0, 30.0])) is None


def test_drag_splits_pressure_and_viscous():
    result, expectations, folder = _extract()
    try:
        kpis = result["physics_data"]["summary_kpis"]
        assert math.isclose(kpis["drag_pressure_total_N"], expectations["drag_pressure_N"], abs_tol=1e-3)
        assert math.isclose(kpis["drag_viscous_total_N"], expectations["drag_viscous_N"], rel_tol=1e-3)
        assert math.isclose(
            kpis["drag_total_N"],
            expectations["drag_pressure_N"] + expectations["drag_viscous_N"],
            rel_tol=1e-3,
        )
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_viscous_source_is_reported_per_zone():
    """PID 2 ha la forza viscosa nel `.dat` (fluent), PID 3 no: l'assieme e' 'mixed'."""
    result, _expectations, folder = _extract()
    try:
        zones = {zone["name"]: zone for zone in result["pid_breakdown"]}
        assert zones["flat_floor"]["viscous_source"] == "fluent"
        assert zones["venturi"]["viscous_source"] == "none"
        kpis = result["physics_data"]["summary_kpis"]
        assert kpis["viscous_source"] == "mixed"
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_coefficients_use_reference_area():
    result, _expectations, folder = _extract()
    try:
        kpis = result["physics_data"]["summary_kpis"]
        q_inf = kpis["dynamic_pressure_pa"]
        area = kpis["reference_area_m2"]
        assert math.isclose(area, 1.08, rel_tol=1e-9)
        # I KPI sono arrotondati (3-4 decimali): confronto con tolleranza assoluta.
        assert math.isclose(kpis["CL_A"], kpis["downforce_N"] / q_inf, abs_tol=1e-3)
        assert math.isclose(kpis["CL"], kpis["downforce_N"] / (q_inf * area), abs_tol=1e-3)
        assert math.isclose(kpis["CD"], kpis["drag_total_N"] / (q_inf * area), abs_tol=1e-3)
        assert math.isclose(kpis["CL"], kpis["CL_A"] / area, abs_tol=1e-3)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_shear_stress_sign_marks_attached_flow():
    """
    tau_w,x = -F_visc,x / A = +2 Pa sui due triangoli di flat_floor -> flusso attaccato.

    Il PID "venturi" non ha la forza viscosa nel `.dat`: il parser ricade sulla
    catena documentata (tau -> velocita' -> Cp > +0.15). Con Cp positivo viene
    marcato come separato al 100%: qui lo verifichiamo, cosi' la catena di
    fallback resta documentata invece di essere una sorpresa.
    """
    result, _expectations, folder = _extract()
    try:
        zones = {zone["zone_name"]: zone for zone in result["pid_breakdown"]}
        assert math.isclose(zones["flat_floor"]["stalled_area_pct"], 0.0, abs_tol=1e-6)
        assert math.isclose(zones["venturi"]["stalled_area_pct"], 100.0, abs_tol=1e-6)

        # Aree: flat_floor 1.0 m^2 su 1.5 totali -> 66.67% attaccato, 33.33% "separato"
        kpis = result["physics_data"]["summary_kpis"]
        assert math.isclose(kpis["stalled_area_percentage"], 100.0 * 0.5 / 1.5, abs_tol=0.01)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_cp_matches_hand_calculation():
    result, _expectations, folder = _extract()
    try:
        kpis = result["physics_data"]["summary_kpis"]
        expected_cp = 100.0 / kpis["dynamic_pressure_pa"]
        flat = [zone for zone in result["pid_breakdown"] if zone["zone_name"] == "flat_floor"][0]
        assert math.isclose(flat["cp_mean"], expected_cp, rel_tol=1e-2), (flat["cp_mean"], expected_cp)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_center_of_pressure_as_wheelbase_percent():
    """
    Con i riferimenti degli assi nel config il CoP viene espresso anche come
    percentuale del passo; senza di essi il KPI resta None (non compare).
    """
    base_res, _exp, folder_a = _extract()
    try:
        kpis = base_res["physics_data"]["summary_kpis"]
        assert kpis["cop_wheelbase_pct"] is None
        assert kpis["wheelbase_m"] is None
    finally:
        shutil.rmtree(folder_a, ignore_errors=True)

    refs = {
        "velocity_inf": 14.0,
        "density_air": 1.225,
        "reference_area": 1.08,
        "front_axle_x": 0.0,
        "rear_axle_x": 1.0,
        "wheelbase": 1.0,
    }
    res, _exp, folder_b = _extract(ref_values=refs)
    try:
        kpis = res["physics_data"]["summary_kpis"]
        pct = kpis["cop_wheelbase_pct"]
        assert pct is not None
        assert 0.0 <= pct <= 100.0, pct
        expected = (float(kpis["cop_x_m"]) - 0.0) / 1.0 * 100.0
        assert math.isclose(pct, expected, abs_tol=0.15), (pct, expected)
        assert math.isclose(kpis["wheelbase_m"], 1.0, rel_tol=1e-9)
    finally:
        shutil.rmtree(folder_b, ignore_errors=True)
