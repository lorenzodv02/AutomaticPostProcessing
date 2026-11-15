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
FRONT_WING_PREFIXES = ("front_", "inverted", "endplate_flap", "flap_verticali", "swan")
REAR_WING_PREFIXES = ("rear_",)
WHEEL_PREFIXES = ("front_tyre", "rear_tyre", "tyrewall")
BODY_PREFIXES = ("chassis", "camicie", "lidar", "main_hoop", "pilota", "presa",
                 "internal_duct", "zed", "cover_zed", "duct_sidepod", "default-exterior",
                 "body", "cockpit")
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


def zone_family(name: str) -> str:
    """Famiglia di una zona: fondo, ala anteriore, ala posteriore, corpo, gomme."""
    clean = str(name or "").lower()
    # l'ordine conta: "front_tyre" e "front_suspension" non sono ala anteriore
    if clean.startswith(WHEEL_PREFIXES):
        return "gomme"
    if clean.startswith(("front_suspension", "rear_suspension", "swan_neck", "swan")):
        return "corpo"
    if clean.startswith(FLOOR_PREFIXES):
        return "fondo"
    if clean.startswith(REAR_WING_PREFIXES):
        return "ala posteriore"
    if clean.startswith(FRONT_WING_PREFIXES):
        return "ala anteriore"
    if clean.startswith(BODY_PREFIXES):
        return "corpo"
    return "altro"


def _zone_metrics(mesh: dict, coord_scale: float) -> dict:
    """Descrittori geometrici generici di una zona, in metri."""
    bbox = mesh.get("bbox") or {}
    areas = np.asarray(mesh.get("areas", []), dtype=float)
    area = float(np.sum(areas)) * coord_scale ** 2 if len(areas) else 0.0
    x_min = float(bbox.get("xmin", 0.0)) * coord_scale
    x_max = float(bbox.get("xmax", 0.0)) * coord_scale
    y_min = float(bbox.get("ymin", 0.0)) * coord_scale
    y_max = float(bbox.get("ymax", 0.0)) * coord_scale
    z_min = float(bbox.get("zmin", 0.0)) * coord_scale
    z_max = float(bbox.get("zmax", 0.0)) * coord_scale
    return {
        "zone": mesh.get("name", ""),
        "family": zone_family(mesh.get("name", "")),
        "area_m2": round(area, 4),
        "chord_m": round(x_max - x_min, 4),
        "span_m": round(z_max - z_min, 4),
        "height_m": round(y_max - y_min, 4),
        "x_range_m": [round(x_min, 4), round(x_max, 4)],
        "y_range_m": [round(y_min, 4), round(y_max, 4)],
        "z_range_m": [round(z_min, 4), round(z_max, 4)],
        "faces": int(mesh.get("n_faces", 0)),
    }


def zone_descriptors(zone_meshes: dict, coord_scale: float = 1.0) -> list:
    """Descrittori di TUTTE le zone aero: non solo il fondo."""
    rows = [_zone_metrics(mesh, coord_scale) for mesh in zone_meshes.values()]
    rows.sort(key=lambda row: (row["family"], -row["area_m2"]))
    return rows


def _zone_triangles(zone_meshes: dict, coord_scale: float, families) -> np.ndarray:
    wanted = (families,) if isinstance(families, str) else tuple(families)
    verts = []
    for mesh in zone_meshes.values():
        if zone_family(mesh.get("name", "")) not in wanted:
            continue
        p0 = np.asarray(mesh["p0"], dtype=float) * coord_scale
        p1 = np.asarray(mesh["p1"], dtype=float) * coord_scale
        p2 = np.asarray(mesh["p2"], dtype=float) * coord_scale
        p3 = np.asarray(mesh["p3"], dtype=float) * coord_scale
        verts.append(np.stack([p0, p1, p2], axis=1))
        if np.any(np.abs(p3 - p2).sum(axis=1) > 1e-12):
            quad = np.abs(p3 - p2).sum(axis=1) > 1e-12
            verts.append(np.stack([p0[quad], p2[quad], p3[quad]], axis=1))
    if not verts:
        return np.zeros((0, 3, 3))
    return np.vstack(verts)


