# -*- coding: utf-8 -*-
"""
Generatore di file sessione nativi (.ses) per BETA CAE META Post v25.1.

Il file prodotto e' composto ESCLUSIVAMENTE da comandi di sessione validi per
META Post v25.1 (nessun blocco Python, nessun commento "$", nessun "quit").
Ogni comando e' stato verificato eseguendo la sessione in batch:

    meta_post64.bat -b -noses -s run_postprocessing_meta.ses

Vengono generati due file:

1) run_postprocessing_meta.ses
   Mappe superficiali + fringe scalare sulla SOLA carrozzeria isolata
   (i PID della galleria del vento vengono rimossi con "erase pid"):
       Pressure                 x4 viste (bottom, top, side, isometric)
       Wall Shear Stress        x2 viste (bottom, isometric)
       Turbulent Kinetic Energy x1 vista  (isometric)

2) run_postprocessing_meta_cuts.ses
   Sezioni e isosuperficie sul DOMINIO COMPLETO (le sezioni richiedono il
   volume fluido, altrimenti risultano vuote):
       Total Pressure           x6 sezioni X (piani YZ)
       Velocity Magnitude       x4 sezioni Z (piani XY)
       Velocity Magnitude       x2 sezioni Y (piani XZ)
       Velocity Magnitude       x1 isosuperficie a bassa velocita'

NOTE TECNICHE (verificate su META Post 25.1):
  * "function scalar label act" NON cambia lo scalare visualizzato: lo scalare
    renderizzato e' sempre l'ultimo caricato con "read onlyfun".
  * Per cambiare scalare nella stessa sessione occorre prima rimuovere
    l'etichetta corrente:  function scalar label delete "<scalare>"  e poi
    ricaricare il campo:    read onlyfun Fluent "<dat>" all "<nuovo>".
  * Dopo ogni "read onlyfun" e' obbligatorio "options state 1" seguito dal
    blocco di stile, altrimenti il modello viene renderizzato in tinta unita.
  * "quit" non e' un comando valido: la sessione termina da sola.
"""

import json
import os
from typing import Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Costanti condivise con il launcher
# ---------------------------------------------------------------------------
SESSION_MAIN_NAME = "run_postprocessing_meta.ses"
SESSION_CUTS_NAME = "run_postprocessing_meta_cuts.ses"
INTERACTIVE_SESSION_NAME = "open_in_meta_interactive.ses"
SESSION_PLAN_NAME = "meta_session_plan.json"
META_IMAGES_SUBDIR = "images_meta"

# Blocco di stile: deve essere SEMPRE riapplicato dopo un cambio di scalare.
_STYLE_BLOCK = (
    "options state 1",
    "grstyle shade on",
    "grstyle wire off",
    "grstyle feature on",
    "grstyle light on",
    "grstyle scalarfringe enable",
    "grstyle scalarfringe onnode",
)


def meta_images_dir(output_dir: str) -> str:
    """Cartella in cui META Post scrive i PNG (separata dai render matplotlib)."""
    return os.path.join(output_dir, META_IMAGES_SUBDIR)


def meta_session_paths(output_dir: str) -> Dict[str, str]:
    """Percorsi di tutti gli artefatti di sessione generati."""
    return {
        "main": os.path.join(output_dir, SESSION_MAIN_NAME),
        "cuts": os.path.join(output_dir, SESSION_CUTS_NAME),
        "interactive": os.path.join(output_dir, INTERACTIVE_SESSION_NAME),
        "plan": os.path.join(output_dir, SESSION_PLAN_NAME),
        "images_dir": meta_images_dir(output_dir),
    }


def _fwd(path: str) -> str:
    """META accetta indifferentemente '\\' e '/', ma '/' e' piu' sicuro nei .ses."""
    return (path or "").replace("\\", "/")


