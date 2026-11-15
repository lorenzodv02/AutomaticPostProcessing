# -*- coding: utf-8 -*-
"""
Rasterizzazione di campi su superfici triangolate (solo numpy).

Perche' esiste: `tripcolor` con subsampling lascia dei buchi sulle mesh dense
(si vedono i singoli triangoli e la geometria sparisce). Qui ogni triangolo
contribuisce al pixel del suo baricentro, quindi il risultato e' **continuo** e
il costo e' lineare nel numero di facce.

Il modulo non importa matplotlib: riceve l'oggetto `ax` e chiama `ax.imshow`,
cosi' resta testabile in CI (che non installa matplotlib).
"""

import numpy as np

# Oltre questa soglia si campiona il mesh: per un'immagine da ~1.5 Mpx bastano
# ~4 M triangoli per avere piu' di un triangolo per pixel.
MAX_POINTS = 4_000_000


def _fill_holes(grid, passes: int = 3):
    """
    Chiude i buchi di 1-2 pixel mediando i vicini finiti.

    Serve perche' anche campionando i vertici, su mesh con pochi triangoli per
    pixel restano pixel vuoti: l'immagine deve risultare continua, non un
    puntinato.
    """
    out = np.array(grid, dtype=float, copy=True)
    for _ in range(max(0, passes)):
        empty = ~np.isfinite(out)
        if not empty.any():
            break
        padded = np.pad(out, 1, constant_values=np.nan)
        neighbours = np.stack([
            padded[:-2, 1:-1], padded[2:, 1:-1], padded[1:-1, :-2], padded[1:-1, 2:],
            padded[:-2, :-2], padded[:-2, 2:], padded[2:, :-2], padded[2:, 2:],
        ])
        with np.errstate(invalid="ignore"):
            mean = np.nanmean(neighbours, axis=0)
        fillable = empty & np.isfinite(mean)
        if not np.any(fillable):
            break
        out[fillable] = mean[fillable]
    return out


def rasterize_surface(ax, x, y, triangles, facecolors, cmap, vmin, vmax,
                      max_points: int = MAX_POINTS):
    """
    Disegna `facecolors` sui baricentri dei triangoli, come immagine continua.

    Restituisce l'oggetto creato da `ax.imshow` (o None se non c'e' nulla da
    disegnare in modo sensato).
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    tri = np.asarray(triangles)
    values = np.asarray(facecolors, dtype=float)
    if tri.size == 0 or values.size == 0 or x.size == 0:
        return None
    if tri.ndim != 2 or tri.shape[1] != 3:
        return None
    if values.size != tri.shape[0]:
        return None

    finite = np.isfinite(values)
    if not np.all(finite):
        tri = tri[finite]
        values = values[finite]
        if tri.size == 0:
            return None

    x0, x1 = float(np.min(x)), float(np.max(x))
    y0, y1 = float(np.min(y)), float(np.max(y))
    if not np.isfinite([x0, x1, y0, y1]).all() or x1 - x0 <= 1e-12 or y1 - y0 <= 1e-12:
        return None

    # Risoluzione: quella della figura, con pixel quadrati rispetto ai dati.
    try:
        fig_w = float(ax.figure.get_size_inches()[0])
        dpi = float(ax.figure.dpi)
    except Exception:
        fig_w, dpi = 10.0, 100.0
    width_px = int(np.clip(round(fig_w * dpi), 600, 1800))
    height_px = int(np.clip(round(width_px * (y1 - y0) / (x1 - x0)), 300, 1600))

    # Si campiona al baricentro **e** sui tre vertici: con soli baricentri il
    # numero di campioni puo' essere inferiore ai pixel e la superficie resta
    # bucherellata.
    vx = x[tri]
    vy = y[tri]
    cx = np.concatenate([vx[:, 0], vx[:, 1], vx[:, 2], (vx[:, 0] + vx[:, 1] + vx[:, 2]) / 3.0])
    cy = np.concatenate([vy[:, 0], vy[:, 1], vy[:, 2], (vy[:, 0] + vy[:, 1] + vy[:, 2]) / 3.0])
    values = np.tile(values, 4)

    if cx.size > max_points:
        step = max(1, cx.size // max_points)
        cx = cx[::step]
        cy = cy[::step]
        values = values[::step]

    ix = np.clip(((cx - x0) / (x1 - x0) * (width_px - 1)).astype(np.int64), 0, width_px - 1)
    iy = np.clip(((cy - y0) / (y1 - y0) * (height_px - 1)).astype(np.int64), 0, height_px - 1)
    flat = iy * width_px + ix

    cells = width_px * height_px
    sums = np.bincount(flat, weights=values, minlength=cells)
    counts = np.bincount(flat, minlength=cells).astype(float)
    grid = np.full(cells, np.nan, dtype=float)
    filled = counts > 0
    if not np.any(filled):
        return None
    grid[filled] = sums[filled] / counts[filled]
    grid = _fill_holes(grid.reshape(height_px, width_px))

    return ax.imshow(
        grid,
        origin="lower",
        extent=[x0, x1, y0, y1],
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        interpolation="bilinear",
        aspect="auto",
    )