def wing_summary(zone_meshes: dict, coord_scale: float = 1.0, family="ala anteriore",
                 stations: int = 24, half_car: bool = False) -> dict:
    """
    Riepilogo di un'ala dalla mesh: apertura, corda media, area, allungamento e
    distribuzione della corda lungo l'apertura. Funziona per ala anteriore e
    posteriore, quindi anche quando il caso e' un full car.
    """
    triangles = _zone_triangles(zone_meshes, coord_scale, family)
    if len(triangles) == 0:
        return {"available": False}
    area, normals, centroids = _triangles_geometry(triangles)
    x_vertices = triangles[:, :, 0]
    y_vertices = triangles[:, :, 1]
    z_vertices = triangles[:, :, 2]
    z = centroids[:, 2]
    z_min, z_max = float(np.min(z_vertices)), float(np.max(z_vertices))
    span = z_max - z_min
    if span < 0.02:
        return {"available": False, "reason": "apertura troppo piccola"}
    edges = np.linspace(z_min, z_max, stations + 1)
    idx = np.clip(np.digitize(z, edges) - 1, 0, stations - 1)
    chord_profile, station_z = [], []
    for station in range(stations):
        mask = idx == station
        station_z.append(0.5 * (edges[station] + edges[station + 1]))
        if not np.any(mask):
            chord_profile.append(0.0)
            continue
        # corda = estensione in x dei vertici nel tratto di apertura
        xs = x_vertices[mask]
        chord_profile.append(float(np.max(xs) - np.min(xs)))
    # i tratti di apertura senza triangoli si interpolano: una mesh reale e'
    # densa, ma le stazioni possono cadere nei vuoti fra le facce
    chord_array = np.asarray(chord_profile, dtype=float)
    valid = chord_array > 0
    if np.count_nonzero(valid) >= 2:
        indexes = np.where(valid)[0]
        chord_array = np.interp(np.arange(len(chord_array)), indexes, chord_array[indexes])
        chord_profile = [float(value) for value in chord_array]
    planform = float(np.sum(chord_array * (span / stations)))
    span_full = span * 2.0 if half_car else span
    planform_full = planform * 2.0 if half_car else planform
    aspect = (span_full ** 2 / planform_full) if planform_full > 1e-9 else None
    return {
        "available": True,
        "span_m": round(span_full, 4),
        "planform_m2": round(planform_full, 4),
        "surface_m2": round(float(np.sum(area)) * (2.0 if half_car else 1.0), 4),
        "chord_mean_m": round(planform_full / span_full, 4) if span_full > 1e-9 else None,
        "chord_max_m": round(max(chord_profile), 4),
        "aspect_ratio": round(aspect, 3) if aspect else None,
        "height_m": round(float(np.max(y_vertices) - np.min(y_vertices)), 4),
        "y_range_m": [round(float(np.min(y_vertices)), 4), round(float(np.max(y_vertices)), 4)],
        "z_profile_m": [round(float(v), 4) for v in station_z],
        "chord_profile_m": [round(float(v), 4) for v in chord_profile],
    }


def extract_geometry(zone_meshes: dict, bbox: dict, coord_scale: float = 1.0,
                     assembly: str = "full_car", half_car: bool = False) -> dict:
    """
    Geometria dell'assieme richiesto: fondo (profilo e metriche), ali
    (apertura, corda, area, allungamento) e descrittori di tutte le zone.

    Non e' piu' solo il fondo: funziona per undertray, front wing, rear wing e
    full car. Le sezioni non presenti nel caso restano vuote, senza errori.
    """
    zones = zone_descriptors(zone_meshes, coord_scale)
    parts = {}
    for row in zones:
        bucket = parts.setdefault(row["family"], {"area_m2": 0.0, "zones": 0})
        bucket["area_m2"] = round(bucket["area_m2"] + row["area_m2"], 4)
        bucket["zones"] += 1
    has_floor = any(str(mesh.get("name", "")).lower().startswith(FLOOR_PREFIXES)
                    for mesh in zone_meshes.values())
    floor = floor_profile(zone_meshes, bbox, coord_scale) if has_floor else {"available": False,
                                                                            "reason": "nessuna zona del fondo"}
    wings = {
        "front": wing_summary(zone_meshes, coord_scale, "ala anteriore", half_car=half_car),
        "rear": wing_summary(zone_meshes, coord_scale, "ala posteriore", half_car=half_car),
    }
    summary = {}
    if floor.get("available"):
        summary.update({key: floor.get(key) for key in
                        ("throat_x_m", "throat_h_m", "throat_pct", "diffuser_angle_deg",
                         "rise_kind", "rise_length_m", "rise_angle_deg", "expansion_ratio",
                         "camber_area_m2", "plan_area_m2", "floor_area_m2", "ground_y",
                         "triangles")})
    for key, wing in wings.items():
        if not wing.get("available"):
            continue
        summary["%s_span_m" % key] = wing["span_m"]
        summary["%s_chord_m" % key] = wing["chord_mean_m"]
        summary["%s_area_m2" % key] = wing["planform_m2"]
        summary["%s_aspect" % key] = wing["aspect_ratio"]
    for family, bucket in parts.items():
        summary["area_%s_m2" % family.replace(" ", "_")] = bucket["area_m2"]
    return {
        "available": bool(zones),
        "assembly": assembly,
        "half_car": bool(half_car),
        "zones": zones,
        "parts": parts,
        "floor": floor,
        "wings": wings,
        "summary": summary,
    }


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
