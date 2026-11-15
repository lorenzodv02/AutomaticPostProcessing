# -*- coding: utf-8 -*-
"""Test delle soglie di diagnosi: prima erano cablate, ora arrivano da config.yaml."""

import config_bridge as cb
from analyzer.assembly_rules import evaluate_design_issues


def _pid(name, stall=0.0, cp_min=-1.0, fy=-10.0, fx=1.0):
    return {
        "id": 2,
        "zone_id": 2,
        "zone_name": name,
        "name": name,
        "n_faces": 100,
        "area_m2": 0.5,
        "stalled_area_pct": stall,
        "cp_min": cp_min,
        "cp_mean": 0.4,
        "fy_N": fy,
        "fx_N": fx,
        "bbox": {"xmin": 0.0, "xmax": 1.0, "ymin": 0.0, "ymax": 0.1, "zmin": -0.5, "zmax": 0.0},
    }


def _bundle(pid_breakdown, **kpi_overrides):
    kpis = {
        "stalled_area_percentage": 2.0,
        "peak_suction_cp": -2.0,
        "downforce_total_N": -300.0,
        "drag_total_N": 20.0,
        "efficiency_l_d": 15.0,
        "cop_x_m": 0.42,
        "cop_x_pct": 42.0,
        "cl_a_total": -2.5,
        "cd_a_total": 0.17,
        "lateral_asymmetry_pct": 0.0,
        "vortex_stability_pct": 95.0,
    }
    kpis.update(kpi_overrides)
    return {
        "assembly_type": "undertray",
        "bounding_box": {"xmin": 0.0, "xmax": 1.0, "ymin": 0.0, "ymax": 0.1, "zmin": -0.5, "zmax": 0.0},
        "cas_info": {},
        "config": {},
        "physics_data": {"summary_kpis": kpis, "pid_breakdown": pid_breakdown},
    }


def _by_id(issues):
    return {issue["id"]: issue for issue in issues}


def test_stall_severity_uses_thresholds():
    """Con le soglie undertray (8% / 18%): 10% e' WARNING, 20% e' CRITICAL."""
    warning_issues = _by_id(evaluate_design_issues(_bundle([_pid("flat_floor", stall=10.0)]), {}))
    worst = [issue for issue in warning_issues.values() if issue["id"].endswith("-01")][0]
    assert worst["severity"] == "WARNING", worst["severity"]

    critical_issues = _by_id(evaluate_design_issues(_bundle([_pid("flat_floor", stall=20.0)]), {}))
    worst = [issue for issue in critical_issues.values() if issue["id"].endswith("-01")][0]
    assert worst["severity"] == "CRITICAL", worst["severity"]

    info_issues = _by_id(evaluate_design_issues(_bundle([_pid("flat_floor", stall=1.0)]), {}))
    worst = [issue for issue in info_issues.values() if issue["id"].endswith("-01")][0]
    assert worst["severity"] == "INFO", worst["severity"]


def test_thresholds_can_be_overridden_from_config():
    """Abbassando critical_stall_pct a 5.0, un 10% diventa CRITICAL: il config comanda davvero."""
    bundle = _bundle([_pid("flat_floor", stall=10.0)])
    bundle["config"] = {"assemblies": {"undertray": {"thresholds": {"critical_stall_pct": 5.0}}}}
    issues = _by_id(evaluate_design_issues(bundle, {}))
    worst = [issue for issue in issues.values() if issue["id"].endswith("-01")][0]
    assert worst["severity"] == "CRITICAL"

    # E la soglia di fallback resta quella di config_bridge quando il file non la definisce
    assert cb.thresholds({}, "undertray")["critical_stall_pct"] == 18.0


def test_suction_peak_severity():
    """Cp_min oltre min_suction_cp_warning (-3.2) e' WARNING, altrimenti INFO."""
    deep = _by_id(evaluate_design_issues(_bundle([_pid("venturi", cp_min=-4.5)]), {}))
    suction = [issue for issue in deep.values() if issue["id"].endswith("-02")][0]
    assert suction["severity"] == "WARNING"

    mild = _by_id(evaluate_design_issues(_bundle([_pid("venturi", cp_min=-2.0)]), {}))
    suction = [issue for issue in mild.values() if issue["id"].endswith("-02")][0]
    assert suction["severity"] == "INFO"


def test_asymmetry_severity():
    """Oltre max_asymmetry_pct (4.5%) la verifica di simmetria diventa WARNING."""
    ok = _by_id(evaluate_design_issues(_bundle([_pid("flat_floor")], lateral_asymmetry_pct=1.0), {}))
    symmetric = [issue for issue in ok.values() if issue["id"].endswith("-04")][0]
    assert symmetric["severity"] == "INFO"

    bad = _by_id(evaluate_design_issues(_bundle([_pid("flat_floor")], lateral_asymmetry_pct=9.0), {}))
    asymmetric = [issue for issue in bad.values() if issue["id"].endswith("-04")][0]
    assert asymmetric["severity"] == "WARNING"


def test_vortex_loss_threshold_generates_issue():
    """vortex_core_loss_threshold (0.35) ora produce una problematica dedicata."""
    healthy = evaluate_design_issues(_bundle([_pid("flat_floor")], vortex_stability_pct=95.0), {})
    assert not [issue for issue in healthy if issue["id"].endswith("-05")]

    degraded = evaluate_design_issues(_bundle([_pid("flat_floor")], vortex_stability_pct=50.0), {})
    vortex_issues = [issue for issue in degraded if issue["id"].endswith("-05")]
    assert len(vortex_issues) == 1
    assert vortex_issues[0]["severity"] == "WARNING"
    assert vortex_issues[0]["cad_redesign_actions"]


def test_every_issue_is_complete():
    """Ogni problematica deve avere i campi che il report consuma."""
    issues = evaluate_design_issues(_bundle([_pid("flat_floor", stall=12.0, cp_min=-4.0)]), {})
    assert issues
    for issue in issues:
        for key in ("id", "severity", "title", "location_xyz", "visual_evidence",
                    "root_cause", "quantified_impact", "cad_redesign_actions"):
            assert issue.get(key), (key, issue.get("id"))
        assert issue["severity"] in ("CRITICAL", "WARNING", "INFO")
