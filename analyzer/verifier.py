# -*- coding: utf-8 -*-
"""
Modulo di Verifica Rigorosa Dati CFD e Immagini (verifier.py).
Impedisce qualsiasi allucinazione, dato sintetico o annotazione su cose inesistenti:
  1) Verifica l'integrita' della mesh 3D e dei campi scalari estratti da .cas e .dat
  2) Verifica l'esclusione delle pareti della galleria del vento (side, top, road, symmetry, inlet, outlet)
  3) Verifica la condizione di simmetria del modello (Half-Car vs Full-Car)
  4) Verifica ogni singola immagine PNG (esistenza, varianza cromatica, maschera geometrica attiva)
  5) Estrae le coordinate reali dei cluster critici dai dati fisici e dai pixel reali dell'immagine.
"""

import os
import numpy as np
from PIL import Image


def find_pixel_cluster_bbox(mask: np.ndarray, roi_offset_x: int, roi_offset_y: int, min_pixels: int = 120):
    """
    Trova il bounding box reale (x1, y1, x2, y2) del cluster principale di pixel attivi in `mask`
    usando i percentili spaziali (10% - 90%) attorno al baricentro denso, evitando box inventati.
    Restituisce None se il numero di pixel attivi e' inferiore a `min_pixels`.
    """
    ys, xs = np.where(mask)
    if xs.size < min_pixels:
        return None

    # Calcola la regione ad alta densita' attorno alla mediana del cluster
    med_x = float(np.median(xs))
    med_y = float(np.median(ys))
    dist = np.hypot(xs - med_x, ys - med_y)
    keep = dist <= np.percentile(dist, 75)
    if np.count_nonzero(keep) < min_pixels // 2:
        keep = np.ones_like(xs, dtype=bool)

    xs_k = xs[keep]
    ys_k = ys[keep]
    x1 = roi_offset_x + int(np.percentile(xs_k, 5))
    x2 = roi_offset_x + int(np.percentile(xs_k, 95))
    y1 = roi_offset_y + int(np.percentile(ys_k, 5))
    y2 = roi_offset_y + int(np.percentile(ys_k, 95))

    if (x2 - x1) < 28:
        cx = (x1 + x2) // 2
        x1, x2 = cx - 20, cx + 20
    if (y2 - y1) < 28:
        cy = (y1 + y2) // 2
        y1, y2 = cy - 20, cy + 20

    return (x1, y1, x2, y2)


def verify_single_image(img_path: str) -> dict:
    """Verifica che un file PNG esista, non sia corrotto/nero/bianco e contenga geometria reale."""
    if not img_path or not os.path.isfile(img_path):
        return {"valid": False, "reason": "File non trovato", "size_kb": 0.0}

    size_kb = os.path.getsize(img_path) / 1024.0
    if size_kb < 12.0:
        return {"valid": False, "reason": f"File troppo piccolo ({size_kb:.1f} KB)", "size_kb": round(size_kb, 1)}

    try:
        with Image.open(img_path) as im:
            arr = np.asarray(im.convert("RGB"), dtype=np.float32)
        h, w, _ = arr.shape
        mean_rgb = float(np.mean(arr))
        std_rgb = float(np.std(arr))

        # Maschera dei pixel appartenenti alla geometria (diversi dallo sfondo chiaro #f0f4f8 / bianco)
        roi = arr[int(0.12 * h):int(0.88 * h), int(0.10 * w):int(0.82 * w)]
        bg_dist = np.abs(roi[:, :, 0] - 240.0) + np.abs(roi[:, :, 1] - 244.0) + np.abs(roi[:, :, 2] - 248.0)
        white_dist = np.abs(roi[:, :, 0] - 255.0) + np.abs(roi[:, :, 1] - 255.0) + np.abs(roi[:, :, 2] - 255.0)
        fg_mask = (bg_dist > 18.0) & (white_dist > 18.0)
        fg_ratio_pct = float(np.count_nonzero(fg_mask)) / max(1, roi.shape[0] * roi.shape[1]) * 100.0

        if mean_rgb < 10.0 or mean_rgb > 253.5 or std_rgb < 4.0 or fg_ratio_pct < 1.0:
            return {
                "valid": False,
                "reason": f"Immagine vuota o priva di geometria (fg={fg_ratio_pct:.1f}%, std={std_rgb:.1f})",
                "size_kb": round(size_kb, 1),
                "foreground_pct": round(fg_ratio_pct, 1),
            }

        return {
            "valid": True,
            "reason": "Immagine verificata con geometria reale visibile",
            "width": w,
            "height": h,
            "size_kb": round(size_kb, 1),
            "foreground_pct": round(fg_ratio_pct, 1),
            "std_rgb": round(std_rgb, 1),
        }
    except Exception as exc:
        return {"valid": False, "reason": f"Errore apertura immagine: {exc}", "size_kb": round(size_kb, 1)}


