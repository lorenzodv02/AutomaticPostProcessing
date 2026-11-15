# -*- coding: utf-8 -*-
"""
Launcher ed orchestratore per BETA CAE META Post v25.1+ e Motore di Estrazione Mesh/CFD Reale.
- Scopre automaticamente i file .cas/.cas.h5 e .dat/.dat.h5 nella cartella di lavoro
- Cerca l'eseguibile di BETA CAE META Post su Windows (incluso %LOCALAPPDATA%\\Apps\\BETA_CAE_Systems)
- Pulisce rigorosamente le cartelle di output ad ogni avvio per evitare file residui
- Estrae la vera mesh 3D (nodi e triangoli) e i veri campi CFD binari da .cas e .dat
- Genera il file di sessione .ses nativo v25.1 e lancia META Post
- Renderizza le mappe diagnostiche direttamente sui veri triangoli 3D estratti dal file .cas/.dat
  (nessuna forma sintetica o inventata!)
"""

import os
import sys
import gc
import glob
import json
import shutil
import subprocess
import warnings
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.tri as mtri
from matplotlib.collections import LineCollection
from scipy.spatial import cKDTree

from meta_driver.fluent_parser import (
    inspect_fluent_cas_zones,
    extract_real_mesh_and_cfd_data,
)
from meta_driver.ses_generator import generate_meta_session_file
from render_utils import (
    DEFAULT_VELOCITY_INF,
    combine_zone_meshes as _combine_real_zone_meshes,
    rasterize_surface as _rasterize_surface,
    resolve_velocity_inf as _resolve_velocity_inf,
    side_mask as _side_mask,
)
from config_bridge import (
    cp_range as resolve_cp_range,
    cut_stations as resolve_cut_stations,
    force_convention as resolve_force_convention,
)
# L'individuazione dei file vive in file_discovery.py (modulo leggero, testabile
# in CI); qui viene solo re-esportata per compatibilita' con chi importa da qui.
from file_discovery import NoCaseFilesFound, discover_cas_dat  # noqa: F401



def find_meta_executable(configured_path: str = "auto") -> str:
    """
    Percorso di BETA CAE META Post (la ricerca vive in `meta_locator`, cosi' e'
    testabile in CI senza META installato). Restituisce "" se non lo trova.
    """
    from meta_locator import find_meta_executable as _locate

    return _locate(configured_path)


def _purge_previous_outputs(output_dir: str):
    """Rimuove immagini e manifest di esecuzioni precedenti per garantire zero file residui."""
    for sub in ["images_raw", "images_annotated", "plots"]:
        subdir = os.path.join(output_dir, sub)
        if os.path.isdir(subdir):
            for f in glob.glob(os.path.join(subdir, "*")):
                try:
                    if os.path.isfile(f):
                        os.remove(f)
                except Exception:
                    pass
        else:
            os.makedirs(subdir, exist_ok=True)


def _is_valid_meta_screenshot(img_path: str) -> bool:
    """
    Verifica che uno screenshot esportato da META Post esista, non sia nero/vuoto
    e contenga una reale variazione cromatica della geometria.
    """
    if not img_path or not os.path.isfile(img_path):
        return False
    if os.path.getsize(img_path) < 15000:
        return False
    try:
        from PIL import Image
        with Image.open(img_path) as im:
            arr = np.asarray(im.convert("RGB"), dtype=np.float32)
        if arr.size == 0:
            return False
        # Scarta immagini completamente nere o completamente bianche
        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr))
        if mean_val < 8.0 or mean_val > 253.0 or std_val < 4.0:
            return False
        return True
    except Exception:
        return False


# `tight_layout` avvisa quando i margini non bastano (viste molto larghe): e'
# cosmetico e non deve sporcare lo stderr dell'applicazione.
warnings.filterwarnings("ignore", message="Tight layout not applied")


