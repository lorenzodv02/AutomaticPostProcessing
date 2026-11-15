# -*- coding: utf-8 -*-
"""
Geometria del fondo estratta direttamente dalla mesh del .cas.

Non usa il .dat: legge i triangoli delle zone del fondo (flat_floor, diffusore,
venturi) e ne ricava:

  * profilo di altezza dal suolo lungo X (media pesata e minimo per stazione);
  * larghezza e area della sezione trasversale stimata A(x) ~ larghezza x altezza;
  * altezza della gola e sua posizione, angolo del diffusore, rapporto di espansione;
  * area della superficie del fondo e area in pianta.

Tutte le grandezze sono in metri. Il piano di riferimento e' il minimo della
bounding box (la pista, se il caso include il dominio esterno) oppure il minimo
della superficie del fondo.
"""
from __future__ import annotations

import math

import numpy as np

FLOOR_PREFIXES = ("flat_floor", "diffusore", "venturi")
HORIZONTAL_NY = 0.55      # solo superfici quasi orizzontali
DEFAULT_STATIONS = 48


def _trapz(values, coords):
    """Integrale trapezoidale senza np.trapz (rimosso in NumPy 2)."""
    values = np.asarray(values, dtype=float)
    coords = np.asarray(coords, dtype=float)
    if len(values) < 2:
        return 0.0
    return float(np.sum(0.5 * (values[1:] + values[:-1]) * np.diff(coords)))


def is_floor_zone(name: str) -> bool:
    return str(name or "").lower().startswith(FLOOR_PREFIXES)


def _floor_triangles(zone_meshes: dict, coord_scale: float):
    """
    Triangoli delle zone del fondo: vertici (n,3,3) in metri e nome zona per
    triangolo. Le facce quad sono divise in due triangoli.
    """
    verts, names = [], []
    for mesh in zone_meshes.values():
        if not is_floor_zone(mesh.get("name", "")):
            continue
        p0 = np.asarray(mesh["p0"], dtype=float) * coord_scale
        p1 = np.asarray(mesh["p1"], dtype=float) * coord_scale
        p2 = np.asarray(mesh["p2"], dtype=float) * coord_scale
        p3 = np.asarray(mesh["p3"], dtype=float) * coord_scale
        quad = np.linalg.norm(p3 - p2, axis=1) > 1e-12
        tri_a = np.stack([p0, p1, p2], axis=1)
        verts.append(tri_a)
        names.extend([mesh.get("name", "")] * len(tri_a))
        if np.any(quad):
            tri_b = np.stack([p0[quad], p2[quad], p3[quad]], axis=1)
            verts.append(tri_b)
            names.extend([mesh.get("name", "")] * len(tri_b))
    if not verts:
        return np.zeros((0, 3, 3)), []
    return np.vstack(verts), names


def _triangles_geometry(triangles: np.ndarray):
    """Area, normale unitaria e centroide di ogni triangolo."""
    if len(triangles) == 0:
        return (np.zeros(0), np.zeros((0, 3)), np.zeros((0, 3)))
    e1 = triangles[:, 1] - triangles[:, 0]
    e2 = triangles[:, 2] - triangles[:, 0]
    cross = np.cross(e1, e2)
    area = 0.5 * np.linalg.norm(cross, axis=1)
    normals = cross / np.maximum(np.linalg.norm(cross, axis=1)[:, None], 1e-15)
    centroids = triangles.mean(axis=1)
    return area, normals, centroids