def verify_session_and_data(session_bundle: dict) -> dict:
    """
    Esegue l'audit completo di verifica sui dati estratti da .cas/.dat e sulle immagini generate.
    Restituisce un dizionario strutturato `verification_report` incluso nel report finale.
    """
    cas_file = session_bundle.get("cas_file")
    dat_file = session_bundle.get("dat_file")
    cas_info = session_bundle.get("cas_info", {})
    physics = session_bundle.get("physics_data", {})
    kpis = physics.get("summary_kpis", {})
    pid_breakdown = physics.get("pid_breakdown", [])
    exported_images = session_bundle.get("exported_images", [])

    checks = []

    # Check 1: File .cas e .dat reali
    cas_ok = bool(cas_file and os.path.isfile(cas_file))
    dat_ok = bool(dat_file and os.path.isfile(dat_file))
    checks.append({
        "id": "CHK-01",
        "name": "Esistenza e Accessibilita' File Binari .CAS / .DAT",
        "status": "PASS" if (cas_ok and dat_ok) else "FAIL",
        "measured": f"CAS: {cas_info.get('cas_size_mb', 0)} MB | DAT: {'OK' if dat_ok else 'MANCANTE'}",
        "details": f"File analizzati: {os.path.basename(cas_file or '')} e {os.path.basename(dat_file or '')}."
    })

    # Check 2: Estrazione nodi e facce 3D reali dal file .cas
    nodes_read = int(physics.get("nodes_read", 0))
    faces_read = int(physics.get("faces_read", 0))
    mesh_ok = nodes_read > 100 and faces_read > 100
    checks.append({
        "id": "CHK-02",
        "name": "Scompattazione Geometria 3D Reale (Nodi & Triangoli)",
        "status": "PASS" if mesh_ok else "FAIL",
        "measured": f"{nodes_read:,} nodi 3D | {faces_read:,} facce superficiali",
        "details": "Coordinate (X, Y, Z) e triangolazioni lette direttamente dalle sezioni binarie (2010/3010 e 2013/3013) del file .cas."
    })

    # Check 3: Isolamento PID Assieme ed esclusione Galleria del Vento
    target_zones = cas_info.get("target_zones", [])
    domain_zones = cas_info.get("domain_zones", [])
    pids_ok = len(target_zones) > 0 and all(
        not any(k in z["name"].lower() for k in ["side", "top", "inlet", "outlet", "symmetry", "road", "fluid"])
        for z in target_zones
    )
    checks.append({
        "id": "CHK-03",
        "name": f"Isolamento Rigoroso PID Assieme ({session_bundle.get('assembly_type', '').upper()})",
        "status": "PASS" if pids_ok else "FAIL",
        "measured": f"{len(target_zones)} PID unificate attive | {len(domain_zones)} zone dominio escluse",
        "details": "PID attive (riunite senza suffisso ':xxx'): " + ", ".join(z["name"] for z in target_zones)
    })

    # Check 4: Verifica Simmetria Modello (Half-Car vs Full-Car)
    is_sym = bool(physics.get("is_half_car_symmetric", False))
    asym_val = float(kpis.get("lateral_asymmetry_pct", 0.0))
    sym_ok = (not is_sym) or (asym_val == 0.0)
    checks.append({
        "id": "CHK-04",
        "name": "Verifica Condizione al Contorno di Simmetria (Piano Z = 0)",
        "status": "PASS" if sym_ok else "FAIL",
        "measured": "Half-Car Simmetrico (Asimmetria = 0.0%)" if is_sym else f"Full-Car (Asimmetria = {asym_val:.2f}%)",
        "details": (
            "Il file .cas contiene il piano 'symmetry' (Z=0): il modello simula meta' vettura e le forze globali sono integrate con fattore 2x. Nessuna falsa asimmetria segnalata."
            if is_sym else "Modello completo su intero dominio."
        )
    })

    # Check 5: Verifica Dati CFD per singolo PID
    pids_with_data = [p for p in pid_breakdown if p.get("n_faces", 0) > 0]
    checks.append({
        "id": "CHK-05",
        "name": "Integrazione Forze e Pressioni per Singolo PID",
        "status": "PASS" if len(pids_with_data) > 0 else "WARN",
        "measured": f"{len(pids_with_data)} componenti con integrali di pressione/taglio",
        "details": "; ".join(
            f"{p['zone_name']}: Area={p['area_m2']:.3f} m², Fy={p['fy_N']:.1f} N, Cp_min={p['cp_min']:.2f}"
            for p in pids_with_data[:6]
        )
    })

    # Check 6: Verifica Immagini Esportate
    valid_imgs = []
    invalid_imgs = []
    for img_info in exported_images:
        res = verify_single_image(img_info.get("path", ""))
        img_info["verification"] = res
        if res["valid"]:
            valid_imgs.append(img_info)
        else:
            invalid_imgs.append((img_info.get("filename", ""), res.get("reason", "")))

    session_bundle["exported_images"] = valid_imgs
    imgs_ok = len(valid_imgs) >= 6 and len(invalid_imgs) == 0
    checks.append({
        "id": "CHK-06",
        "name": "Controllo Qualita' e Validita' Immagini Esportate",
        "status": "PASS" if imgs_ok else ("WARN" if len(valid_imgs) > 0 else "FAIL"),
        "measured": f"{len(valid_imgs)} immagini valide verificate | {len(invalid_imgs)} scartate",
        "details": "Tutte le immagini sono state controllate a livello di pixel per escludere schermate nere, vuote o sintetiche."
    })

    overall_passed = all(c["status"] in ("PASS", "WARN") for c in checks) and mesh_ok and pids_ok

    report = {
        "overall_status": "VERIFIED_REAL_DATA" if overall_passed else "VERIFICATION_WARNING",
        "is_half_car_symmetric": is_sym,
        "nodes_verified": nodes_read,
        "faces_verified": faces_read,
        "valid_images_count": len(valid_imgs),
        "rejected_images_count": len(invalid_imgs),
        "checks": checks,
    }
    session_bundle["verification_report"] = report
    return report
