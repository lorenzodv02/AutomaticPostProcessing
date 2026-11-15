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

import warnings

import numpy as np

# Oltre questa soglia si campiona il mesh: per un'immagine da ~1.5 Mpx bastano
# ~4 M triangoli per avere piu' di un triangolo per pixel.
MAX_POINTS = 4_000_000


def _fill_holes(grid, passes: int = 6):
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
        # nanmean su vicini tutti vuoti emette "Mean of empty slice": e' atteso
        # (quei pixel restano vuoti) e non deve sporcare lo stderr dell'app.
        with np.errstate(invalid="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            mean = np.nanmean(neighbours, axis=0)
        fillable = empty & np.isfinite(mean)
        if not np.any(fillable):
            break
        out[fillable] = mean[fillable]
    return out


def side_mask(normals, axis: int = 1, sign: int = -1, threshold: float = 0.15):
    """
    Maschera dei triangoli che appartengono a un lato della superficie.

    Serve a distinguere davvero la vista "lato aspirazione" (-Y) dalla vista
    superiore (+Y): senza filtro si proiettano entrambi i lati e le due immagini
    risultano quasi identiche.
    """
    if normals is None:
        return None
    normals = np.asarray(normals, dtype=float)
    if normals.ndim != 2 or normals.shape[1] <= axis:
        return None
    return normals[:, axis] * float(sign) > float(threshold)


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


def combine_zone_meshes(
    zone_meshes: dict,
    mirror_symmetry: bool = False,
    target_budget_triangles: int = 1_500_000,
):
    """
    Combina i triangoli 3D reali di tutti i PID dell'assieme selezionato in array unificati.
    Se il modello e' half-car simmetrico (Z <= 0) e mirror_symmetry=True, aggiunge anche
    la copia specchiata (Z >= 0) per visualizzare l'impronta completa del veicolo.
    Il budget e' alto di proposito: il renderer rasterizza le mesh dense, quindi
    tenere pochi triangoli serve solo a rendere la geometria irriconoscibile.
    Il valore e' configurabile da `meta.render_max_triangles`.
    """
    valid_zones = []
    for pid_i, (zid, zm) in enumerate(zone_meshes.items()):
        pts = zm.get("nodes", zm.get(" nodes"))
        tris = zm.get("triangles")
        if pts is None or tris is None or pts.shape[0] == 0 or tris.shape[0] == 0:
            continue
        valid_zones.append((pid_i, zid, zm, pts, tris))

    if not valid_zones:
        return None

    # Se c'e' simmetria, la copia specchiata raddoppia i triangoli: dimezziamo il budget per l'half-car
    target_half = (target_budget_triangles // 2) if mirror_symmetry else target_budget_triangles
    total_raw_tris = sum(tris.shape[0] for _, _, _, _, tris in valid_zones)

    # I PID piccoli (<= 800 triangoli, es. alette, flap, endplate sottili) mantengono il 100%
    # Il budget restante viene ripartito proporzionalmente tra le superfici estese (fondo, telaio, ruote)
    small_threshold = 800
    small_tris_sum = sum(tris.shape[0] for _, _, _, _, tris in valid_zones if tris.shape[0] <= small_threshold)
    large_zones = [z for z in valid_zones if z[4].shape[0] > small_threshold]
    large_raw_sum = sum(z[4].shape[0] for z in large_zones)
    avail_for_large = max(5000, target_half - small_tris_sum)

    all_pts, all_tris, all_cp, all_taux, all_tke, all_pid_idx, pid_labels = [], [], [], [], [], [], []
    all_normals = []
    offset = 0

    for pid_i, zid, zm, pts, tris in valid_zones:
        n_pts = pts.shape[0]
        n_tris = tris.shape[0]

        normals = zm.get("normals")
        if total_raw_tris <= target_half or n_tris <= small_threshold:
            tris_sub = tris
            cp_sub = zm["cp"]
            taux_sub = zm["tau_x"]
            tke_sub = zm["tke"]
            normals_sub = normals
        else:
            weight = n_tris / max(large_raw_sum, 1)
            allocated = max(small_threshold, int(avail_for_large * weight))
            step = max(1, n_tris // allocated)
            sel = np.arange(0, n_tris, step, dtype=np.int64)
            tris_sub = tris[sel]
            cp_sub = zm["cp"][sel]
            taux_sub = zm["tau_x"][sel]
            tke_sub = zm["tke"][sel]
            normals_sub = normals[sel] if normals is not None else None

        all_pts.append(pts)
        all_tris.append(tris_sub + offset)
        all_cp.append(cp_sub)
        all_taux.append(taux_sub)
        all_tke.append(tke_sub)
        all_pid_idx.append(np.full(tris_sub.shape[0], pid_i, dtype=np.int32))
        if normals_sub is not None and len(normals_sub) == tris_sub.shape[0]:
            all_normals.append(np.asarray(normals_sub, dtype=float))
        pid_labels.append({
            "pid_index": pid_i,
            "zone_id": zid,
            "zone_name": zm.get("zone_name", zm.get("name", f"PID_{zid}")),
            "n_triangles": int(n_tris),
            "centroid": [float(np.mean(pts[:, 0])), float(np.mean(pts[:, 1])), float(np.mean(pts[:, 2]))],
        })
        offset += n_pts

        if mirror_symmetry:
            pts_mir = pts.copy()
            pts_mir[:, 2] = -pts_mir[:, 2]
            all_pts.append(pts_mir)
            all_tris.append(tris_sub + offset)
            all_cp.append(cp_sub)
            all_taux.append(taux_sub)
            all_tke.append(tke_sub)
            all_pid_idx.append(np.full(tris_sub.shape[0], pid_i, dtype=np.int32))
            if normals_sub is not None and len(normals_sub) == tris_sub.shape[0]:
                all_normals.append(np.asarray(normals_sub, dtype=float))
            offset += n_pts

    if not all_pts:
        return None

    total_tris = sum(arr.shape[0] for arr in all_tris)
    normals_full = None
    if all_normals and sum(arr.shape[0] for arr in all_normals) == total_tris:
        normals_full = np.vstack(all_normals)

    return {
        "pts": np.vstack(all_pts),
        "tris": np.vstack(all_tris),
        "normals": normals_full,
        "cp": np.concatenate(all_cp),
        "tau_x": np.concatenate(all_taux),
        "tke": np.concatenate(all_tke),
        "pid_idx": np.concatenate(all_pid_idx),
        "pid_labels": pid_labels,
    }