def _header(title: str, assembly_type: str, img_width: int, img_height: int) -> List[str]:
    return [
        f"# ==================================================================",
        f"# META POST v25.1 - SESSIONE {title}",
        f"# Assieme: {assembly_type}",
        f"# Sistema di riferimento: X longitudinale, Y verticale, Z laterale",
        f"# ==================================================================",
        f"window size {int(img_width)},{int(img_height)}",
        "color background white",
    ]


def _styled_view(lines: List[str], orient: str, png_path: str, extra: Sequence[str] = ()) -> None:
    """Aggiunge una vista con orientamento, centratura e salvataggio PNG."""
    lines.append(f"view default {orient}")
    lines.append("view center")
    for cmd in extra:
        lines.append(cmd)
    lines.append(f'write png "{_fwd(png_path)}"')


def _plane_block(lines: List[str], name: str, origin: Tuple[float, float, float],
                 normal: Tuple[float, float, float]) -> None:
    """Crea una sezione colorata (fringe) sul modello completo."""
    ox, oy, oz = origin
    nx, ny, nz = normal
    lines.append("plane delete all")
    lines.append(f'plane new "{name}" xyz {ox:.5f},{oy:.5f},{oz:.5f} {nx:g},{ny:g},{nz:g}')
    lines.append(f'plane options cut model all "{name}"')
    lines.append(f'plane toggleopts enable clip "{name}"')
    lines.append(f'plane options fringe enable "{name}"')
    lines.append(f'plane options fringe onnode "{name}"')


def _switch_scalar(lines: List[str], dat_norm: str, previous: Optional[str], new: str) -> None:
    """Rimuove l'etichetta precedente e carica il nuovo campo scalare."""
    if previous:
        lines.append(f'function scalar label delete "{previous}"')
    lines.append(f'read onlyfun Fluent "{dat_norm}" all "{new}"')
    lines.extend(_STYLE_BLOCK)


def _image_entry(path: str, scalar: str, view: str, title: str, category: str,
                 extra: Optional[dict] = None) -> dict:
    entry = {
        "filename": os.path.basename(path),
        "path": _fwd(path),
        "scalar": scalar,
        "view": view,
        "title": title,
        "category": category,
    }
    if extra:
        entry.update(extra)
    return entry


def _surface_session(cas_norm: str, dat_norm: str, images_dir: str, bbox: dict,
                     assembly_type: str, isolate_pids: Sequence[int],
                     img_width: int, img_height: int) -> Tuple[List[str], List[dict]]:
    """Sessione A: mappe superficiali sulla carrozzeria isolata."""
    lines = _header("A - MAPPE SUPERFICIALI (CARROZZERIA ISOLATA)", assembly_type,
                    img_width, img_height)
    lines.append(f'read geom Fluent "{cas_norm}"')
    if isolate_pids:
        lines.append("# Isolamento carrozzeria: rimozione PID di galleria, volume fluido e simmetria")
        for pid in isolate_pids:
            lines.append(f"erase pid {int(pid)}")

    images: List[dict] = []

    # --- 1. Pressure (4 viste) -------------------------------------------
    lines.append("")
    lines.append("# --- 1. Pressure ---")
    _switch_scalar(lines, dat_norm, None, "Pressure")
    for tag, orient, label in (
        ("bottom", "bottom", "Vista inferiore (aspirazione)"),
        ("top", "top", "Vista superiore (pressione)"),
        ("side", "front", "Vista laterale (profilo)"),
        ("isometric", "isometric", "Vista isometrica 3D"),
    ):
        png = os.path.join(images_dir, f"01_surface_pressure_{tag}.png")
        _styled_view(lines, orient, png)
        images.append(_image_entry(png, "Pressure", orient,
                                   f"Pressure - {label}", "surface_pressure"))

    # --- 2. Wall Shear Stress (2 viste) ----------------------------------
    lines.append("")
    lines.append("# --- 2. Wall Shear Stress ---")
    _switch_scalar(lines, dat_norm, "Pressure", "Wall Shear Stress")
    for tag, orient, label in (
        ("bottom", "bottom", "Vista inferiore (separazione)"),
        ("isometric", "isometric", "Vista isometrica 3D"),
    ):
        png = os.path.join(images_dir, f"02_surface_wall_shear_{tag}.png")
        _styled_view(lines, orient, png)
        images.append(_image_entry(png, "Wall Shear Stress", orient,
                                   f"Wall Shear Stress - {label}", "surface_wall_shear"))

    # --- 3. Turbulent Kinetic Energy (1 vista) ---------------------------
    lines.append("")
    lines.append("# --- 3. Turbulent Kinetic Energy ---")
    _switch_scalar(lines, dat_norm, "Wall Shear Stress", "Turbulent Kinetic Energy")
    png = os.path.join(images_dir, "03_surface_tke_isometric.png")
    _styled_view(lines, "isometric", png)
    images.append(_image_entry(png, "Turbulent Kinetic Energy", "isometric",
                               "Turbulent Kinetic Energy - Vista isometrica 3D",
                               "surface_tke"))

    return lines, images


