# -*- coding: utf-8 -*-
"""
Motore di Regole Aerodinamiche Basato sui Dati Reali per Singolo PID (assembly_rules.py).
Deriva tutte le problematiche del design esclusivamente dalle metriche reali misurate
sui PID del file .cas/.dat (es. flat_floor, diffusore_int, venturi, venturi_first,
venturi_second, venturi_endplate), rispettando la simmetria Half-Car (Z = 0).
"""


def _format_pid_bbox(p: dict, fallback_bbox: dict) -> str:
    b = p.get("bbox") if p else None
    if not b:
        b = fallback_bbox
    return (
        f"X = [{b.get('xmin', 0.0):.3f}, {b.get('xmax', 1.0):.3f}] m | "
        f"Y = [{b.get('ymin', 0.0):.3f}, {b.get('ymax', 0.3):.3f}] m | "
        f"Z = [{b.get('zmin', -0.6):.3f}, {b.get('zmax', 0.0):.3f}] m"
    )


def evaluate_design_issues(session_bundle: dict, cv_results: dict) -> list:
    """
    Analizza i dati reali per singolo PID (`pid_breakdown`), i KPI globali e la condizione di
    simmetria per generare la lista verificata delle problematiche del design.
    """
    assembly_type = session_bundle.get("assembly_type", "undertray")
    bbox = session_bundle.get("bounding_box", {})
    pdata = session_bundle.get("physics_data", {})
    kpis = pdata.get("summary_kpis", {})
    pid_breakdown = pdata.get("pid_breakdown", [])
    is_sym = bool(pdata.get("is_half_car_symmetric", False))

    stall_global_pct = float(kpis.get("stalled_area_percentage", 0.0))
    peak_cp_global = float(kpis.get("peak_suction_cp", -2.5))
    df_total = float(kpis.get("downforce_total_N", 0.0))
    drag_total = float(kpis.get("drag_total_N", 0.0))

    # Ordina i PID reali per individuare i componenti effettivamente critici
    pids_by_stall = sorted(pid_breakdown, key=lambda p: -float(p.get("stalled_area_pct", 0.0)))
    pids_by_suction = sorted(pid_breakdown, key=lambda p: float(p.get("cp_min", 0.0)))
    pids_by_drag = sorted(pid_breakdown, key=lambda p: -float(p.get("fx_N", 0.0)))

    worst_stall_pid = pids_by_stall[0] if pids_by_stall else None
    second_stall_pid = pids_by_stall[1] if len(pids_by_stall) > 1 else worst_stall_pid
    best_suction_pid = pids_by_suction[0] if pids_by_suction else None
    highest_drag_pid = pids_by_drag[0] if pids_by_drag else None

    issues = []

    # 1. Diagnostica sul PID con maggior separazione / stallo (Tau_w,x <= 0)
    if worst_stall_pid:
        p_name = worst_stall_pid["zone_name"]
        p_id = worst_stall_pid["zone_id"]
        p_stall = float(worst_stall_pid["stalled_area_pct"])
        p_area = float(worst_stall_pid["area_m2"])
        p_fy = float(worst_stall_pid["fy_N"])
        p_fx = float(worst_stall_pid["fx_N"])
        p_cp_mean = float(worst_stall_pid["cp_mean"])
        sev = "CRITICAL" if p_stall >= 8.0 else ("WARNING" if p_stall >= 2.0 else "INFO")

        issues.append({
            "id": f"{assembly_type[:2].upper()}-{sev[:4]}-01",
            "severity": sev,
            "title": f"Separazione dello Strato Limite Misurata sul Componente '{p_name}' (PID {p_id})",
            "location_xyz": _format_pid_bbox(worst_stall_pid, bbox),
            "visual_evidence": (
                f"Mappa 05 (X-Wall Shear Stress su {p_name}), Mappa 00 (Topologia PID ID:{p_id}) "
                f"e Grafico 00 (Riparto Forze & Stallo per PID)"
            ),
            "root_cause": (
                f"Dall'integrazione diretta delle {worst_stall_pid['n_faces']:,} facce superficiali del PID '{p_name}' "
                f"(ID {p_id}, area = {p_area:.4f} m²), il {p_stall:.2f}% della superficie del componente presenta sforzo "
                f"di taglio longitudinale Tau_w,x <= 0 Pa (media globale assieme = {stall_global_pct:.2f}%). "
                f"Il recupero di pressione con Cp medio pari a {p_cp_mean:.2f} sul componente rallenta lo strato limite "
                f"fino all'inversione locale del flusso."
            ),
            "quantified_impact": (
                f"Sul singolo componente '{p_name}' (Half-Car): Fy = {p_fy:.1f} N (deportanza = {-p_fy:.1f} N), "
                f"Fx (drag) = {p_fx:.1f} N, con {p_stall:.2f}% di superficie in regime di distacco."
            ),
            "cad_redesign_actions": [
                f"Addolcire la curvatura longitudinale di ingresso su '{p_name}' (PID {p_id}) con continuità G2 per ridurre il gradiente avverso dCp/dX.",
                f"Ridurre l'angolo di divergenza locale su '{p_name}' di 1.5° - 2.5° nelle zone in cui Tau_w,x scende sotto zero.",
                "Iniettare quantità di moto nello strato limite a monte del componente tramite slot di soffiaggio o riposizionamento delle derive (strakes) dei canali Venturi."
            ]
        })

    # 2. Diagnostica sul Picco di Depressione e Gradiente Avverso (PID di massima aspirazione)
    if best_suction_pid:
        s_name = best_suction_pid["zone_name"]
        s_id = best_suction_pid["zone_id"]
        s_cp_min = float(best_suction_pid["cp_min"])
        s_cp_mean = float(best_suction_pid["cp_mean"])
        s_fy = float(best_suction_pid["fy_N"])
        s_area = float(best_suction_pid["area_m2"])

        issues.append({
            "id": f"{assembly_type[:2].upper()}-WARN-02",
            "severity": "WARNING",
            "title": f"Concentrazione del Picco di Depressione su '{s_name}' (PID {s_id}, Cp_min = {s_cp_min:.2f})",
            "location_xyz": _format_pid_bbox(best_suction_pid, bbox),
            "visual_evidence": (
                f"Mappa 01 (Cp Lato Aspirazione Bottom -Y), Mappa 04 (Vista 3D Isometrica) e Grafico 01 (Cp Longitudinale)"
            ),
            "root_cause": (
                f"Il componente '{s_name}' (PID {s_id}, area = {s_area:.4f} m²) raggiunge il picco assoluto di depressione "
                f"dell'assieme con Cp_min = {s_cp_min:.2f} (Cp medio = {s_cp_mean:.2f}), generando {-s_fy:.1f} N di deportanza "
                f"(su singolo lato Half-Car). Il forte salto tra Cp_min ({s_cp_min:.2f}) e Cp_mean ({s_cp_mean:.2f}) indica "
                f"un picco di aspirazione molto localizzato alla gola seguito da una rapida risalita di pressione."
            ),
            "quantified_impact": (
                f"Contributo dominante alla deportanza ({-s_fy * (2.0 if is_sym else 1.0):.1f} N Full-Car equivalenti), "
                f"ma elevata sensibilità al beccheggio (pitch sensitivity) e affaticamento dello strato limite a valle."
            ),
            "cad_redesign_actions": [
                f"Distribuire la sezione di gola di '{s_name}' (PID {s_id}) su un tratto longitudinale X più esteso (+40-60 mm) per allargare il plateau di basso Cp senza aumentare il picco istantaneo.",
                "Verificare la continuità tangenziale e di curvatura nella giunzione tra flat_floor, venturi e diffusore_int."
            ]
        })

    # 3. Diagnostica su Resistenza di Pressione e secondo componente per criticità
    target_drag_pid = highest_drag_pid if highest_drag_pid else second_stall_pid
    if target_drag_pid:
        d_name = target_drag_pid["zone_name"]
        d_id = target_drag_pid["zone_id"]
        d_fx = float(target_drag_pid["fx_N"])
        d_fy = float(target_drag_pid["fy_N"])
        d_stall = float(target_drag_pid["stalled_area_pct"])

        issues.append({
            "id": f"{assembly_type[:2].upper()}-WARN-03",
            "severity": "WARNING",
            "title": f"Contributo di Resistenza Aerodinamica (Drag) e Perdite Locali su '{d_name}' (PID {d_id})",
            "location_xyz": _format_pid_bbox(target_drag_pid, bbox),
            "visual_evidence": "Grafico 00 (Riparto Forze per PID), Mappa 03 (Profilo Laterale XY) e Mappa 07 (TKE)",
            "root_cause": (
                f"Il componente '{d_name}' (PID {d_id}) registra un contributo di forza longitudinale Fx = {d_fx:.2f} N "
                f"(Half-Car) a fronte di Fy = {d_fy:.2f} N, con {d_stall:.2f}% di superficie soggetta a flusso lento/separato. "
                f"Le superfici inclinate rispetto all'asse X e i bordi laterali (endplate / rampe secondarie) convertono "
                f"parte della depressione in resistenza di forma (pressure drag)."
            ),
            "quantified_impact": (
                f"Impatto sul rapporto di efficienza globale L/D = {kpis.get('efficiency_l_d', 0.0):.2f} "
                f"(Deportanza totale = {df_total:.1f} N, Drag totale = {drag_total:.1f} N)."
            ),
            "cad_redesign_actions": [
                f"Ottimizzare l'inclinazione e lo svergolamento locale di '{d_name}' (PID {d_id}) per ridurre la proiezione frontale normale a X.",
                "Per le paratie laterali (venturi_endplate), profilare il bordo d'attacco e introdurre uno scarico di pressione (footplate arch / slot) vicino alla ruota posteriore."
            ]
        })

    # 4. Verifica Condizione di Simmetria e Bilanciamento Globale PID
    issues.append({
        "id": f"{assembly_type[:2].upper()}-INFO-04",
        "severity": "INFO",
        "title": (
            "Verifica Modello Half-Car Simmetrico (Z = 0) e Bilanciamento Longitudinale CoP"
            if is_sym else "Analisi Simmetria Laterale e Bilanciamento Longitudinale CoP"
        ),
        "location_xyz": (
            f"Piano di Simmetria Z = 0.000 m | Centro di Pressione X_CoP = {kpis.get('cop_x_m', 0.0):.3f} m ({kpis.get('cop_x_pct', 50.0):.1f}% L)"
        ),
        "visual_evidence": "Mappa 00 (Topologia PID), Grafico 02 (CoP) e Grafico 03 (Distribuzione Spanwise Z)",
        "root_cause": (
            f"L'ispezione del file .cas conferma la presenza della zona di simmetria ('symmetry' a Z = 0 m): "
            f"il modello CFD rappresenta metà vettura (Z <= 0 m) e impone per condizione al contorno un'asimmetria "
            f"laterale esattamente pari a 0.00%. Il Centro di Pressione longitudinale dell'assieme cade a "
            f"X_CoP = {kpis.get('cop_x_m', 0.0):.3f} m ({kpis.get('cop_x_pct', 50.0):.1f}% della lunghezza dell'assieme)."
            if is_sym else
            f"Modello Full-Domain con indice di asimmetria laterale misurato pari a {kpis.get('lateral_asymmetry_pct', 0.0):.2f}% "
            f"e Centro di Pressione a X_CoP = {kpis.get('cop_x_m', 0.0):.3f} m."
        ),
        "quantified_impact": (
            f"Forze totali Full-Car (2x Half-Car): Deportanza = {df_total:.1f} N (CL*A = {kpis.get('cl_a_total', 0.0):.3f} m²), "
            f"Resistenza = {drag_total:.1f} N (CD*A = {kpis.get('cd_a_total', 0.0):.3f} m²), Efficienza L/D = {kpis.get('efficiency_l_d', 0.0):.2f}."
        ),
        "cad_redesign_actions": [
            f"Verificare che la posizione longitudinale X_CoP = {kpis.get('cop_x_m', 0.0):.3f} m sia allineata con il target di bilanciamento aerodinamico del veicolo.",
            "Qualora si vogliano investigare effetti di imbardata (yaw) o instabilità bi-stabili asimmetriche nel diffusore, eseguire una simulazione sul dominio completo (Full-Car senza piano symmetry)."
        ]
    })

    return issues
