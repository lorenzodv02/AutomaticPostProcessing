# -*- coding: utf-8 -*-
"""Test della rasterizzazione delle superfici (solo numpy, nessun matplotlib)."""

import numpy as np

from render_utils import rasterize_surface


class _Figure:
    dpi = 100.0

    def get_size_inches(self):
        return (12.0, 6.0)


class _StubAxes:
    """Registra la chiamata a imshow e restituisce un oggetto-sentinella."""

    def __init__(self):
        self.figure = _Figure()
        self.calls = []

    def imshow(self, data, **kwargs):
        self.calls.append((data, kwargs))
        return "IMAGE"


def _grid_mesh(nx=200, ny=100):
    xs = np.linspace(0.0, 1.0, nx)
    ys = np.linspace(0.0, 0.5, ny)
    gx, gy = np.meshgrid(xs, ys)
    x = gx.ravel()
    y = gy.ravel()
    idx = np.arange(x.size).reshape(gy.shape)
    i0 = idx[:-1, :-1].ravel()
    i1 = idx[:-1, 1:].ravel()
    i2 = idx[1:, :-1].ravel()
    i3 = idx[1:, 1:].ravel()
    tris = np.vstack([np.column_stack([i0, i1, i2]), np.column_stack([i1, i3, i2])])
    values = np.sin(6 * x[tris].mean(axis=1)) * np.cos(4 * y[tris].mean(axis=1))
    return x, y, tris, values


def test_dense_mesh_is_fully_filled():
    """Una mesh fitta (piu' triangoli che pixel) deve produrre un'immagine senza buchi."""
    x, y, tris, values = _grid_mesh(1400, 700)
    assert tris.shape[0] > 1_500_000    # sopra la soglia del percorso vettoriale

    ax = _StubAxes()
    result = rasterize_surface(ax, x, y, tris, values, cmap="jet", vmin=-1, vmax=1)

    assert result == "IMAGE"
    assert len(ax.calls) == 1
    grid, kwargs = ax.calls[0]
    assert kwargs["origin"] == "lower"
    assert kwargs["extent"] == [0.0, 1.0, 0.0, 0.5]
    assert np.isfinite(grid).all(), "la superficie non deve avere buchi"
    assert grid.min() >= -1.0 and grid.max() <= 1.0


def test_mid_density_has_no_large_holes():
    """Con campioni ogni ~4 px il riempimento non fa miracoli, ma non lascia buchi larghi."""
    x, y, tris, values = _grid_mesh(300, 150)
    ax = _StubAxes()
    assert rasterize_surface(ax, x, y, tris, values, "jet", -1, 1) == "IMAGE"
    grid, _kwargs = ax.calls[0]
    filled_fraction = float(np.isfinite(grid).mean())
    assert filled_fraction > 0.95, filled_fraction


def test_small_mesh_still_works():
    """Su mesh molto rada non si pretende copertura totale, ma nessun crash."""
    x, y, tris, values = _grid_mesh(20, 10)
    ax = _StubAxes()
    assert rasterize_surface(ax, x, y, tris, values, "jet", -1, 1) == "IMAGE"
    grid, _kwargs = ax.calls[0]
    assert np.isfinite(grid).any()
    assert grid.shape[0] > 100 and grid.shape[1] > 100


def test_nan_values_are_skipped():
    x, y, tris, values = _grid_mesh(60, 30)
    values = values.copy()
    values[:50] = np.nan
    ax = _StubAxes()
    assert rasterize_surface(ax, x, y, tris, values, "jet", -1, 1) == "IMAGE"


def test_degenerate_inputs_return_none():
    ax = _StubAxes()
    assert rasterize_surface(ax, np.zeros(3), np.zeros(3), np.array([[0, 1, 2]]),
                             np.array([1.0]), "jet", 0, 1) is None
    assert rasterize_surface(ax, np.array([]), np.array([]), np.array([]),
                             np.array([]), "jet", 0, 1) is None
    # valori disallineati dai triangoli: niente crash
    assert rasterize_surface(ax, np.array([0.0, 1.0, 0.0]), np.array([0.0, 0.0, 1.0]),
                             np.array([[0, 1, 2]]), np.array([1.0, 2.0]), "jet", 0, 1) is None