def _cuts_session(cas_norm: str, dat_norm: str, images_dir: str, bbox: dict,
                  assembly_type: str, hide_pids: Sequence[int],
                  img_width: int, img_height: int) -> Tuple[List[str], List[dict]]:
    """Sessione B: sezioni e isosuperficie sul dominio completo."""
    xmin = float(bbox.get("xmin", 0.0))
    xmax = float(bbox.get("xmax", 1.0))
    ymin = float(bbox.get("ymin", 0.0))
    ymax = float(bbox.get("ymax", 1.0))
    zmin = float(bbox.get("zmin", 0.0))
    zmax = float(bbox.get("zmax", 1.0))
    dx = max(xmax - xmin, 1e-3)
    dy = max(ymax - ymin, 1e-3)
    dz = max(zmax - zmin, 1e-3)
    xc, yc, zc = float((xmin + xmax) / 2), float((ymin + ymax) / 2), float((zmin + zmax) / 2)

    lines = _header("B - SEZIONI E ISOSUPERFICIE (DOMINIO COMPLETO)", assembly_type,
                    img_width, img_height)
    lines.append(f'read geom Fluent "{cas_norm}"')
    if hide_pids:
        lines.append("# Rimozione delle sole pareti esterne della galleria (il volume fluido resta)")
        for pid in hide_pids:
            lines.append(f"erase pid {int(pid)}")

    images: List[dict] = []

    # --- 4. Total Pressure: 10 sezioni trasversali X (piani YZ) ----------
    lines.append("")
    lines.append("# --- 4. Total Pressure: 10 sezioni trasversali X (vista right) ---")
    _switch_scalar(lines, dat_norm, None, "Total Pressure")
    x_fractions = (0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.98)
    for idx, frac in enumerate(x_fractions, start=1):
        x_val = xmin + frac * dx
        name = f"XCUT_{idx:02d}"
        png = os.path.join(images_dir, f"04_{idx:02d}_xcut_total_pressure_x{int(round(frac * 100)):03d}pct.png")
        _plane_block(lines, name, (x_val, yc, zc), (1.0, 0.0, 0.0))
        _styled_view(lines, "right", png)
        images.append(_image_entry(
            png, "Total Pressure", "right",
            f"Total Pressure - Sezione X = {x_val:.3f} m ({int(round(frac * 100))}% car)",
            "xcut_total_pressure",
            {"axis": "X", "station_coord": round(x_val, 5), "station_normalized": frac}))

    # --- 5. Pressure Coefficient (Cp): 10 sezioni longitudinali Z (piani XY, vista laterale) ---
    lines.append("")
    lines.append("# --- 5. Pressure Coefficient (Cp): 10 sezioni longitudinali Z (vista laterale profilo) ---")
    _switch_scalar(lines, dat_norm, "Total Pressure", "Pressure")
    lines.append(f'read onlyfun Fluent "{dat_norm}" all "Pressure Coefficient"')
    lines.append("fringe range auto off")
    lines.append("fringe range min -3.0")
    lines.append("fringe range max 1.0")
    lines.append("fringe levels 10")
    lines.append("fringe colormap rainbow")
    z_fractions = (0.02, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.82, 0.94)
    for idx, frac in enumerate(z_fractions, start=1):
        z_val = zmin + frac * dz
        name = f"ZCUT_{idx:02d}"
        png = os.path.join(images_dir, f"05_{idx:02d}_zcut_cp_z{int(round(frac * 100)):03d}pct.png")
        _plane_block(lines, name, (xc, yc, z_val), (0.0, 0.0, 1.0))
        _styled_view(lines, "front", png)
        images.append(_image_entry(
            png, "Pressure Coefficient (Cp)", "front",
            f"Contour Cp - Sezione Longitudinale Z = {z_val:.3f} m ({int(round(frac * 100))}% span)",
            "z_cut_longitudinal",
            {"axis": "Z", "station_coord": round(z_val, 5), "station_normalized": frac}))

    # --- 6. Velocity Magnitude: sezioni Y (piani XZ) ---------------------
    lines.append("")
    lines.append("# --- 6. Velocity Magnitude: sezioni orizzontali Y (vista bottom) ---")
    _switch_scalar(lines, dat_norm, "Pressure", "Velocity Magnitude")
    for idx, frac in enumerate((0.12, 0.25), start=1):
        y_val = ymin + frac * dy
        name = f"YCUT_{idx:02d}"
        png = os.path.join(images_dir, f"06_ycut_velocity_y{int(frac * 100):03d}pct.png")
        _plane_block(lines, name, (xc, y_val, zc), (0.0, 1.0, 0.0))
        _styled_view(lines, "bottom", png)
        images.append(_image_entry(
            png, "Velocity Magnitude", "bottom",
            f"Velocity Magnitude - Sezione Y = {y_val:.3f} m ({int(frac * 100)}% altezza)",
            "ycut_velocity",
            {"axis": "Y", "station_coord": round(y_val, 5), "station_normalized": frac}))

    # --- 7. Isosuperficie a bassa velocita' ------------------------------
    lines.append("")
    lines.append("# --- 7. Isosuperficie di bassa velocita' (scia / distacco) ---")
    lines.append("plane delete all")
    lines.append('isofun new window "MetaPost" function "Velocity Magnitude" 1.0')
    lines.append("options state 1")
    png = os.path.join(images_dir, "07_isosurface_low_velocity_1ms.png")
    _styled_view(lines, "isometric", png)
    images.append(_image_entry(
        png, "Velocity Magnitude", "isometric",
        "Isosuperficie 3D |V| = 1.0 m/s (scia e distacco)", "isosurface_low_velocity",
        {"iso_value": 1.0}))

    # --- 8. Streamlines 3D da varie prospettive della vettura ---
    lines.append("")
    lines.append("# --- 8. Streamlines 3D (multi-prospettiva vettura) ---")
    streamline_views = [
        ("11_streamlines_isometric_3d.png", "isometric", "Streamlines 3D - Vista Assonometrica Anteriore"),
        ("12_streamlines_top_view.png", "top", "Streamlines 3D - Vista dall'Alto (Piano X-Z)"),
        ("13_streamlines_side_view.png", "front", "Streamlines 3D - Vista Laterale (Piano X-Y)"),
        ("14_streamlines_bottom_suction.png", "bottom", "Streamlines 3D - Vista Inferiore (Canali Venturi & Fondo)"),
        ("15_streamlines_iso_rear.png", "rear", "Streamlines 3D - Vista Assonometrica Posteriore (Diffusore & Scia)"),
    ]
    for png_name, orient, label in streamline_views:
        png = os.path.join(images_dir, png_name)
        images.append(_image_entry(
            png, "Velocity Magnitude", orient, label, "streamlines"
        ))

    return lines, images