def find_ramp(x, h, min_slope=0.03, min_rise=0.010):
    """
    Trova il tratto in salita piu' ripido del fondo (diffusore o cascata).

    Distingue un vero diffusore (salita dolce e lunga) da un gradino/cascata:
    nei casi reali il "tratto in salita" puo' essere una scalinata di 5 cm.
    """
    values = np.asarray(h, dtype=float)
    coords = np.asarray(x, dtype=float)
    if len(values) < 3:
        return {"x_start_m": None, "x_end_m": None, "angle_deg": None,
                "rise_m": None, "h_start": None, "h_end": None, "kind": None,
                "length_m": None}
    slopes = np.diff(values) / np.maximum(np.diff(coords), 1e-9)
    positive = slopes > float(min_slope)
    best = None
    index = 0
    while index < len(positive):
        if not positive[index]:
            index += 1
            continue
        end = index
        while end + 1 < len(positive) and positive[end + 1]:
            end += 1
        rise = float(values[end + 1] - values[index])
        length = float(coords[end + 1] - coords[index])
        if rise >= float(min_rise) and (best is None or rise > best[0]):
            best = (rise, length, index, end + 1)
        index = end + 1
    if best is None:
        return {"x_start_m": None, "x_end_m": None, "angle_deg": None,
                "rise_m": None, "h_start": None, "h_end": None, "kind": None,
                "length_m": None}
    rise, length, first, last = best
    angle = math.degrees(math.atan(rise / length)) if length > 1e-9 else float("nan")
    return {
        "x_start_m": round(float(coords[first]), 4),
        "x_end_m": round(float(coords[last]), 4),
        "length_m": round(length, 4),
        "angle_deg": round(float(angle), 2) if math.isfinite(angle) else None,
        "rise_m": round(rise, 4),
        "h_start": round(float(values[first]), 4),
        "h_end": round(float(values[last]), 4),
        # un vero diffusore e' lungo e non troppo ripido; oltre 35 deg e' un gradino
        "kind": "diffusore" if (length >= 0.15 and angle <= 35.0) else "gradino/cascata",
    }


def zone_ladder(zone_meshes, coord_scale=1.0):
    """Elenco delle zone del fondo con la loro estensione in x, altezza e area."""
    ladder = []
    for mesh in zone_meshes.values():
        if not is_floor_zone(mesh.get("name", "")):
            continue
        bbox = mesh.get("bbox") or {}
        ladder.append({
            "zone": mesh.get("name", ""),
            "x_min_m": round(float(bbox.get("xmin", 0.0)) * coord_scale, 4),
            "x_max_m": round(float(bbox.get("xmax", 0.0)) * coord_scale, 4),
            "y_min_m": round(float(bbox.get("ymin", 0.0)) * coord_scale, 4),
            "y_max_m": round(float(bbox.get("ymax", 0.0)) * coord_scale, 4),
            "z_width_m": round((float(bbox.get("zmax", 0.0)) - float(bbox.get("zmin", 0.0))) * coord_scale, 4),
            "area_m2": round(float(np.sum(np.asarray(mesh.get("areas", []), dtype=float)))
                             * coord_scale ** 2, 4) if mesh.get("areas") is not None else 0.0,
            "faces": int(mesh.get("n_faces", 0)),
        })
    ladder.sort(key=lambda item: item["x_min_m"])
    return ladder