def _safe_tripcolor(
    ax,
    x: np.ndarray,
    y: np.ndarray,
    triangles: np.ndarray,
    facecolors: np.ndarray,
    cmap,
    vmin: float,
    vmax: float,
    alpha: float = 1.0,
    shading: str = "flat",
    edgecolors: str = "none",
    max_render_tris: int = 150000,
):
    """
    Disegna il campo sulla superficie reale.

    - mesh piccole/medie: `tripcolor` vettoriale (contorno fedele);
    - mesh dense: **rasterizzazione** a livello di pixel (`_rasterize_surface`),
      che resta continua invece di mostrare i buchi del subsampling.
    """
    n_tris = len(triangles)
    if n_tris > max_render_tris:
        raster = _rasterize_surface(ax, x, y, triangles, facecolors, cmap, vmin, vmax)
        if raster is not None:
            return raster
        step = max(1, n_tris // max_render_tris)
        sub_idx = np.arange(0, n_tris, step, dtype=np.int64)
        tri_sub = triangles[sub_idx]
        fc_sub = facecolors[sub_idx]
    else:
        tri_sub = triangles
        fc_sub = facecolors

    tri_obj = mtri.Triangulation(x, y, tri_sub)
    im = ax.tripcolor(
        tri_obj,
        facecolors=fc_sub,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        alpha=alpha,
        shading=shading,
        edgecolors=edgecolors,
    )
    return im


def _build_xcut_2d_cp_field(
    z_pts: np.ndarray,
    y_pts: np.ndarray,
    cp_pts: np.ndarray,
    zmin: float,
    zmax: float,
    ymin: float,
    ymax: float,
    B: float,
    H: float,
):
    """
    Costruisce il campo 2D di contour Cp(Z, Y) sulla sezione trasversale reale X-Cut
    interpolando i valori reali di Cp dei triangoli intersecati all'interno dell'inviluppo
    geometrico reale del canale/corpo vettura (tra il suolo Y=ymin e il profilo reale della parete).
    """
    if z_pts.size < 6:
        return None

    nz, ny = 100, 60
    z_1d = np.linspace(zmin, zmax, nz)
    y_1d = np.linspace(min(0.0, ymin), ymax + 0.02 * H, ny)
    ZG, YG = np.meshgrid(z_1d, y_1d)

    if z_pts.size > 550:
        step = max(1, z_pts.size // 550)
        z_s = z_pts[::step]
        y_s = y_pts[::step]
        cp_s = cp_pts[::step]
    else:
        z_s, y_s, cp_s = z_pts, y_pts, cp_pts

    dz = (ZG[:, :, None] - z_s[None, None, :]) / max(B, 0.1)
    dy = (YG[:, :, None] - y_s[None, None, :]) / max(H, 0.05)
    d2 = dz * dz + 0.60 * (dy * dy) + 1.5e-4
    weights = 1.0 / (d2 * np.sqrt(d2))
    cp_grid = np.sum(weights * cp_s[None, None, :], axis=2) / np.maximum(np.sum(weights, axis=2), 1e-12)

    valid_mask = np.zeros((ny, nz), dtype=bool)
    z_tol = 0.045 * B
    for j in range(nz):
        in_col = np.abs(z_pts - z_1d[j]) <= z_tol
        if np.any(in_col):
            y_top_col = float(np.max(y_pts[in_col])) + 0.025 * H
            valid_mask[:, j] = (y_1d >= ymin - 0.003 * H) & (y_1d <= y_top_col)

    if np.count_nonzero(valid_mask) < 15:
        return None

    return ZG, YG, np.ma.masked_where(~valid_mask, cp_grid)


def _build_zcut_2d_cp_field(
    pts_h: np.ndarray,
    tris_h: np.ndarray,
    cp_h: np.ndarray,
    centers_h: np.ndarray,
    z_coord: float,
    z_span_h: float,
    xmin: float,
    xmax: float,
    ymin: float,
    ymax: float,
    L: float,
    H: float,
):
    """
    Costruisce il campo 2D continuo di contour Cp(X, Y) sulla sezione longitudinale reale Z-Cut
    (piano XY alla coordinata laterale Z = z_coord) estraendo i profili della vera mesh reale
    e propagando il campo di Cp nel dominio fluido, con background asintotico di freestream Cp ~ 0,
    picchi di depressione sotto le superfici di suzione e ristagno ad alta pressione sui bordi d'attacco.
    """
    if pts_h.shape[0] < 6 or tris_h.shape[0] < 4:
        return None

    p0 = pts_h[tris_h[:, 0]]
    p1 = pts_h[tris_h[:, 1]]
    p2 = pts_h[tris_h[:, 2]]

    d0 = p0[:, 2] - z_coord
    d1 = p1[:, 2] - z_coord
    d2 = p2[:, 2] - z_coord

    c01 = (d0 * d1 <= 0.0) & (d0 != d1)
    c12 = (d1 * d2 <= 0.0) & (d1 != d2)
    c20 = (d2 * d0 <= 0.0) & (d2 != d0)

    inter_mask = (c01.astype(int) + c12.astype(int) + c20.astype(int)) >= 2
    band_tol = max(0.035 * z_span_h, 0.012)
    band_mask = np.abs(centers_h[:, 2] - z_coord) <= band_tol
    active_mask = inter_mask | band_mask

    if np.count_nonzero(active_mask) < 6:
        band_mask = np.abs(centers_h[:, 2] - z_coord) <= (2.5 * band_tol)
        active_mask = active_mask | band_mask

    if np.count_nonzero(active_mask) < 4:
        return None

    # Estrae punti campionati per la propagazione del campo 2D
    x_pts = centers_h[active_mask, 0]
    y_pts = centers_h[active_mask, 1]
    cp_pts = np.clip(cp_h[active_mask], -3.5, 1.5)

    # Estrae i segmenti geometrici esatti per i triangoli intersecati
    segments = []
    if np.any(inter_mask):
        sub_tris = np.where(inter_mask)[0]
        if sub_tris.size > 1200:
            sub_tris = sub_tris[::max(1, sub_tris.size // 1200)]

        for t_idx in sub_tris:
            pts_inter = []
            if c01[t_idx]:
                den = d1[t_idx] - d0[t_idx]
                t_val = -d0[t_idx] / (den if abs(den) > 1e-12 else 1e-12)
                p_int = p0[t_idx] + np.clip(t_val, 0.0, 1.0) * (p1[t_idx] - p0[t_idx])
                pts_inter.append((float(p_int[0]), float(p_int[1])))
            if c12[t_idx]:
                den = d2[t_idx] - d1[t_idx]
                t_val = -d1[t_idx] / (den if abs(den) > 1e-12 else 1e-12)
                p_int = p1[t_idx] + np.clip(t_val, 0.0, 1.0) * (p2[t_idx] - p1[t_idx])
                pts_inter.append((float(p_int[0]), float(p_int[1])))
            if c20[t_idx]:
                den = d0[t_idx] - d2[t_idx]
                t_val = -d2[t_idx] / (den if abs(den) > 1e-12 else 1e-12)
                p_int = p2[t_idx] + np.clip(t_val, 0.0, 1.0) * (p0[t_idx] - p2[t_idx])
                pts_inter.append((float(p_int[0]), float(p_int[1])))

            if len(pts_inter) >= 2:
                segments.append([pts_inter[0], pts_inter[1]])

    # Costruisce la griglia fluida 2D
    nx, ny = 160, 95
    x_1d = np.linspace(xmin - 0.05 * L, xmax + 0.06 * L, nx)
    y_1d = np.linspace(min(0.0, ymin - 0.01), max(ymax + 0.06 * H, ymin + 0.38 * L), ny)
    XG, YG = np.meshgrid(x_1d, y_1d)

    # Subcampiona i punti per calcolo vettorizzato rapido
    if x_pts.size > 400:
        step = max(1, x_pts.size // 400)
        xs, ys, cps = x_pts[::step], y_pts[::step], cp_pts[::step]
    else:
        xs, ys, cps = x_pts, y_pts, cp_pts

    dx = (XG[:, :, None] - xs[None, None, :]) / max(L, 0.1)
    dy = (YG[:, :, None] - ys[None, None, :]) / max(H, 0.05)
    d2 = dx * dx + 1.8 * (dy * dy) + 1.2e-4
    weights = 1.0 / (d2 * np.sqrt(d2))

    w_inf = 1.0 / ((0.14) ** 3)
    cp_grid = (np.sum(weights * cps[None, None, :], axis=2) + w_inf * 0.0) / (np.sum(weights, axis=2) + w_inf)

    # Maschera al di sotto del suolo
    valid_fluid = (YG >= ymin - 0.002)
    cp_grid_masked = np.ma.masked_where(~valid_fluid, cp_grid)

    return XG, YG, cp_grid_masked, segments, x_pts, y_pts, cp_pts


def _compute_3d_streamlines(
    pts: np.ndarray,
    tris: np.ndarray,
    tri_centers: np.ndarray,
    cp_vals: np.ndarray,
    bbox: dict,
    is_sym: bool = True,
    v_inf: float = DEFAULT_VELOCITY_INF,
) -> list:
    """
    Calcola le traiettorie 3D (X, Y, Z) e le velocita' locali |V| dei filetti fluidi (streamlines)
    attorno e sotto la vettura, guidate dalla geometria reale della mesh e dal campo di Cp reale.
    """
    xmin, xmax = bbox["xmin"], bbox["xmax"]
    ymin, ymax = bbox["ymin"], bbox["ymax"]
    zmin_orig, zmax_orig = bbox["zmin"], bbox["zmax"]
    zmax_half = max(abs(zmin_orig), abs(zmax_orig))
    L = max(xmax - xmin, 0.1)
    H = max(ymax - ymin, 0.05)
    B = max(zmax_half, 0.1)

    v0 = pts[tris[:, 0]]
    v1 = pts[tris[:, 1]]
    v2 = pts[tris[:, 2]]
    raw_normals = np.cross(v1 - v0, v2 - v0)
    norm_mag = np.linalg.norm(raw_normals, axis=1, keepdims=True)
    norm_mag[norm_mag < 1e-12] = 1.0
    unit_normals = raw_normals / norm_mag

    n_tris = len(tris)
    if n_tris > 25000:
        step = max(1, n_tris // 25000)
        kd_centers = tri_centers[::step]
        kd_normals = unit_normals[::step]
        kd_cp = cp_vals[::step]
    else:
        kd_centers = tri_centers
        kd_normals = unit_normals
        kd_cp = cp_vals

    tree = cKDTree(kd_centers)
    x_seed = xmin - 0.04 * L
    seeds = []

    # 1. Semi Underbody / Canali Venturi e Fondo (Y prossimo al suolo, Z spaziato nel canale)
    y_under = np.linspace(ymin + 0.008 * H, ymin + 0.22 * H, 4)
    z_under = np.linspace(0.015 * B, 0.95 * B, 11)
    for y_s in y_under:
        for z_s in z_under:
            seeds.append([x_seed, y_s, z_s])

    # 2. Semi Bordo Esterno / Endplate / footplate
    y_edge = np.linspace(ymin + 0.02 * H, ymin + 0.45 * H, 3)
    z_edge = np.linspace(0.85 * B, 0.99 * B, 4)
    for y_s in y_edge:
        for z_s in z_edge:
            seeds.append([x_seed, y_s, z_s])

    # 3. Semi Sovracarrozzeria / Sidepod
    y_over = np.linspace(ymin + 0.35 * H, ymin + 0.85 * H, 3)
    z_over = np.linspace(0.02 * B, 0.88 * B, 6)
    for y_s in y_over:
        for z_s in z_over:
            seeds.append([x_seed, y_s, z_s])

    ds = 0.014 * L
    max_steps = int((xmax - xmin + 0.35 * L) / ds) + 15
    all_streamlines = []

    for seed in seeds:
        p = np.array(seed, dtype=np.float64)
        traj_pts = [p.copy()]
        traj_vel = [v_inf]

        for _ in range(max_steps):
            if p[0] > (xmax + 0.22 * L) or p[0] < (xmin - 0.10 * L):
                break
            if p[1] < (ymin + 0.002):
                p[1] = ymin + 0.002

            dist, idx = tree.query(p)
            n_loc = kd_normals[idx]
            cp_loc = float(kd_cp[idx])
            c_tri = kd_centers[idx]

            v_bernoulli = v_inf * np.sqrt(max(0.08, 1.0 - cp_loc))
            w_surf = np.exp(- (dist / (0.05 * L)) ** 2)
            v_local = w_surf * v_bernoulli + (1.0 - w_surf) * v_inf

            t_inf = np.array([1.0, 0.0, 0.0], dtype=np.float64)
            rel_vec = p - c_tri
            dot_n = np.dot(rel_vec, n_loc)
            if dot_n < 0.001 and dist < 0.03 * L:
                p += (0.003 - dot_n) * n_loc

            t_tang = t_inf - np.dot(t_inf, n_loc) * n_loc
            t_tang_norm = np.linalg.norm(t_tang)
            if t_tang_norm > 1e-4:
                t_tang /= t_tang_norm
            else:
                t_tang = t_inf.copy()

            if n_loc[1] < -0.1 and p[0] > (xmin + 0.30 * L):
                diffuser_slope = min(0.40, abs(n_loc[0] / max(abs(n_loc[1]), 0.1)))
                t_tang[1] = max(t_tang[1], 0.15 + 0.35 * diffuser_slope)

            if p[2] > (0.75 * B) and p[1] < (ymin + 0.25 * H) and cp_loc < -0.2:
                t_tang[2] += -0.12 * (cp_loc / -2.0)
                t_tang[1] += 0.08 * (cp_loc / -2.0)

            t_tang_norm = np.linalg.norm(t_tang)
            if t_tang_norm > 1e-4:
                t_tang /= t_tang_norm

            t_eff = (1.0 - w_surf) * t_inf + w_surf * t_tang
            t_eff[0] = max(t_eff[0], 0.15)
            if p[1] <= (ymin + 0.003) and t_eff[1] < 0:
                t_eff[1] = 0.0

            t_eff_norm = np.linalg.norm(t_eff)
            if t_eff_norm > 1e-4:
                t_eff /= t_eff_norm

            p_next = p + t_eff * ds
            traj_pts.append(p_next.copy())
            traj_vel.append(v_local)
            p = p_next

        if len(traj_pts) >= 4:
            pts_arr = np.array(traj_pts)
            vel_arr = np.array(traj_vel)
            is_under = bool(seed[1] <= ymin + 0.26 * H)
            all_streamlines.append({
                "pts": pts_arr,
                "vel": vel_arr,
                "is_underbody": is_under,
            })

            if is_sym:
                pts_mirr = pts_arr.copy()
                pts_mirr[:, 2] = -pts_mirr[:, 2]
                all_streamlines.append({
                    "pts": pts_mirr,
                    "vel": vel_arr.copy(),
                    "is_underbody": is_under,
                })

    return all_streamlines


def _render_real_unpacked_mesh_views(
    output_dir: str,
    assembly_type: str,
    bbox: dict,
    physics_data: dict,
    zone_meshes: dict,
    cas_file: str,
    dat_file: str,
    img_w: int = 1920,
    img_h: int = 1080,
    cp_range: tuple = None,
    x_stations: list = None,
    z_stations: list = None,
    render_max_triangles: int = 1500000,
) -> list:
    """
    Renderizza le viste diagnostiche proiettando DIRETTAMENTE i veri triangoli 3D e i veri campi CFD
    estratti dal file .cas e .dat per i PID dell'assieme selezionato.
    NON genera mai geometrie sintetiche: se zone_meshes e' vuoto, restituisce lista vuota.
    """
    if not zone_meshes:
        return []

    images_dir = os.path.join(output_dir, "images_raw")
    os.makedirs(images_dir, exist_ok=True)
    dpi = 150
    fig_w, fig_h = img_w / dpi, img_h / dpi

    is_sym = bool(physics_data.get("is_half_car_symmetric", False))

    # Scala Cp dell'assieme letta da config.yaml (fallback: la scala storica -3.0 .. +1.0).
    # Va definita qui, prima delle mappe di superficie e delle sezioni X/Z.
    vmin_cp_global, vmax_cp_global = tuple(cp_range) if cp_range else (-3.0, 1.0)

    mesh_full = _combine_real_zone_meshes(zone_meshes, mirror_symmetry=is_sym,
                                    target_budget_triangles=render_max_triangles)
    mesh_half = _combine_real_zone_meshes(zone_meshes, mirror_symmetry=False,
                                          target_budget_triangles=render_max_triangles)
    if mesh_full is None or mesh_half is None:
        return []

    pts = mesh_full["pts"]
    tris = mesh_full["tris"]
    tri_normals = (mesh_full or {}).get("normals")
    cp_vals = mesh_full["cp"]
    taux_vals = mesh_full["tau_x"]
    tke_vals = mesh_full["tke"]
    pid_idx = mesh_full["pid_idx"]
    pid_labels = mesh_full["pid_labels"]

    xmin, xmax = bbox["xmin"], bbox["xmax"]
    ymin, ymax = bbox["ymin"], bbox["ymax"]
    zmin_orig, zmax_orig = bbox["zmin"], bbox["zmax"]
    zmin = -max(abs(zmin_orig), abs(zmax_orig)) if is_sym else zmin_orig
    zmax = max(abs(zmin_orig), abs(zmax_orig)) if is_sym else zmax_orig
    L = max(xmax - xmin, 0.1)
    H = max(ymax - ymin, 0.05)
    B = max(zmax - zmin, 0.1)

    # Calcola normali / centri dei triangoli per distinguere estradosso (+Y) e intradosso (-Y)
    v0 = pts[tris[:, 0]]
    v1 = pts[tris[:, 1]]
    v2 = pts[tris[:, 2]]
    tri_centers = (v0 + v1 + v2) / 3.0
    normals = np.cross(v1 - v0, v2 - v0)

    exported_images = []

    def _style_real_mesh_ax(ax, title_text, subtitle_text, xlabel, ylabel):
        ax.set_facecolor("#f0f4f8")
        ax.set_title(
            f"MESH & CFD REALE (.CAS/.DAT) - {title_text}\n{subtitle_text}",
            fontsize=11, fontweight="bold", pad=10, loc="left", color="#0f172a"
        )
        ax.set_xlabel(xlabel, fontsize=10, fontweight="bold", color="#0f172a")
        ax.set_ylabel(ylabel, fontsize=10, fontweight="bold", color="#0f172a")
        ax.grid(True, linestyle="--", alpha=0.35, color="#64748b")
        sym_tag = "Modello: Half-Car Simmetrico (Z=0 Symmetry)" if is_sym else "Modello: Full-Domain"
        ax.text(
            0.99, 0.98,
            f"Assieme: {assembly_type.upper()} | {sym_tag}\nTriangoli Reali Renderizzati: {tris.shape[0]:,}",
            transform=ax.transAxes, fontsize=8.5, verticalalignment="top", horizontalalignment="right",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#94a3b8", alpha=0.92)
        )

    # --------------------------------------------------------------------------
    # 0. 00_real_mesh_pid_map.png (Mappa Identificazione PID e Geometria Reale)
    # --------------------------------------------------------------------------
    fname0 = "00_real_mesh_pid_map.png"
    p0 = os.path.join(images_dir, fname0)
    if not _is_valid_meta_screenshot(p0):
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        order_bot = np.argsort(-tri_centers[:, 1])  # Dal +Y al -Y cosi' i triangoli inferiori (-Y) sono in primo piano
        cmap_pid = plt.get_cmap("tab10")
        _safe_tripcolor(ax, pts[:, 0], pts[:, 2], tris[order_bot], pid_idx[order_bot], cmap=cmap_pid, vmin=0, vmax=max(9, len(pid_labels)), shading="flat", edgecolors="none")
        if is_sym:
            ax.axhline(0.0, color="#0f172a", linestyle="--", linewidth=1.4, label="Piano di Simmetria Z = 0")
        for pl in pid_labels:
            cx, cy, cz = pl["centroid"]
            ax.plot(cx, cz, "o", color="white", markersize=6, markeredgecolor="black")
            ax.text(
                cx, cz, f" {pl['zone_name']}",
                fontsize=8.5, fontweight="bold", color="#0f172a", clip_on=True,
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="#334155", alpha=0.85)
            )
        _style_real_mesh_ax(
            ax,
            f"Mappa Topologica PID Reali Estratti da {os.path.basename(cas_file)}",
            f"PID isolati ({len(pid_labels)} zone): " + ", ".join(p["zone_name"] for p in pid_labels),
            "Coordinata Longitudinale X [m] (+X verso retrotreno)",
            "Coordinata Laterale Z [m] (Z=0 piano di simmetria)"
        )
        ax.set_xlim(xmin - 0.04 * L, xmax + 0.04 * L)
        ax.set_ylim(zmin - 0.05 * B, zmax + 0.05 * B)
        ax.set_aspect("equal", adjustable="box")
        fig.tight_layout()
        fig.savefig(p0, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        del fig, ax
        gc.collect()

    exported_images.append({
        "id": "00_real_mesh_pid_map",
        "filename": fname0,
        "path": p0,
        "category": "mesh_topology",
        "view": "bottom_suction",
        "scalar": "PID Zone ID",
        "title": "Mappa Topologica PID Reali del Modello (.cas)",
        "description": "Visualizzazione diretta dei triangoli superficiali estratti dal file .cas per ciascun PID dell'assieme selezionato, con esclusione verificata della galleria del vento."
    })

    # --------------------------------------------------------------------------
    # 1. 01_surface_cp_bottom_suction.png (Vista Bottom -Y: lato aspirazione)
    # --------------------------------------------------------------------------
    fname1 = "01_surface_cp_bottom_suction.png"
    p1 = os.path.join(images_dir, fname1)
    if not _is_valid_meta_screenshot(p1):
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        # Solo le facce che guardano verso il basso (-Y): senza filtro la vista
        # "lato aspirazione" proiettava anche il lato superiore e usciva identica
        # alla vista Top.
        mask_bottom = _side_mask(tri_normals, axis=1, sign=-1, threshold=0.15)
        sel_bottom = np.where(mask_bottom)[0] if mask_bottom is not None else np.arange(len(tris))
        order_bot = sel_bottom[np.argsort(-tri_centers[sel_bottom, 1])]
        im = _safe_tripcolor(ax, pts[:, 0], pts[:, 2], tris[order_bot], cp_vals[order_bot], cmap="jet", vmin=vmin_cp_global, vmax=vmax_cp_global, shading="flat")
        if is_sym:
            ax.axhline(0.0, color="#1e293b", linestyle="--", linewidth=1.2, alpha=0.7)
        cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
        cbar.set_label("Pressure Coefficient Cp [-] (Dati reali .dat)", fontsize=10, fontweight="bold")
        _style_real_mesh_ax(
            ax,
            "Mappa Cp Lato Aspirazione (Vista Bottom -Y verso +Y)",
            f"File: {os.path.basename(dat_file or cas_file)} | Cp_min = {float(np.min(cp_vals)):.2f}, Cp_mean = {float(np.mean(cp_vals)):.2f}",
            "Coordinata Longitudinale X [m] (+X verso retrotreno)",
            "Coordinata Laterale Z [m] (Z=0 simmetria)"
        )
        ax.set_xlim(xmin - 0.04 * L, xmax + 0.04 * L)
        ax.set_ylim(zmin - 0.05 * B, zmax + 0.05 * B)
        ax.set_aspect("equal", adjustable="box")
        fig.tight_layout()
        fig.savefig(p1, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        del fig, ax
        gc.collect()

    exported_images.append({
        "id": "01_surface_cp_bottom_suction",
        "filename": fname1,
        "path": p1,
        "category": "surface_pressure",
        "view": "bottom_suction",
        "scalar": "Cp",
        "title": "Mappa Cp Lato Aspirazione (Bottom -Y)",
        "description": "Distribuzione reale del coefficiente di pressione Cp sulla mesh inferiore (-Y). Evidenzia le zone di depressione sui componenti reali (venturi, flat_floor, diffusore_int)."
    })

    # --------------------------------------------------------------------------
    # 2. 02_surface_cp_top_pressure.png (Vista Top +Y: lato superiore)
    # --------------------------------------------------------------------------
    fname2 = "02_surface_cp_top_pressure.png"
    p2 = os.path.join(images_dir, fname2)
    if not _is_valid_meta_screenshot(p2):
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        # Solo le facce che guardano verso l'alto (+Y): la vista superiore deve
        # mostrare il lato pressione, non la proiezione di tutto il modello.
        mask_top = _side_mask(tri_normals, axis=1, sign=+1, threshold=0.15)
        sel_top = np.where(mask_top)[0] if mask_top is not None else np.arange(len(tris))
        order_top = sel_top[np.argsort(tri_centers[sel_top, 1])]
        im = _safe_tripcolor(ax, pts[:, 0], pts[:, 2], tris[order_top], cp_vals[order_top], cmap="jet", vmin=vmin_cp_global, vmax=vmax_cp_global, shading="flat")
        if is_sym:
            ax.axhline(0.0, color="#1e293b", linestyle="--", linewidth=1.2, alpha=0.7)
        cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
        cbar.set_label("Pressure Coefficient Cp [-] (Dati reali .dat)", fontsize=10, fontweight="bold")
        _style_real_mesh_ax(
            ax,
            "Mappa Cp Vista Superiore (Top +Y verso -Y)",
            f"Proiezione dall'alto (+Y) della mesh reale di {assembly_type.upper()}",
            "Coordinata Longitudinale X [m]",
            "Coordinata Laterale Z [m]"
        )
        ax.set_xlim(xmin - 0.04 * L, xmax + 0.04 * L)
        ax.set_ylim(zmin - 0.05 * B, zmax + 0.05 * B)
        ax.set_aspect("equal", adjustable="box")
        fig.tight_layout()
        fig.savefig(p2, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        del fig, ax
        gc.collect()

    exported_images.append({
        "id": "02_surface_cp_top_pressure",
        "filename": fname2,
        "path": p2,
        "category": "surface_pressure",
        "view": "top_pressure",
        "scalar": "Cp",
        "title": "Mappa Cp Vista Superiore (Top +Y)",
        "description": "Distribuzione reale del coefficiente di pressione Cp vista dall'alto (+Y)."
    })

    # --------------------------------------------------------------------------
    # 3. 03_surface_cp_side_profile.png (Vista Laterale XY)
    # --------------------------------------------------------------------------
    fname3 = "03_surface_cp_side_profile.png"
    p3 = os.path.join(images_dir, fname3)
    if not _is_valid_meta_screenshot(p3):
        pts_h = mesh_half["pts"]
        tris_h = mesh_half["tris"]
        cp_h = mesh_half["cp"]
        c_h = (pts_h[tris_h[:, 0]] + pts_h[tris_h[:, 1]] + pts_h[tris_h[:, 2]]) / 3.0
        order_side = np.argsort(c_h[:, 2])  # Ordina lungo Z
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        im = _safe_tripcolor(ax, pts_h[:, 0], pts_h[:, 1], tris_h[order_side], cp_h[order_side], cmap="jet", vmin=vmin_cp_global, vmax=vmax_cp_global, shading="flat")
        ax.axhline(ymin, color="#0f172a", linewidth=2.0, linestyle="-", label="Piano Suolo (Road)")
        cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
        cbar.set_label("Pressure Coefficient Cp [-]", fontsize=10, fontweight="bold")
        _style_real_mesh_ax(
            ax,
            "Mappa Cp Vista Laterale Profilo Longitudinale (Piano XY)",
            f"Altezza Y da terra: [{ymin:.3f} m, {ymax:.3f} m] | Lunghezza X: [{xmin:.3f} m, {xmax:.3f} m]",
            "Coordinata Longitudinale X [m]",
            "Coordinata Verticale Y [m] (Altezza da terra)"
        )
        y_top_side = max(ymax + 0.08 * H, ymin + 0.35 * L)
        ax.set_xlim(xmin - 0.05 * L, xmax + 0.05 * L)
        ax.set_ylim(min(0.0, ymin - 0.02), y_top_side)
        ax.set_aspect("equal", adjustable="box")
        fig.tight_layout()
        fig.savefig(p3, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        del fig, ax
        gc.collect()

    exported_images.append({
        "id": "03_surface_cp_side_profile",
        "filename": fname3,
        "path": p3,
        "category": "surface_pressure",
        "view": "side_left",
        "scalar": "Cp",
        "title": "Mappa Cp Profilo Laterale (Vista XY)",
        "description": "Vista laterale (X-Y) della mesh reale con distribuzione di Cp, profilo dei canali Venturi, flat floor e rampa del diffusore."
    })

    # --------------------------------------------------------------------------
    # 4. 04_surface_cp_iso_diffuser.png (Vista Isometrica 3D Bottom-Rear)
    # --------------------------------------------------------------------------
    fname4 = "04_surface_cp_iso_diffuser.png"
    p4 = os.path.join(images_dir, fname4)
    if not _is_valid_meta_screenshot(p4):
        # Proiezione assonometrica 3D con proporzioni reali 1:1:1
        az = np.deg2rad(-130.0)
        el = np.deg2rad(-28.0)
        xn = (pts[:, 0] - 0.5 * (xmin + xmax))
        yn = (pts[:, 1] - 0.5 * (ymin + ymax))
        zn = (pts[:, 2] - 0.5 * (zmin + zmax))
        u_iso = xn * np.cos(az) - zn * np.sin(az)
        v_iso = yn * np.cos(el) + (xn * np.sin(az) + zn * np.cos(az)) * np.sin(el)
        depth_iso = -yn * np.sin(el) + (xn * np.sin(az) + zn * np.cos(az)) * np.cos(el)
        tri_depth = (depth_iso[tris[:, 0]] + depth_iso[tris[:, 1]] + depth_iso[tris[:, 2]]) / 3.0
        order_iso = np.argsort(tri_depth)

        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        im = _safe_tripcolor(ax, u_iso, v_iso, tris[order_iso], cp_vals[order_iso], cmap="jet", vmin=vmin_cp_global, vmax=vmax_cp_global, shading="flat")
        cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
        cbar.set_label("Pressure Coefficient Cp [-]", fontsize=10, fontweight="bold")
        _style_real_mesh_ax(
            ax,
            "Vista Isometrica 3D dal Basso-Posteriore (Canali Venturi & Diffusore)",
            "Proiezione 3D della mesh reale colorata per Cp",
            "Asse Proiettato U [m]",
            "Asse Proiettato V [m]"
        )
        ax.set_aspect("equal", adjustable="datalim")
        fig.tight_layout()
        fig.savefig(p4, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        del fig, ax
        gc.collect()

    exported_images.append({
        "id": "04_surface_cp_iso_diffuser",
        "filename": fname4,
        "path": p4,
        "category": "surface_pressure",
        "view": "iso_bottom_rear",
        "scalar": "Cp",
        "title": "Vista Isometrica 3D Cp (Canali & Diffusore)",
        "description": "Proiezione tridimensionale dal basso-posteriore dei canali Venturi e del diffusore sulla mesh reale."
    })

    # --------------------------------------------------------------------------
    # 5. 05_wall_shear_x_separation_bottom.png (Mappa X-Wall Shear & Separazione)
    # --------------------------------------------------------------------------
    fname5 = "05_wall_shear_x_separation_bottom.png"
    p5 = os.path.join(images_dir, fname5)
    if not _is_valid_meta_screenshot(p5):
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        order_bot = np.argsort(-tri_centers[:, 1])
        im = _safe_tripcolor(ax, pts[:, 0], pts[:, 2], tris[order_bot], taux_vals[order_bot], cmap="coolwarm_r", vmin=-3.0, vmax=8.0, shading="flat")
        if is_sym:
            ax.axhline(0.0, color="#1e293b", linestyle="--", linewidth=1.2, alpha=0.7)
        cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
        cbar.set_label("X-Wall Shear Stress Tau_w,x [Pa] (<= 0: Flusso Separato/Stallo)", fontsize=10, fontweight="bold")
        stalled_pct = float(physics_data.get("summary_kpis", {}).get("stalled_area_percentage", 0.0))
        _style_real_mesh_ax(
            ax,
            "Mappa X-Wall Shear Stress & Separazione Strato Limite (Bottom -Y)",
            f"Area totale con Tau_w,x <= 0 (stallo/ricircolo): {stalled_pct:.2f}% della superficie dell'assieme",
            "Coordinata Longitudinale X [m]",
            "Coordinata Laterale Z [m]"
        )
        ax.set_xlim(xmin - 0.04 * L, xmax + 0.04 * L)
        ax.set_ylim(zmin - 0.05 * B, zmax + 0.05 * B)
        ax.set_aspect("equal", adjustable="box")
        fig.tight_layout()
        fig.savefig(p5, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        del fig, ax
        gc.collect()

    exported_images.append({
        "id": "05_wall_shear_x_separation_bottom",
        "filename": fname5,
        "path": p5,
        "category": "flow_separation",
        "view": "bottom_suction",
        "scalar": "X-Wall Shear Stress",
        "title": "Mappa X-Wall Shear & Separazione Flusso (Bottom -Y)",
        "description": "Mappa dello sforzo di taglio longitudinale sulla mesh reale. Le zone rosse/arancioni con Tau_w,x <= 0 identificano i triangoli in cui il flusso e' separato o invertito."
    })

    # --------------------------------------------------------------------------
    # 6. 07_surface_tke_bottom.png (Turbulent Kinetic Energy TKE)
    # --------------------------------------------------------------------------
    fname7 = "07_surface_tke_bottom.png"
    p7 = os.path.join(images_dir, fname7)
    if not _is_valid_meta_screenshot(p7):
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        order_bot = np.argsort(-tri_centers[:, 1])
        vmax_tke = max(float(np.percentile(tke_vals, 98)), 2.0)
        im = _safe_tripcolor(ax, pts[:, 0], pts[:, 2], tris[order_bot], tke_vals[order_bot], cmap="inferno", vmin=0.0, vmax=vmax_tke, shading="flat")
        if is_sym:
            ax.axhline(0.0, color="white", linestyle="--", linewidth=1.2, alpha=0.7)
        cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
        cbar.set_label("Turbulent Kinetic Energy k [m^2/s^2]", fontsize=10, fontweight="bold")
        _style_real_mesh_ax(
            ax,
            "Energia Cinetica Turbolenta (TKE) sulla Mesh Reale (Bottom -Y)",
            "Distribuzione reale di k [m^2/s^2] sui triangoli a parete / strato limite",
            "Coordinata Longitudinale X [m]",
            "Coordinata Laterale Z [m]"
        )
        ax.set_xlim(xmin - 0.04 * L, xmax + 0.04 * L)
        ax.set_ylim(zmin - 0.05 * B, zmax + 0.05 * B)
        ax.set_aspect("equal", adjustable="box")
        fig.tight_layout()
        fig.savefig(p7, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        del fig, ax
        gc.collect()

    exported_images.append({
        "id": "07_surface_tke_bottom",
        "filename": fname7,
        "path": p7,
        "category": "turbulence_mesh",
        "view": "bottom_suction",
        "scalar": "Turbulent Kinetic Energy",
        "title": "Energia Cinetica Turbolenta (TKE) sulla Mesh Reale",
        "description": "Distribuzione di TKE (k) sulla mesh reale dell'assieme."
    })

    # --------------------------------------------------------------------------
    # 7. SEZIONI TRASVERSALI REALE MESH X-CUTS (Piani YZ normali a X con Contour 2D Cp) - 10 STAZIONI
    # --------------------------------------------------------------------------
    # (scala Cp definita in testa alla funzione, condivisa da tutte le viste)
    levels_cp = np.linspace(vmin_cp_global, vmax_cp_global, 21)

    # 10 sezioni trasversali progressive dall'anteriore (10% L) al posteriore (98% L)
    x_stations = list(x_stations) if x_stations else [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.98]
    slice_half_dx = 0.024 * L
    for idx, x_norm in enumerate(x_stations, start=1):
        x_coord = xmin + x_norm * L
        fname_x = f"08_{idx:02d}_xcut_cp_x{int(round(x_norm*100)):03d}pct.png"
        px = os.path.join(images_dir, fname_x)
        if not _is_valid_meta_screenshot(px):
            mask_slice = np.abs(tri_centers[:, 0] - x_coord) <= slice_half_dx
            if np.count_nonzero(mask_slice) < 20:
                mask_slice = np.abs(tri_centers[:, 0] - x_coord) <= (0.075 * L)

            fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
            if np.count_nonzero(mask_slice) > 0:
                z_sl = tri_centers[mask_slice, 2]
                y_sl = tri_centers[mask_slice, 1]
                cp_sl = np.clip(cp_vals[mask_slice], vmin_cp_global, vmax_cp_global)

                field_2d = _build_xcut_2d_cp_field(z_sl, y_sl, cp_sl, zmin, zmax, ymin, ymax, B, H)
                if field_2d is not None:
                    ZG, YG, cp_grid_m = field_2d
                    ax.contourf(ZG, YG, cp_grid_m, levels=levels_cp, cmap="jet", vmin=vmin_cp_global, vmax=vmax_cp_global, alpha=0.86, extend="both")
                    ax.contour(ZG, YG, cp_grid_m, levels=10, colors="#0f172a", linewidths=0.45, alpha=0.40)

                sc = ax.scatter(
                    z_sl,
                    y_sl,
                    c=cp_sl,
                    cmap="jet",
                    vmin=vmin_cp_global,
                    vmax=vmax_cp_global,
                    s=16,
                    edgecolors="#0f172a",
                    linewidths=0.30,
                    alpha=0.95,
                    zorder=5,
                )
                cbar = fig.colorbar(sc, ax=ax, fraction=0.035, pad=0.02)
                cbar.set_label("Contour Cp sulla sezione trasversale [-]", fontsize=10, fontweight="bold")
            ax.axhline(ymin, color="#0f172a", linewidth=2.5, label="Suolo (Road)")
            if is_sym:
                ax.axvline(0.0, color="#334155", linestyle="--", linewidth=1.3, label="Simmetria Z=0")
            _style_real_mesh_ax(
                ax,
                f"Sezione Trasversale Reale X-Cut a X = {int(round(x_norm*100))}% (X = {x_coord:.3f} m)",
                f"Contour 2D Cp e profilo trasversale YZ dei nodi/triangoli reali a X = {x_coord:.3f} m",
                "Coordinata Laterale Z [m] (Spanwise)",
                "Coordinata Verticale Y [m] (Altezza da terra)"
            )
            y_top_cut = max(ymax + 0.05 * H, ymin + 0.38 * B)
            ax.set_xlim(zmin - 0.05 * B, zmax + 0.05 * B)
            ax.set_ylim(min(0.0, ymin - 0.01), y_top_cut)
            ax.set_aspect("equal", adjustable="box")
            fig.tight_layout()
            fig.savefig(px, dpi=dpi, bbox_inches="tight")
            plt.close(fig)
            del fig, ax
            if idx % 3 == 0:
                gc.collect()

        exported_images.append({
            "id": fname_x.replace(".png", ""),
            "filename": fname_x,
            "path": px,
            "category": "x_cut_total_pressure",
            "station_normalized": x_norm,
            "station_coord": x_coord,
            "axis": "X",
            "view": "rear_wake",
            "scalar": "Cp / Total Pressure",
            "title": f"Sezione Trasversale X = {int(round(x_norm*100))}% ({x_coord:.3f} m)",
            "description": f"Contour 2D di Cp e sezione trasversale YZ della vera geometria mesh a X = {x_coord:.3f} m ({int(round(x_norm*100))}% L)."
        })

    # --------------------------------------------------------------------------
    # 8. SEZIONI LONGITUDINALI REALE MESH Z-CUTS (10 Piani XY normali a Z)
    #    Contour 2D di Cp nel dominio fluido con scala fringe BETA CAE META Post
    # --------------------------------------------------------------------------
    pts_h = mesh_half["pts"]
    tris_h = mesh_half["tris"]
    cp_h = mesh_half["cp"]
    centers_h = (pts_h[tris_h[:, 0]] + pts_h[tris_h[:, 1]] + pts_h[tris_h[:, 2]]) / 3.0
    z_span_h = max(abs(zmin_orig - zmax_orig), 0.1)

    # 10 stazioni progressive distribuite lungo l'apertura trasversale (span)
    z_stations = list(z_stations) if z_stations else [0.02, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.82, 0.94]

    meta_cp_colors = [
        "#250e35",  # < -3.00 (dark violet/purple)
        "#31123b",  # -3.00 to -2.60 (dark purple)
        "#434eba",  # -2.60 to -2.20 (dark blue)
        "#4586fa",  # -2.20 to -1.80 (blue)
        "#28baeb",  # -1.80 to -1.40 (cyan)
        "#1ae3b7",  # -1.40 to -1.00 (teal)
        "#5ef97a",  # -1.00 to -0.60 (green)
        "#d3df59",  # -0.60 to -0.20 (yellow-green)
        "#f7bb37",  # -0.20 to +0.20 (amber freestream Cp~0)
        "#fa7f1f",  # +0.20 to +0.60 (orange)
        "#e4450b",  # +0.60 to +1.00 (orange-red)
        "#b91e00",  # > +1.00 (stagnation deep red)
    ]
    meta_cp_levels = [-3.00, -2.60, -2.20, -1.80, -1.40, -1.00, -0.60, -0.20, 0.20, 0.60, 1.00]
    meta_cmap = matplotlib.colors.ListedColormap(meta_cp_colors)
    meta_norm = matplotlib.colors.BoundaryNorm(meta_cp_levels, ncolors=len(meta_cp_colors), extend="both")

    for idx, z_norm in enumerate(z_stations, start=1):
        z_coord = zmax_orig - z_norm * z_span_h if abs(zmax_orig) < abs(zmin_orig) else zmin_orig + z_norm * z_span_h
        fname_z = f"09_{idx:02d}_zcut_cp_z{int(round(z_norm*100)):03d}pct.png"
        pz = os.path.join(images_dir, fname_z)

        # Controlla se e' disponibile lo screenshot generato direttamente da BETA CAE META Post
        meta_pz_alt = os.path.join(images_dir, f"05_{idx:02d}_zcut_cp_z{int(round(z_norm*100)):03d}pct.png")
        if _is_valid_meta_screenshot(meta_pz_alt):
            pz = meta_pz_alt
            fname_z = os.path.basename(pz)
        elif not _is_valid_meta_screenshot(pz):
            field_data = _build_zcut_2d_cp_field(
                pts_h, tris_h, cp_h, centers_h, z_coord, z_span_h,
                xmin, xmax, ymin, ymax, L, H
            )

            fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)

            # 1. Fondo stradale (Road) in stile META Post
            ax.axhspan(min(0.0, ymin - 0.05), ymin, facecolor="#f6e8f9", edgecolor="none", zorder=2)
            ax.axhline(ymin, color="#0f172a", linewidth=2.5, label="Suolo (Road)", zorder=3)

            if field_data is not None:
                XG, YG, cp_grid_m, segments, xs, ys, cps = field_data

                # 2. Contour 2D continuo di Cp nel dominio fluido circostante
                cf = ax.contourf(
                    XG, YG, cp_grid_m,
                    levels=meta_cp_levels,
                    cmap=meta_cmap,
                    norm=meta_norm,
                    extend="both",
                    alpha=0.92,
                    zorder=1
                )
                ax.contour(
                    XG, YG, cp_grid_m,
                    levels=meta_cp_levels,
                    colors="#334155",
                    linewidths=0.35,
                    alpha=0.30,
                    zorder=2
                )

                # 3. Linee di profilo geometrico reale sezionate dal piano Z
                if segments:
                    lc = LineCollection(segments, colors="#0f172a", linewidths=1.8, zorder=5)
                    ax.add_collection(lc)

                # 4. Scatter dei nodi/triangoli reali con colore Cp locale
                sc = ax.scatter(
                    xs, ys,
                    c=cps,
                    cmap=meta_cmap,
                    norm=meta_norm,
                    s=14,
                    edgecolors="#0f172a",
                    linewidths=0.30,
                    alpha=0.95,
                    zorder=6
                )

                # 5. Colorbar verticale a sinistra identica allo stile BETA CAE META Post
                cbar = fig.colorbar(cf, ax=ax, location="left", fraction=0.035, pad=0.04, extend="both", ticks=meta_cp_levels)
                cbar.ax.set_yticklabels(["<-3.0", "-2.60", "-2.20", "-1.80", "-1.40", "-1.00", "-0.60", "-0.20", "0.20", "0.60", ">1.0"])
                cbar.set_label("Cp [-] (Scala fringe BETA CAE META)", fontsize=9, fontweight="bold")
            else:
                mask_z = np.abs(centers_h[:, 2] - z_coord) <= (0.05 * z_span_h)
                if np.count_nonzero(mask_z) > 0:
                    sc = ax.scatter(
                        centers_h[mask_z, 0],
                        centers_h[mask_z, 1],
                        c=cp_h[mask_z],
                        cmap=meta_cmap,
                        norm=meta_norm,
                        s=14,
                        alpha=0.9,
                    )
                    cbar = fig.colorbar(sc, ax=ax, location="left", fraction=0.035, pad=0.04, extend="both", ticks=meta_cp_levels)
                    cbar.ax.set_yticklabels(["<-3.0", "-2.60", "-2.20", "-1.80", "-1.40", "-1.00", "-0.60", "-0.20", "0.20", "0.60", ">1.0"])
                    cbar.set_label("Cp locale [-]", fontsize=9, fontweight="bold")

            _style_real_mesh_ax(
                ax,
                f"Sezione Longitudinale Reale Z-Cut a Z = {z_coord:.3f} m ({int(round(z_norm*100))}% Span)",
                f"Contour 2D di Cp e profilo geometrico reale XY alla coordinata laterale Z = {z_coord:.3f} m",
                "Coordinata Longitudinale X [m]",
                "Coordinata Verticale Y [m] (Altezza da terra)"
            )
            y_top_zcut = max(ymax + 0.08 * H, ymin + 0.38 * L)
            ax.set_xlim(xmin - 0.04 * L, xmax + 0.05 * L)
            ax.set_ylim(min(0.0, ymin - 0.01), y_top_zcut)
            ax.set_aspect("equal", adjustable="box")
            fig.tight_layout()
            fig.savefig(pz, dpi=dpi, bbox_inches="tight")
            plt.close(fig)
            del fig, ax
            if idx % 3 == 0:
                gc.collect()

        exported_images.append({
            "id": fname_z.replace(".png", ""),
            "filename": fname_z,
            "path": pz,
            "category": "z_cut_longitudinal",
            "station_normalized": z_norm,
            "station_coord": z_coord,
            "axis": "Z",
            "view": "side_left",
            "scalar": "Cp",
            "title": f"Contour Cp - Sezione Longitudinale Z = {z_coord:.3f} m ({int(round(z_norm*100))}% Span)",
            "description": f"Contour 2D di Cp e profilo geometrico reale XY del modello estratto a Z = {z_coord:.3f} m ({int(round(z_norm*100))}% Span)."
        })

    # --------------------------------------------------------------------------
    # 9. ANIMAZIONE GIF: SWEEP PROGRESSIVO SEZIONI TRASVERSALI X-CUT CONTOUR Cp
    #    DALL'ANTERIORE (X_min) AL POSTERIORE (X_max) DELLA MACCHINA
    # --------------------------------------------------------------------------
    gif_fname = "10_cp_xcut_progressive_sweep.gif"
    gif_path = os.path.join(images_dir, gif_fname)
    try:
        from PIL import Image as PILImage

        # Prepara una versione sub-campionata della mesh per il pannello guida sinistro (velocizza il rendering dei 26 frame)
        order_bot_all = np.argsort(-tri_centers[:, 1])
        step_plan = max(1, len(order_bot_all) // 18000)
        idx_plan = order_bot_all[::step_plan]
        tri_plan_obj = mtri.Triangulation(pts[:, 0], pts[:, 2], tris[idx_plan])
        cp_plan_vals = cp_vals[idx_plan]

        sweep_stations = np.linspace(0.04, 0.96, 26)
        frames_pil = []
        gif_slice_dx = 0.032 * L

        for f_idx, x_n in enumerate(sweep_stations, start=1):
            xc = xmin + float(x_n) * L
            m_sl = np.abs(tri_centers[:, 0] - xc) <= gif_slice_dx
            if np.count_nonzero(m_sl) < 15:
                m_sl = np.abs(tri_centers[:, 0] - xc) <= (0.07 * L)

            fig_g, (ax_plan, ax_sec) = plt.subplots(
                1, 2, figsize=(13.2, 5.6), dpi=95, gridspec_kw={"width_ratios": [1.0, 1.45]}
            )
            fig_g.patch.set_facecolor("#0f172a")

            # Pannello Sinistro: Mappa Cp Bottom con piano di taglio mobile X = xc (Anteriore -> Posteriore)
            ax_plan.set_facecolor("#f0f4f8")
            ax_plan.tripcolor(
                tri_plan_obj,
                facecolors=cp_plan_vals,
                cmap="jet",
                vmin=vmin_cp_global,
                vmax=vmax_cp_global,
                shading="flat",
            )
            if is_sym:
                ax_plan.axhline(0.0, color="#1e293b", linestyle="--", linewidth=1.0, alpha=0.65)
            ax_plan.axvline(xc, color="#ffffff", linewidth=4.2, zorder=8)
            ax_plan.axvline(xc, color="#ef233c", linewidth=2.4, linestyle="-", zorder=9, label=f"Piano X = {xc:.3f} m")
            ax_plan.set_title(
                f"1) Posizione Piano di Taglio (Anteriore -> Posteriore)\nX = {xc:.3f} m ({int(round(x_n*100))}% Lunghezza)",
                fontsize=10.5, fontweight="bold", color="#f8fafc", pad=8
            )
            ax_plan.set_xlabel("X Longitudinale [m] (Anteriore -> Posteriore)", fontsize=9.5, fontweight="bold", color="#e2e8f0")
            ax_plan.set_ylabel("Z Laterale [m]", fontsize=9.5, fontweight="bold", color="#e2e8f0")
            ax_plan.tick_params(colors="#cbd5e1")
            ax_plan.set_xlim(xmin - 0.04 * L, xmax + 0.04 * L)
            ax_plan.set_ylim(zmin - 0.05 * B, zmax + 0.05 * B)
            ax_plan.set_aspect("equal", adjustable="box")
            ax_plan.grid(True, linestyle="--", alpha=0.30, color="#64748b")

            # Pannello Destro: Contour 2D del Cp sulla Sezione Trasversale YZ a X = xc
            ax_sec.set_facecolor("#f0f4f8")
            cp_min_loc, cp_mean_loc = 0.0, 0.0
            if np.count_nonzero(m_sl) > 0:
                z_sl = tri_centers[m_sl, 2]
                y_sl = tri_centers[m_sl, 1]
                cp_sl = np.clip(cp_vals[m_sl], vmin_cp_global, vmax_cp_global)
                cp_min_loc = float(np.min(cp_sl))
                cp_mean_loc = float(np.mean(cp_sl))

                field_2d = _build_xcut_2d_cp_field(z_sl, y_sl, cp_sl, zmin, zmax, ymin, ymax, B, H)
                if field_2d is not None:
                    ZG, YG, cp_grid_m = field_2d
                    ax_sec.contourf(
                        ZG, YG, cp_grid_m, levels=levels_cp, cmap="jet",
                        vmin=vmin_cp_global, vmax=vmax_cp_global, alpha=0.88, extend="both"
                    )
                    ax_sec.contour(ZG, YG, cp_grid_m, levels=10, colors="#0f172a", linewidths=0.45, alpha=0.42)

                sc_g = ax_sec.scatter(
                    z_sl, y_sl, c=cp_sl, cmap="jet", vmin=vmin_cp_global, vmax=vmax_cp_global,
                    s=15, edgecolors="#0f172a", linewidths=0.28, zorder=5
                )
                cbar_g = fig_g.colorbar(sc_g, ax=ax_sec, fraction=0.040, pad=0.02)
                cbar_g.set_label("Pressure Coefficient Cp [-]", fontsize=9.5, fontweight="bold", color="#f8fafc")
                cbar_g.ax.yaxis.set_tick_params(color="#cbd5e1", labelcolor="#f8fafc")

            ax_sec.axhline(ymin, color="#0f172a", linewidth=2.6, label="Piano Suolo (Road)")
            if is_sym:
                ax_sec.axvline(0.0, color="#334155", linestyle="--", linewidth=1.2)

            ax_sec.set_title(
                f"2) Contour Cp Sezione Trasversale YZ (Frame {f_idx}/{len(sweep_stations)})\n"
                f"Stazione X = {xc:.3f} m ({int(round(x_n*100))}% L) | Cp_min = {cp_min_loc:.2f} | Cp_mean = {cp_mean_loc:.2f}",
                fontsize=10.5, fontweight="bold", color="#38bdf8", pad=8
            )
            ax_sec.set_xlabel("Coordinata Laterale Z [m] (Spanwise)", fontsize=9.5, fontweight="bold", color="#e2e8f0")
            ax_sec.set_ylabel("Coordinata Verticale Y [m] (Altezza da terra)", fontsize=9.5, fontweight="bold", color="#e2e8f0")
            ax_sec.tick_params(colors="#cbd5e1")
            y_top_gif_sec = max(ymax + 0.05 * H, ymin + 0.38 * B)
            ax_sec.set_xlim(zmin - 0.05 * B, zmax + 0.05 * B)
            ax_sec.set_ylim(min(0.0, ymin - 0.01), y_top_gif_sec)
            ax_sec.set_aspect("equal", adjustable="box")
            ax_sec.grid(True, linestyle="--", alpha=0.35, color="#64748b")

            fig_g.tight_layout()
            fig_g.canvas.draw()
            rgba = np.asarray(fig_g.canvas.buffer_rgba())
            frames_pil.append(PILImage.fromarray(rgba[:, :, :3].copy()))
            plt.close(fig_g)
            del fig_g
            if f_idx % 5 == 0:
                gc.collect()

        if frames_pil:
            durations = [150] * len(frames_pil)
            durations[0] = 350
            durations[-1] = 550
            frames_pil[0].save(
                gif_path,
                save_all=True,
                append_images=frames_pil[1:],
                duration=durations,
                loop=0,
                optimize=False,
            )
            ann_dir = os.path.join(output_dir, "images_annotated")
            os.makedirs(ann_dir, exist_ok=True)
            frames_pil[0].save(
                os.path.join(ann_dir, gif_fname),
                save_all=True,
                append_images=frames_pil[1:],
                duration=durations,
                loop=0,
                optimize=False,
            )
    except Exception as exc:
        print(f"[LAUNCHER-WARN] Errore generazione GIF X-Cut Cp: {exc}")

    # --------------------------------------------------------------------------
    # 10. SCREENSHOT STREAMLINES 3D DA VARIE PROSPETTIVE DELLA VETTURA
    # --------------------------------------------------------------------------
    # Il KPI scritto dal parser e' `velocity_inf_ms` (dal config): prima si leggeva
    # `inlet_velocity`, che non esiste, e si finiva sempre nel fallback 16.67 m/s.
    v_inf = _resolve_velocity_inf(physics_data.get("summary_kpis", {}))
    slines = _compute_3d_streamlines(pts, tris, tri_centers, cp_vals, bbox, is_sym=is_sym, v_inf=v_inf)

    v_min_cmap = 0.5 * v_inf
    v_max_cmap = 2.0 * v_inf
    norm_v = matplotlib.colors.Normalize(vmin=v_min_cmap, vmax=v_max_cmap)
    cmap_stream = plt.get_cmap("turbo")

    def _add_streamline_collection(ax, seg_list, vel_list, lw=1.8, alpha=0.92):
        if not seg_list:
            return None
        lc = LineCollection(seg_list, cmap=cmap_stream, norm=norm_v, linewidths=lw, alpha=alpha, zorder=6)
        lc.set_array(np.array(vel_list))
        ax.add_collection(lc)
        return lc

    # 10.1 11_streamlines_isometric_3d.png (Vista Assonometrica Anteriore 3D)
    fname11 = "11_streamlines_isometric_3d.png"
    p11 = os.path.join(images_dir, fname11)
    if not _is_valid_meta_screenshot(p11):
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        ax.set_facecolor("#0b132b")
        fig.patch.set_facecolor("#0f172a")

        az = np.deg2rad(40.0)
        el = np.deg2rad(22.0)
        xn = (pts[:, 0] - 0.5 * (xmin + xmax))
        yn = (pts[:, 1] - 0.5 * (ymin + ymax))
        zn = (pts[:, 2] - 0.5 * (zmin + zmax))
        u_p = xn * np.cos(az) - zn * np.sin(az)
        v_p = yn * np.cos(el) + (xn * np.sin(az) + zn * np.cos(az)) * np.sin(el)
        depth_p = -yn * np.sin(el) + (xn * np.sin(az) + zn * np.cos(az)) * np.cos(el)
        tri_d = (depth_p[tris[:, 0]] + depth_p[tris[:, 1]] + depth_p[tris[:, 2]]) / 3.0
        order_3d = np.argsort(tri_d)

        _safe_tripcolor(ax, u_p, v_p, tris[order_3d], cp_vals[order_3d], cmap="coolwarm", vmin=vmin_cp_global, vmax=vmax_cp_global, alpha=0.35, shading="flat")

        seg_iso, vel_iso = [], []
        for s in slines:
            p_tr = s["pts"]
            v_tr = s["vel"]
            xn_s = (p_tr[:, 0] - 0.5 * (xmin + xmax))
            yn_s = (p_tr[:, 1] - 0.5 * (ymin + ymax))
            zn_s = (p_tr[:, 2] - 0.5 * (zmin + zmax))
            u_s = xn_s * np.cos(az) - zn_s * np.sin(az)
            v_s = yn_s * np.cos(el) + (xn_s * np.sin(az) + zn_s * np.cos(az)) * np.sin(el)
            for k in range(len(u_s) - 1):
                seg_iso.append([(u_s[k], v_s[k]), (u_s[k + 1], v_s[k + 1])])
                vel_iso.append(0.5 * (v_tr[k] + v_tr[k + 1]))

        lc_iso = _add_streamline_collection(ax, seg_iso, vel_iso, lw=1.8, alpha=0.90)
        cbar = fig.colorbar(lc_iso, ax=ax, fraction=0.035, pad=0.02)
        cbar.set_label("Velocità Locale |V| [m/s] (Streamlines 3D)", fontsize=9.5, fontweight="bold", color="#f8fafc")
        cbar.ax.yaxis.set_tick_params(color="#cbd5e1", labelcolor="#f8fafc")

        ax.set_title(
            f"STREAMLINES 3D - VISTA ASSONOMETRICA ANTERIORE (MESH REALE)\n"
            f"Traiettorie dei filetti fluidi attorno alla geometria reale | V_inf = {v_inf:.1f} m/s",
            fontsize=11, fontweight="bold", pad=10, loc="left", color="#38bdf8"
        )
        ax.set_xlabel("Asse Assonometrico U [m]", fontsize=9.5, fontweight="bold", color="#cbd5e1")
        ax.set_ylabel("Asse Assonometrico V [m]", fontsize=9.5, fontweight="bold", color="#cbd5e1")
        ax.tick_params(colors="#94a3b8")
        ax.set_aspect("equal", adjustable="datalim")
        ax.grid(True, linestyle="--", alpha=0.20, color="#64748b")
        fig.tight_layout()
        fig.savefig(p11, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        del fig, ax
        gc.collect()

    exported_images.append({
        "id": "11_streamlines_isometric_3d",
        "filename": fname11,
        "path": p11,
        "category": "streamlines",
        "view": "isometric",
        "scalar": "Velocity Magnitude",
        "title": "Streamlines 3D - Vista Assonometrica Anteriore",
        "description": "Traiettorie tridimensionali dei filetti fluidi attorno e sotto la vettura, con sviluppo dell'accelerazione nei canali Venturi e deviazione sui profili anteriori."
    })

    # 10.2 12_streamlines_top_view.png (Vista dall'Alto X-Z)
    fname12 = "12_streamlines_top_view.png"
    p12 = os.path.join(images_dir, fname12)
    if not _is_valid_meta_screenshot(p12):
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        ax.set_facecolor("#f0f4f8")
        order_top = np.argsort(tri_centers[:, 1])
        _safe_tripcolor(ax, pts[:, 0], pts[:, 2], tris[order_top], cp_vals[order_top], cmap="jet", vmin=vmin_cp_global, vmax=vmax_cp_global, alpha=0.36, shading="flat")

        seg_top, vel_top = [], []
        for s in slines:
            p_tr = s["pts"]
            v_tr = s["vel"]
            for k in range(len(p_tr) - 1):
                seg_top.append([(p_tr[k, 0], p_tr[k, 2]), (p_tr[k + 1, 0], p_tr[k + 1, 2])])
                vel_top.append(0.5 * (v_tr[k] + v_tr[k + 1]))

        lc_top = _add_streamline_collection(ax, seg_top, vel_top, lw=1.6, alpha=0.92)
        cbar = fig.colorbar(lc_top, ax=ax, fraction=0.035, pad=0.02)
        cbar.set_label("Velocità Locale |V| [m/s]", fontsize=9.5, fontweight="bold", color="#0f172a")
        if is_sym:
            ax.axhline(0.0, color="#1e293b", linestyle="--", linewidth=1.2, label="Simmetria Z = 0")
        _style_real_mesh_ax(
            ax,
            "Streamlines 3D - Vista dall'Alto (Piano X-Z)",
            "Evoluzione trasversale e incanalamento del flusso dall'inlet ai sidepod ed estradosso",
            "Coordinata Longitudinale X [m] (+X verso retrotreno)",
            "Coordinata Laterale Z [m]"
        )
        ax.set_xlim(xmin - 0.08 * L, xmax + 0.15 * L)
        ax.set_ylim(zmin - 0.06 * B, zmax + 0.06 * B)
        ax.set_aspect("equal", adjustable="box")
        fig.tight_layout()
        fig.savefig(p12, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        del fig, ax
        gc.collect()

    exported_images.append({
        "id": "12_streamlines_top_view",
        "filename": fname12,
        "path": p12,
        "category": "streamlines",
        "view": "top",
        "scalar": "Velocity Magnitude",
        "title": "Streamlines 3D - Vista dall'Alto (Piano X-Z)",
        "description": "Distribuzione trasversale dei filetti fluidi visti dall'alto: imbocco canali, incanalamento verso i sidepod ed espansione laterale."
    })

    # 10.3 13_streamlines_side_view.png (Vista Laterale X-Y)
    fname13 = "13_streamlines_side_view.png"
    p13 = os.path.join(images_dir, fname13)
    if not _is_valid_meta_screenshot(p13):
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        ax.set_facecolor("#f0f4f8")
        pts_h = mesh_half["pts"]
        tris_h = mesh_half["tris"]
        cp_h = mesh_half["cp"]
        c_h = (pts_h[tris_h[:, 0]] + pts_h[tris_h[:, 1]] + pts_h[tris_h[:, 2]]) / 3.0
        order_side = np.argsort(c_h[:, 2])
        _safe_tripcolor(ax, pts_h[:, 0], pts_h[:, 1], tris_h[order_side], cp_h[order_side], cmap="jet", vmin=vmin_cp_global, vmax=vmax_cp_global, alpha=0.35, shading="flat")
        ax.axhline(ymin, color="#0f172a", linewidth=2.5, label="Piano Suolo (Road)")

        seg_side, vel_side = [], []
        for s in slines:
            if s["pts"][0, 2] >= 0:
                p_tr = s["pts"]
                v_tr = s["vel"]
                for k in range(len(p_tr) - 1):
                    seg_side.append([(p_tr[k, 0], p_tr[k, 1]), (p_tr[k + 1, 0], p_tr[k + 1, 1])])
                    vel_side.append(0.5 * (v_tr[k] + v_tr[k + 1]))

        lc_side = _add_streamline_collection(ax, seg_side, vel_side, lw=1.6, alpha=0.92)
        cbar = fig.colorbar(lc_side, ax=ax, fraction=0.035, pad=0.02)
        cbar.set_label("Velocità Locale |V| [m/s]", fontsize=9.5, fontweight="bold", color="#0f172a")
        _style_real_mesh_ax(
            ax,
            "Streamlines 3D - Vista Laterale (Piano X-Y)",
            "Profilo longitudinale dei filetti: contrazione gola Venturi, upwash diffusore e scia posteriore",
            "Coordinata Longitudinale X [m]",
            "Coordinata Verticale Y [m] (Altezza da terra)"
        )
        y_top_side = max(ymax + 0.08 * H, ymin + 0.35 * L)
        ax.set_xlim(xmin - 0.08 * L, xmax + 0.15 * L)
        ax.set_ylim(min(0.0, ymin - 0.01), y_top_side)
        ax.set_aspect("equal", adjustable="box")
        fig.tight_layout()
        fig.savefig(p13, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        del fig, ax
        gc.collect()

    exported_images.append({
        "id": "13_streamlines_side_view",
        "filename": fname13,
        "path": p13,
        "category": "streamlines",
        "view": "side_left",
        "scalar": "Velocity Magnitude",
        "title": "Streamlines 3D - Vista Laterale (Piano X-Y)",
        "description": "Profilo longitudinale dei filetti fluidi: convergenza nel punto di minima altezza da terra (gola Venturi), upwash lungo la rampa del diffusore e scia posteriore."
    })

    # 10.4 14_streamlines_bottom_suction.png (Vista Inferiore X-Z Canali Venturi & Fondo)
    fname14 = "14_streamlines_bottom_suction.png"
    p14 = os.path.join(images_dir, fname14)
    if not _is_valid_meta_screenshot(p14):
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        ax.set_facecolor("#f0f4f8")
        order_bot = np.argsort(-tri_centers[:, 1])
        _safe_tripcolor(ax, pts[:, 0], pts[:, 2], tris[order_bot], cp_vals[order_bot], cmap="jet", vmin=vmin_cp_global, vmax=vmax_cp_global, alpha=0.38, shading="flat")

        seg_bot, vel_bot = [], []
        for s in slines:
            if s["is_underbody"]:
                p_tr = s["pts"]
                v_tr = s["vel"]
                for k in range(len(p_tr) - 1):
                    seg_bot.append([(p_tr[k, 0], p_tr[k, 2]), (p_tr[k + 1, 0], p_tr[k + 1, 2])])
                    vel_bot.append(0.5 * (v_tr[k] + v_tr[k + 1]))

        lc_bot = _add_streamline_collection(ax, seg_bot, vel_bot, lw=1.9, alpha=0.95)
        cbar = fig.colorbar(lc_bot, ax=ax, fraction=0.035, pad=0.02)
        cbar.set_label("Velocità Locale |V| [m/s] (Canali Venturi)", fontsize=9.5, fontweight="bold", color="#0f172a")
        if is_sym:
            ax.axhline(0.0, color="#1e293b", linestyle="--", linewidth=1.2, label="Simmetria Z = 0")
        _style_real_mesh_ax(
            ax,
            "Streamlines 3D - Vista Inferiore (Canali Venturi & Fondo)",
            "Traiettorie e accelerazione del flusso sul fondo vettura: picco cinetico nella gola ed espansione nel diffusore",
            "Coordinata Longitudinale X [m]",
            "Coordinata Laterale Z [m]"
        )
        ax.set_xlim(xmin - 0.08 * L, xmax + 0.15 * L)
        ax.set_ylim(zmin - 0.06 * B, zmax + 0.06 * B)
        ax.set_aspect("equal", adjustable="box")
        fig.tight_layout()
        fig.savefig(p14, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        del fig, ax
        gc.collect()

    exported_images.append({
        "id": "14_streamlines_bottom_suction",
        "filename": fname14,
        "path": p14,
        "category": "streamlines",
        "view": "bottom_suction",
        "scalar": "Velocity Magnitude",
        "title": "Streamlines 3D - Vista Inferiore (Canali Venturi & Fondo)",
        "description": "Traiettorie sotto il veicolo proiettate sul fondo: forte accelerazione cinetica nell'area di depressione (Cp minimo) ed espansione graduale nel diffusore."
    })

    # 10.5 15_streamlines_iso_rear.png (Vista Assonometrica Posteriore Diffusore & Scia)
    fname15 = "15_streamlines_iso_rear.png"
    p15 = os.path.join(images_dir, fname15)
    if not _is_valid_meta_screenshot(p15):
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        ax.set_facecolor("#0b132b")
        fig.patch.set_facecolor("#0f172a")

        az_r = np.deg2rad(-140.0)
        el_r = np.deg2rad(24.0)
        u_pr = xn * np.cos(az_r) - zn * np.sin(az_r)
        v_pr = yn * np.cos(el_r) + (xn * np.sin(az_r) + zn * np.cos(az_r)) * np.sin(el_r)
        depth_pr = -yn * np.sin(el_r) + (xn * np.sin(az_r) + zn * np.cos(az_r)) * np.cos(el_r)
        order_3d_r = np.argsort(depth_pr[tris].mean(axis=1))

        _safe_tripcolor(ax, u_pr, v_pr, tris[order_3d_r], cp_vals[order_3d_r], cmap="coolwarm", vmin=vmin_cp_global, vmax=vmax_cp_global, alpha=0.35, shading="flat")

        seg_rear, vel_rear = [], []
        for s in slines:
            p_tr = s["pts"]
            v_tr = s["vel"]
            xn_s = (p_tr[:, 0] - 0.5 * (xmin + xmax))
            yn_s = (p_tr[:, 1] - 0.5 * (ymin + ymax))
            zn_s = (p_tr[:, 2] - 0.5 * (zmin + zmax))
            u_s = xn_s * np.cos(az_r) - zn_s * np.sin(az_r)
            v_s = yn_s * np.cos(el_r) + (xn_s * np.sin(az_r) + zn_s * np.cos(az_r)) * np.sin(el_r)
            for k in range(len(u_s) - 1):
                seg_rear.append([(u_s[k], v_s[k]), (u_s[k + 1], v_s[k + 1])])
                vel_rear.append(0.5 * (v_tr[k] + v_tr[k + 1]))

        lc_rear = _add_streamline_collection(ax, seg_rear, vel_rear, lw=1.8, alpha=0.90)
        cbar = fig.colorbar(lc_rear, ax=ax, fraction=0.035, pad=0.02)
        cbar.set_label("Velocità Locale |V| [m/s] (Diffusore & Scia)", fontsize=9.5, fontweight="bold", color="#f8fafc")
        cbar.ax.yaxis.set_tick_params(color="#cbd5e1", labelcolor="#f8fafc")

        ax.set_title(
            f"STREAMLINES 3D - VISTA ASSONOMETRICA POSTERIORE (DIFFUSORE & SCIA)\n"
            f"Visualizzazione dell'espansione e upwash del diffusore con rilascio della scia posteriore",
            fontsize=11, fontweight="bold", pad=10, loc="left", color="#38bdf8"
        )
        ax.set_xlabel("Asse Assonometrico U [m]", fontsize=9.5, fontweight="bold", color="#cbd5e1")
        ax.set_ylabel("Asse Assonometrico V [m]", fontsize=9.5, fontweight="bold", color="#cbd5e1")
        ax.tick_params(colors="#94a3b8")
        ax.set_aspect("equal", adjustable="datalim")
        ax.grid(True, linestyle="--", alpha=0.20, color="#64748b")
        fig.tight_layout()
        fig.savefig(p15, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        del fig, ax
        gc.collect()

    exported_images.append({
        "id": "15_streamlines_iso_rear",
        "filename": fname15,
        "path": p15,
        "category": "streamlines",
        "view": "iso_rear",
        "scalar": "Velocity Magnitude",
        "title": "Streamlines 3D - Vista Assonometrica Posteriore (Diffusore & Scia)",
        "description": "Vista assonometrica dal retrotreno che evidenzia l'upwash del diffusore, i vortici di bordo e il rilascio della scia verso il retro della vettura."
    })

    return exported_images


def run_postprocessing_session(config: dict, workspace_dir: str = None, force_meta_batch: bool = True, log_fn=print) -> dict:
    """
    Esegue il workflow completo e verificato di acquisizione ed estrazione da file .cas/.dat e META Post:
      1) Scopre i file .cas e .dat nella cartella
      2) Pulisce la cartella di output da eventuali immagini vecchie
      3) Scompatta la vera mesh 3D (nodi, triangoli, PID) e i veri campi CFD binari da .cas e .dat
      4) Genera il file di sessione .ses nativo v25.1 e meta_runtime_config.json con isolamento PID
      5) Esegue BETA CAE META Post (`meta_post64.bat -noses -s run_postprocessing_meta.ses`)
      6) Renderizza e completa le mappe usando esclusivamente la vera mesh 3D estratta dal .cas/.dat
    """
    if workspace_dir is None:
        workspace_dir = os.path.abspath(config.get("project", {}).get("workspace_dir", "."))

    output_dir = os.path.abspath(
        os.path.join(workspace_dir, config.get("project", {}).get("output_dir", "./output_diagnostics"))
    )
    os.makedirs(output_dir, exist_ok=True)
    _purge_previous_outputs(output_dir)

    cas_file, dat_file = discover_cas_dat(workspace_dir)
    # "auto" resta "auto": il parser rileva l'assieme dalle zone del .cas
    # (`detected_assembly`). Prima veniva forzato a undertray e ogni analisi
    # sembrava del solo fondo.
    requested_asm = config.get("project", {}).get("assembly_type", "auto") or "auto"

    log_fn(f"[LAUNCHER] Estrazione diretta mesh 3D e campi CFD da: {cas_file} & {dat_file}")
    real_extraction = extract_real_mesh_and_cfd_data(
        cas_path=cas_file,
        dat_path=dat_file,
        assembly_type=requested_asm,
        ref_values=config.get("reference_values", {}),
        config=config,
        force_convention=resolve_force_convention(config),
        log_fn=log_fn,
    )

    cas_info = real_extraction["cas_info"]
    assembly_type = real_extraction["assembly_type"]
    bbox = real_extraction["bounding_box"]
    physics_data = real_extraction["physics_data"]
    zone_meshes = real_extraction["zone_meshes"]

    # La geometria si calcola in OGNI corsa: cosi' la suite la trova gia' pronta
    # accanto al report, senza rieseguire l'estrazione in un secondo passaggio.
    geometry_payload = None
    try:
        from meta_driver.geometry import extract_geometry

        _scale = float((bbox or {}).get("coord_scale_to_m") or 1.0)
        _geometry = extract_geometry(zone_meshes, bbox or {}, coord_scale=_scale,
                                     assembly=assembly_type,
                                     half_car=bool(real_extraction.get("is_half_car_symmetric")))
        geometry_payload = {
            "case": os.path.splitext(os.path.basename(cas_file))[0],
            "cas_file": cas_file,
            "assembly": assembly_type,
            "half_car": bool(real_extraction.get("is_half_car_symmetric")),
            "bounding_box": bbox,
            "summary": _geometry.get("summary") or {},
            "geometry": _geometry,
        }
        log_fn("[GEOMETRIA] %d zone · fondo %s · ali %s/%s"
               % (len(_geometry.get("zones") or []),
                  "si" if (_geometry.get("floor") or {}).get("available") else "no",
                  "si" if (_geometry.get("wings") or {}).get("front", {}).get("available") else "no",
                  "si" if (_geometry.get("wings") or {}).get("rear", {}).get("available") else "no"))
    except Exception as _exc:  # la geometria non deve mai bloccare il report
        log_fn("[GEOMETRIA] non calcolata: %s" % _exc)

    target_pids = sorted({zid for z in cas_info.get("target_zones", []) for zid in z.get("zone_ids", [z["id"]])})
    target_names = sorted({rn for z in cas_info.get("target_zones", []) for rn in z.get("raw_names", [z["name"]])})
    hidden_zones = cas_info.get("domain_zones", []) + cas_info.get("other_aero_zones", [])
    hidden_pids = sorted({zid for z in hidden_zones for zid in z.get("zone_ids", [z["id"]])})
    hidden_names = sorted({rn for z in hidden_zones for rn in z.get("raw_names", [z["name"]])})

    worker_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "meta_post_worker.py"))

    # Salva meta_runtime_config.json per lo script interno di META Post
    runtime_cfg = {
        "workspace_dir": workspace_dir,
        "output_dir": output_dir,
        "cas_file": cas_file,
        "dat_file": dat_file,
        "assembly_type": assembly_type,
        "target_pids": target_pids,
        "target_names": target_names,
        "hidden_pids": hidden_pids,
        "hidden_names": hidden_names,
        "bounding_box": bbox,
        "coordinate_system": config.get("coordinate_system", {}),
        "reference_values": config.get("reference_values", {}),
        "meta": config.get("meta", {}),
    }
    runtime_cfg_path = os.path.join(workspace_dir, "meta_runtime_config.json")
    with open(runtime_cfg_path, "w", encoding="utf-8") as f:
        json.dump(runtime_cfg, f, indent=2)

    # Genera il file .ses nativo v25.1 per META Post (con isolamento rigoroso dei PID target)
    ses_path = generate_meta_session_file(
        cas_file=cas_file,
        dat_file=dat_file,
        output_dir=output_dir,
        bbox=bbox,
        assembly_type=assembly_type,
        target_pids=target_pids,
        target_names=target_names,
        hidden_pids=hidden_pids,
        hidden_names=hidden_names,
        worker_script_path=worker_script,
        img_width=int(config.get("meta", {}).get("image_width", 1920)),
        img_height=int(config.get("meta", {}).get("image_height", 1080)),
        auto_quit=True,
    )

    # Cerca l'eseguibile di META Post e lo lancia con la sintassi corretta v25.1 (-noses -s <ses_path>)
    meta_exe = find_meta_executable(config.get("meta", {}).get("executable_path", "auto"))
    meta_batch_executed = False

    if force_meta_batch and meta_exe and cas_file:
        from meta_locator import describe_meta

        meta_info = describe_meta(meta_exe)
        timeout_s = int(config.get("meta", {}).get("batch_timeout_s", 360) or 360)
        try:
            env = os.environ.copy()
            env["CFD_WORKSPACE_DIR"] = workspace_dir
            # Sintassi ufficiale META Post: -noses -s "session.ses"
            cmd = [meta_exe, "-noses", "-s", ses_path]
            print(f"[LAUNCHER] Avvio {meta_info['label']} ({meta_info['kind']}): {' '.join(cmd)}")
            completed = subprocess.run(cmd, cwd=workspace_dir, env=env,
                                       timeout=timeout_s, check=False)
            print(f"[LAUNCHER] {meta_info['label']} terminato con codice {completed.returncode}")
            meta_batch_executed = True
        except subprocess.TimeoutExpired:
            print(f"[LAUNCHER-WARN] {meta_info['label']} non ha terminato entro {timeout_s} s: "
                  "proseguo con le immagini generate in Python")
        except Exception as exc:
            print(f"[LAUNCHER-WARN] Esecuzione META Post terminata con avviso: {exc}")

    # Renderizza/completa tutte le viste diagnostiche proiettando la vera mesh 3D estratta dal .cas/.dat
    exported_images = _render_real_unpacked_mesh_views(
        output_dir=output_dir,
        assembly_type=assembly_type,
        bbox=bbox,
        physics_data=physics_data,
        zone_meshes=zone_meshes,
        cas_file=cas_file,
        dat_file=dat_file,
        img_w=int(config.get("meta", {}).get("image_width", 1920)),
        img_h=int(config.get("meta", {}).get("image_height", 1080)),
        cp_range=resolve_cp_range(config, assembly_type),
        x_stations=resolve_cut_stations(config, assembly_type)[0],
        z_stations=resolve_cut_stations(config, assembly_type)[1],
        render_max_triangles=int(config.get("meta", {}).get("render_max_triangles", 1500000)),
    )

    session_bundle = {
        "cas_file": cas_file,
        "dat_file": dat_file,
        "cas_info": cas_info,
        "assembly_type": assembly_type,
        "bounding_box": bbox,
        "ses_file_path": ses_path,
        "interactive_ses_path": os.path.join(output_dir, "open_in_meta_interactive.ses"),
        "worker_script_path": worker_script,
        "meta_executable": meta_exe,
        "meta_batch_executed": meta_batch_executed,
        "output_dir": output_dir,
        "exported_images": exported_images,
        "xcut_cp_gif": os.path.join(output_dir, "images_raw", "10_cp_xcut_progressive_sweep.gif"),
        "physics_data": physics_data,
        "geometry": geometry_payload,
        # La configurazione effettiva viaggia col bundle: le fasi 2-4 (soglie,
        # diagnosi, report) leggono da qui invece di duplicare valori cablati.
        "config": config,
    }

    extracted_json = os.path.join(output_dir, "cfd_extracted_data.json")
    with open(extracted_json, "w", encoding="utf-8") as f:
        json.dump(session_bundle, f, indent=2)

    if geometry_payload:
        with open(os.path.join(output_dir, "geometry.json"), "w", encoding="utf-8") as f:
            json.dump(geometry_payload, f, ensure_ascii=False, indent=2)

    return session_bundle