def _zone(n_tris, name="zona"):
    """Zona finta con `n_tris` triangoli indipendenti."""
    pts = np.column_stack([
        np.arange(n_tris * 3, dtype=float) % 10.0,
        np.zeros(n_tris * 3),
        (np.arange(n_tris * 3, dtype=float) // 10.0) % 5.0,
    ])
    tris = np.arange(n_tris * 3, dtype=np.int32).reshape((n_tris, 3))
    return {
        "nodes": pts,
        "triangles": tris,
        "cp": np.linspace(-1.0, 1.0, n_tris),
        "tau_x": np.linspace(0.0, 5.0, n_tris),
        "tke": np.linspace(0.0, 2.0, n_tris),
        "zone_name": name,
    }


def test_combine_keeps_everything_under_budget():
    from render_utils import combine_zone_meshes

    zones = {1: _zone(1000), 2: _zone(1200)}
    out = combine_zone_meshes(zones, mirror_symmetry=False, target_budget_triangles=1_500_000)
    assert out["tris"].shape[0] == 2200
    assert out["cp"].shape[0] == 2200


def test_combine_respects_budget_for_large_zones():
    from render_utils import combine_zone_meshes

    zones = {1: _zone(200_000), 2: _zone(200_000)}
    budget = 100_000
    out = combine_zone_meshes(zones, mirror_symmetry=False, target_budget_triangles=budget)
    kept = out["tris"].shape[0]
    assert kept <= budget + 5000, kept
    assert kept >= budget // 2, kept


def test_combine_keeps_small_zones_complete():
    from render_utils import combine_zone_meshes

    zones = {1: _zone(300, "aletta"), 2: _zone(200_000, "fondo")}
    out = combine_zone_meshes(zones, mirror_symmetry=False, target_budget_triangles=50_000)
    small_pid = out["pid_idx"] == 0
    assert int(np.count_nonzero(small_pid)) == 300


def test_combine_mirror_doubles_the_mesh():
    from render_utils import combine_zone_meshes

    zones = {1: _zone(500)}
    half = combine_zone_meshes(zones, mirror_symmetry=False, target_budget_triangles=1_500_000)
    full = combine_zone_meshes(zones, mirror_symmetry=True, target_budget_triangles=1_500_000)
    assert full["tris"].shape[0] == 2 * half["tris"].shape[0]
    # la copia specchiata sta sul lato opposto in Z
    assert full["pts"][:, 2].min() < 0.0


def test_resolve_velocity_prefers_real_kpi_key():
    """La chiave scritta dal parser e' `velocity_inf_ms` (non `inlet_velocity`)."""
    from render_utils import resolve_velocity_inf

    assert resolve_velocity_inf({"velocity_inf_ms": 14.0}) == 14.0
    assert resolve_velocity_inf({"velocity_inf_ms": 20.0, "inlet_velocity": 16.67}) == 20.0


def test_resolve_velocity_fallbacks_and_default():
    from render_utils import DEFAULT_VELOCITY_INF, resolve_velocity_inf

    assert resolve_velocity_inf({"velocity_inf": 12.5}) == 12.5
    assert resolve_velocity_inf({"inlet_velocity": 16.67}) == 16.67
    # chiave assente o non valida -> default, NON un valore cablato a caso
    assert resolve_velocity_inf({}) == DEFAULT_VELOCITY_INF
    assert resolve_velocity_inf({"velocity_inf_ms": 0}) == DEFAULT_VELOCITY_INF
    assert resolve_velocity_inf({"velocity_inf_ms": "x"}) == DEFAULT_VELOCITY_INF
    assert resolve_velocity_inf(None) == DEFAULT_VELOCITY_INF
