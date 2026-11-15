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