def floor_profile(zone_meshes: dict, bbox: dict, coord_scale: float = 1.0,
                  stations: int = DEFAULT_STATIONS) -> dict:
    """Profilo altimetrico del fondo e metriche derivate."""
    triangles, _names = _floor_triangles(zone_meshes, coord_scale)
    area, normals, centroids = _triangles_geometry(triangles)
    if len(triangles) == 0:
        return {"available": False, "reason": "nessuna zona del fondo nel mesh"}

    horizontal = np.abs(normals[:, 1]) >= HORIZONTAL_NY
    if np.count_nonzero(horizontal) < 20:
        # casi senza fondo riconoscibile: si usano tutte le facce del fondo
        horizontal = np.ones(len(triangles), dtype=bool)
    x = centroids[horizontal, 0]
    y = centroids[horizontal, 1]
    z = centroids[horizontal, 2]
    a = area[horizontal]

    x_min, x_max = float(np.min(x)), float(np.max(x))
    if x_max - x_min < 0.05:
        return {"available": False, "reason": "estensione longitudinale del fondo troppo piccola"}

    edges = np.linspace(x_min, x_max, stations + 1)
    idx = np.clip(np.digitize(x, edges) - 1, 0, stations - 1)
    xs, h_mean, h_min, widths, sections = [], [], [], [], []
    for station in range(stations):
        mask = idx == station
        if not np.any(mask):
            xs.append(0.5 * (edges[station] + edges[station + 1]))
            h_mean.append(np.nan)
            h_min.append(np.nan)
            widths.append(np.nan)
            sections.append(np.nan)
            continue
        weights = np.maximum(a[mask], 1e-12)
        xs.append(0.5 * (edges[station] + edges[station + 1]))
        h_mean.append(float(np.average(y[mask], weights=weights)))
        h_min.append(float(np.min(y[mask])))
        widths.append(float(np.max(z[mask]) - np.min(z[mask])))
        sections.append(float(np.sum(weights)))

    h_mean = np.array(h_mean, dtype=float)
    h_min = np.array(h_min, dtype=float)
    widths = np.array(widths, dtype=float)
    # riempie i buchi per interpolazione lineare
    for array in (h_mean, h_min, widths):
        valid = np.isfinite(array)
        if np.count_nonzero(valid) >= 2:
            array[~valid] = np.interp(np.array(xs)[~valid], np.array(xs)[valid], array[valid])

    ground = float(min(bbox.get("ymin", np.nanmin(h_min)), 0.0)) if "ymin" in bbox else float(np.min(h_min))
    ride_mean = h_mean - ground
    ride_min = h_min - ground
    width = np.clip(widths, 1e-6, None)
    # sezione trasversale stimata: larghezza x altezza (rettangolo equivalente)
    section = width * ride_mean

    xs_arr = np.array(xs, dtype=float)
    span = xs_arr[-1] - xs_arr[0]
    inner = (xs_arr >= xs_arr[0] + 0.1 * span) & (xs_arr <= xs_arr[-1] - 0.1 * span)
    if not np.any(inner):
        inner = np.ones(len(xs_arr), dtype=bool)
    throat_index = int(np.where(inner)[0][np.argmin(ride_mean[inner])])
    throat_x = float(xs_arr[throat_index])
    throat_h = float(ride_min[throat_index])
    ramp = find_ramp(xs_arr, ride_min)
    angle = ramp["angle_deg"]
    rear_h = ramp["h_end"]
    throat_h = float(ride_min[throat_index])
    expansion = (rear_h / throat_h) if throat_h > 1e-6 else float("nan")
    camber_area = _trapz(np.maximum(ride_mean - ride_min, 0.0), xs_arr)
    plan_area = _trapz(width, xs_arr)

    zones = zone_ladder(zone_meshes, coord_scale)
    return {
        "available": True,
        "ramp": ramp,
        "zones": zones,
        "stations": stations,
        "x_m": [round(float(v), 4) for v in xs_arr],
        "h_mean_m": [round(float(v), 4) for v in ride_mean],
        "h_min_m": [round(float(v), 4) for v in ride_min],
        "width_m": [round(float(v), 4) for v in width],
        "section_m2": [round(float(v), 5) for v in section],
        "ground_y": round(ground, 5),
        "throat_x_m": round(throat_x, 4),
        "throat_h_m": round(throat_h, 4),
        "throat_pct": round((throat_x - xs_arr[0]) / span * 100.0, 1),
        "diffuser_angle_deg": round(angle, 2) if isinstance(angle, (int, float)) else None,
        "rise_kind": (ramp or {}).get("kind"),
        "rise_length_m": (ramp or {}).get("length_m"),
        "rise_angle_deg": (ramp or {}).get("angle_deg"),
        "expansion_ratio": round(expansion, 3) if math.isfinite(expansion) else None,
        "camber_area_m2": round(camber_area, 5),
        "plan_area_m2": round(plan_area, 4),
        "floor_area_m2": round(float(np.sum(a)), 4),
        "x_range_m": [round(x_min, 4), round(x_max, 4)],
        "triangles": int(len(triangles)),
        "used_horizontal": int(np.count_nonzero(horizontal)),
    }


def summarize(profile: dict) -> dict:
    """Solo le metriche scalari, per le tabelle."""
    if not profile or not profile.get("available"):
        return {}
    keys = ("throat_x_m", "throat_h_m", "throat_pct", "diffuser_angle_deg",
            "rise_kind", "rise_length_m", "rise_angle_deg", "expansion_ratio",
            "camber_area_m2", "plan_area_m2", "floor_area_m2", "ground_y", "triangles")
    return {key: profile.get(key) for key in keys}