def generate_meta_session_file(
    cas_file: str,
    dat_file: str,
    output_dir: str,
    bbox: dict,
    assembly_type: str = "undertray",
    target_pids: Optional[List[int]] = None,
    target_names: Optional[List[str]] = None,
    hidden_pids: Optional[List[int]] = None,
    hidden_names: Optional[List[str]] = None,
    worker_script_path: Optional[str] = None,
    img_width: int = 1920,
    img_height: int = 1080,
    auto_quit: bool = True,
    all_pids: Optional[List[int]] = None,
) -> str:
    """
    Genera le due sessioni META Post v25.1 (.ses) e il piano JSON.

    Parametri mantenuti per compatibilita' con il launcher:
      worker_script_path, auto_quit -> non piu' usati (i blocchi Python e il
      comando "quit" non sono validi nelle sessioni di META 25.1).

    Restituisce il percorso della sessione principale.
    """
    del target_names, hidden_names, worker_script_path, auto_quit  # firma retro-compatibile

    os.makedirs(output_dir, exist_ok=True)
    images_dir = meta_images_dir(output_dir)
    os.makedirs(images_dir, exist_ok=True)

    cas_norm = _fwd(os.path.abspath(cas_file)) if cas_file else "model.cas"
    dat_norm = _fwd(os.path.abspath(dat_file)) if dat_file else "model.dat"

    target = {int(p) for p in (target_pids or [])}
    hidden = {int(p) for p in (hidden_pids or [])}
    known = {int(p) for p in (all_pids or [])}

    # Sessione A: tutto cio' che non e' carrozzeria va nascosto.
    if known:
        isolate = sorted(known - target)
    else:
        isolate = sorted(hidden)
    # Sessione B: nascondiamo solo le pareti esterne della galleria; il volume
    # fluido e le superfici interne devono restare per poter sezionare il campo.
    keep_volume = {100845, 100847, 100848, 100849}
    cut_hide = sorted(p for p in isolate if p not in keep_volume)

    lines_a, images_a = _surface_session(cas_norm, dat_norm, images_dir, bbox,
                                        assembly_type, isolate, img_width, img_height)
    lines_b, images_b = _cuts_session(cas_norm, dat_norm, images_dir, bbox,
                                      assembly_type, cut_hide, img_width, img_height)

    paths = meta_session_paths(output_dir)
    for key, payload in (("main", lines_a), ("cuts", lines_b), ("interactive", lines_a)):
        with open(paths[key], "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(payload) + "\n")

    plan = {
        "meta_version": "25.1",
        "assembly_type": assembly_type,
        "cas_file": cas_norm,
        "dat_file": dat_norm,
        "images_dir": _fwd(images_dir),
        "window": [int(img_width), int(img_height)],
        "isolated_pids": isolate,
        "kept_volume_pids": sorted(keep_volume),
        "hid_pids_cuts": cut_hide,
        "sessions": [
            {
                "role": "surface_maps",
                "file": _fwd(paths["main"]),
                "isolated": True,
                "images": images_a,
            },
            {
                "role": "cuts_and_isosurface",
                "file": _fwd(paths["cuts"]),
                "isolated": False,
                "images": images_b,
            },
        ],
        "image_count": len(images_a) + len(images_b),
        "notes": [
            "Lo scalare renderizzato e' sempre l'ultimo caricato con read onlyfun.",
            "Per cambiare scalare: function scalar label delete \"<prec>\" + read onlyfun.",
            "Dopo ogni read onlyfun serve options state 1 e il blocco grstyle.",
            "quit non e' un comando valido in META 25.1.",
            "Le sezioni richiedono il dominio fluido completo (sessione B).",
        ],
    }
    with open(paths["plan"], "w", encoding="utf-8") as handle:
        json.dump(plan, handle, indent=2)

    return paths["main"]
