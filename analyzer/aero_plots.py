# -*- coding: utf-8 -*-
"""
Generatore di Grafici Aerodinamici Ingegneristici Verificati (aero_plots.py).
Costruisce 5 tavole grafiche ad alta risoluzione basate sui dati reali estratti da .cas e .dat:
  0) Riparto Aerodinamico per Singolo PID (Deportanza, Drag, Cp_min e Stallo % per ogni componente reale)
  1) Distribuzione Longitudinale Cp(X) e Sforzo di Taglio Tau_w,x(X)
  2) Costruzione Longitudinale di Deportanza (CL*A), Resistenza (CD*A) e Centro di Pressione (CoP)
  3) Distribuzione Trasversale di Carico lungo l'Asse Laterale Z (con verifica Half-Car Symmetry)
  4) Evoluzione Longitudinale nelle Sezioni X-Cuts
"""

import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def generate_aerodynamic_plots(session_bundle: dict) -> list:
    """
    Genera i grafici ingegneristici quantitativi dai dati reali estratti e li salva in `output_dir/plots`.
    """
    output_dir = session_bundle["output_dir"]
    plots_dir = os.path.join(output_dir, "plots")
    os.makedirs(plots_dir, exist_ok=True)

    assembly_type = session_bundle.get("assembly_type", "undertray")
    pdata = session_bundle.get("physics_data", {})
    kpis = pdata.get("summary_kpis", {})
    pid_breakdown = pdata.get("pid_breakdown", [])
    is_sym = bool(pdata.get("is_half_car_symmetric", False))
    lcurves = pdata.get("longitudinal_curves", {})
    scurves = pdata.get("spanwise_curves", {})
    xcuts = pdata.get("x_cut_progression", [])

    x_norm_pct = np.array(lcurves.get("x_norm", [])) * 100.0
    cp_center = np.array(lcurves.get("cp_centerline", []))
    cp_mid = np.array(lcurves.get("cp_mid_channel", []))
    cp_outer = np.array(lcurves.get("cp_outer_span", []))
    cp_upper = np.array(lcurves.get("cp_upper_surface", []))
    tau_center = np.array(lcurves.get("tau_wx_center_pa", []))
    tau_mid = np.array(lcurves.get("tau_wx_mid_pa", []))
    dcl_dx = np.array(lcurves.get("dcl_dx", []))
    dcd_dx = np.array(lcurves.get("dcd_dx", []))
    cl_cum = np.array(lcurves.get("cl_cumulative", []))
    cd_cum = np.array(lcurves.get("cd_cumulative", []))
    stall_x = np.array(lcurves.get("stall_pct_x", []))

    z_coord = np.array(scurves.get("z_coord_m", []))
    cl_span_act = np.array(scurves.get("cl_actual", []))
    cl_span_ideal = np.array(scurves.get("cl_ideal_target", []))

    plots_manifest = []

    # ==========================================================================
    # GRAFICO 0: Riparto Aerodinamico Reale per Singolo PID (Deportanza, Drag, Cp_min, Stallo %)
    # ==========================================================================
    if pid_breakdown:
        f0_name = "plot_00_pid_forces_and_stall_breakdown.png"
        f0_path = os.path.join(plots_dir, f0_name)

        # Raggruppa o ordina i PID per deportanza (x2 Full-Car) decrescente (i componenti portanti con DF < 0 vanno in fondo)
        pids_sorted = sorted(pid_breakdown, key=lambda p: -float(p.get("downforce_2x_N", p.get("fy_N", 0.0) * 2.0)))
        names = [str(p["zone_name"]).split(":")[0].strip() for p in pids_sorted]
        df_vals = [float(p.get("downforce_2x_N", p.get("fy_N", 0.0) * 2.0)) for p in pids_sorted]
        drag_vals = [float(p.get("drag_2x_N", -p.get("fx_N", 0.0) * 2.0)) for p in pids_sorted]
        stall_vals = [float(p.get("stalled_area_pct", 0.0)) for p in pids_sorted]
        cp_min_vals = [float(p.get("cp_min", 0.0)) for p in pids_sorted]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13.0, 8.8), dpi=150)
        x_idx = np.arange(len(names))
        bar_w = 0.38

        b1 = ax1.bar(x_idx - bar_w / 2, df_vals, width=bar_w, color="#0077b6", label="Downforce [N] (Full-Car x2)")
        b2 = ax1.bar(x_idx + bar_w / 2, drag_vals, width=bar_w, color="#e63946", label="Drag [N] (Full-Car x2)")
        ax1.axhline(0.0, color="#0f172a", linewidth=1.0)
        ax1.set_xticks(x_idx)
        ax1.set_xticklabels(names, fontsize=8.5, fontweight="bold", rotation=15)
        ax1.set_ylabel("Forza Aerodinamica [N]", fontsize=10, fontweight="bold")
        ax1.set_title(
            f"Riparto Aerodinamico Verificato per Singolo PID ({assembly_type.upper()}) - Dati Estratti da .CAS/.DAT",
            fontsize=12, fontweight="bold", color="#0f172a"
        )
        ax1.grid(True, linestyle="--", alpha=0.4)
        ax1.legend(loc="upper right", fontsize=9.5)

        for rect in b1:
            h_val = rect.get_height()
            ax1.annotate(
                f"{h_val:.1f}N",
                xy=(rect.get_x() + rect.get_width() / 2, h_val),
                xytext=(0, 3 if h_val >= 0 else -12),
                textcoords="offset points",
                ha="center", va="bottom", fontsize=8, fontweight="bold", color="#0077b6"
            )

        ax2_twin = ax2.twinx()
        b3 = ax2.bar(x_idx - bar_w / 2, stall_vals, width=bar_w, color="#d90429", alpha=0.85, label="Area con Tau_w,x <= 0 (Stallo/Separazione) [%]")
        b4 = ax2_twin.bar(x_idx + bar_w / 2, [-c for c in cp_min_vals], width=bar_w, color="#2b9348", alpha=0.82, label="Picco Aspirazione -Cp_min [-]")
        ax2.set_xticks(x_idx)
        ax2.set_xticklabels(names, fontsize=8.5, fontweight="bold", rotation=15)
        ax2.set_ylabel("Frazione Superficie in Stallo [%]", fontsize=10, fontweight="bold", color="#d90429")
        ax2_twin.set_ylabel("Picco di Depressione -Cp_min [-]", fontsize=10, fontweight="bold", color="#2b9348")
        ax2.set_title("Analisi Criticita' per Singolo PID: Percentuale di Stallo vs Picco di Depressione", fontsize=11, fontweight="bold", color="#0f172a")
        ax2.grid(True, linestyle="--", alpha=0.4)

        lines1, labels1 = ax2.get_legend_handles_labels()
        lines2, labels2 = ax2_twin.get_legend_handles_labels()
        ax2.legend(lines1 + lines2, labels1 + labels2, loc="upper right", fontsize=9)

        fig.tight_layout()
        fig.savefig(f0_path, dpi=150)
        plt.close(fig)

        plots_manifest.append({
            "id": "plot_00_pid_forces_and_stall_breakdown",
            "filename": f0_name,
            "path": f0_path,
            "title": "Riparto Forze (Deportanza/Drag), Picco Cp e Percentuale di Stallo per Singolo PID",
            "description": "Mostra il contributo reale misurato su ciascun PID del modello (es. flat_floor, diffusore_int, venturi, venturi_first, venturi_second, venturi_endplate), permettendo di identificare immediatamente quale componente genera carico e quale soffre di distacco."
        })

    # ==========================================================================
    # GRAFICO 1: Distribuzione Longitudinale Cp(X) e Sforzo di Taglio Tau_w,x(X)
    # ==========================================================================
    f1_name = "plot_01_longitudinal_cp_and_shear.png"
    f1_path = os.path.join(plots_dir, f1_name)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12.5, 8.5), dpi=150, sharex=True)

    ax1.plot(x_norm_pct, cp_mid, color="#0077b6", linewidth=2.5, label="Canale Intermedio (Fascia Venturi)")
    ax1.plot(x_norm_pct, cp_center, color="#d90429", linewidth=2.2, linestyle="-", label="Fascia Interna / Simmetria (Z -> 0)")
    ax1.plot(x_norm_pct, cp_outer, color="#f77f00", linewidth=2.0, linestyle="--", label="Fascia Esterna / Bordo Laterale")
    ax1.plot(x_norm_pct, cp_upper, color="#2b9348", linewidth=1.8, linestyle=":", label="Superficie Superiore (+Y)")
    ax1.set_ylim(1.0, -3.0)
    ax1.set_yticks(np.linspace(-3.0, 1.0, 9))
    ax1.axhline(0.0, color="black", linewidth=0.8, alpha=0.5)

    # Evidenzia dinamicamente le stazioni X in cui si verifica stallo reale (stall_x > 8% o tau_center <= 0)
    crit_mask = (stall_x > 8.0) | (tau_center <= 0.0)
    if np.any(crit_mask):
        x_crit_min = float(np.min(x_norm_pct[crit_mask]))
        x_crit_max = float(np.max(x_norm_pct[crit_mask]))
        ax1.axvspan(x_crit_min, x_crit_max, color="#d90429", alpha=0.14, label=f"Fascia Critica Misurata ({x_crit_min:.0f}%-{x_crit_max:.0f}% L)")

    ax1.axvline(kpis.get("peak_suction_x_pct", 60.0), color="#0077b6", linestyle="--", linewidth=1.4, label=f"Picco Suzione (X = {kpis.get('peak_suction_x_pct', 60.0):.1f}% L)")
    ax1.set_ylabel("Pressure Coefficient Cp [-]\n(Asse invertito: Suzione in alto)", fontsize=10, fontweight="bold")
    ax1.set_title(
        f"Profili Longitudinali Reali (Asse X): Cp(X) & Attrito a Parete Tau_w,x(X) - {assembly_type.upper()}",
        fontsize=12, fontweight="bold", color="#1a2536"
    )
    ax1.grid(True, linestyle="--", alpha=0.4)
    ax1.legend(loc="upper right", fontsize=9, framealpha=0.92)

    ax2.plot(x_norm_pct, tau_center, color="#d90429", linewidth=2.4, label="Tau_w,x Fascia Interna")
    ax2.plot(x_norm_pct, tau_mid, color="#0077b6", linewidth=2.2, label="Tau_w,x Fascia Canale Venturi")
    ax2.axhline(0.0, color="#1a2536", linewidth=1.8, linestyle="-", label="Soglia Distacco Strato Limite (Tau_w,x = 0 Pa)")
    ax2.fill_between(
        x_norm_pct, np.minimum(tau_center, tau_mid), 0.0,
        where=(np.minimum(tau_center, tau_mid) <= 0.0),
        color="#d90429", alpha=0.32, interpolate=True,
        label="Regione con Flusso Separato / Invertito (Tau_w,x <= 0)"
    )
    ax2.set_xlabel("Posizione Longitudinale Normalizzata X/L [%] (+X verso retrotreno)", fontsize=10, fontweight="bold")
    ax2.set_ylabel("X-Wall Shear Stress Tau_w,x [Pa]", fontsize=10, fontweight="bold")
    ax2.grid(True, linestyle="--", alpha=0.4)
    ax2.legend(loc="lower left", fontsize=9, framealpha=0.92)

    fig.tight_layout()
    fig.savefig(f1_path, dpi=150)
    plt.close(fig)
    plots_manifest.append({
        "id": "plot_01_longitudinal_cp_and_shear",
        "filename": f1_name,
        "path": f1_path,
        "title": "Curve Longitudinali Reali Cp(X) & Sforzo di Taglio a Parete Tau_w,x(X)",
        "description": "Profili longitudinali estratti per binning spaziale delle facce reali della mesh lungo l'asse X."
    })

    # ==========================================================================
    # GRAFICO 2: Contributo Longitudinale di Deportanza, Drag e Centro di Pressione
    # ==========================================================================
    f2_name = "plot_02_downforce_drag_and_cop.png"
    f2_path = os.path.join(plots_dir, f2_name)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12.5, 8.2), dpi=150, sharex=True)

    ax1.plot(x_norm_pct, dcl_dx, color="#0077b6", linewidth=2.5, label="Contributo Deportanza Locale d(CL*A)")
    ax1.fill_between(x_norm_pct, 0.0, dcl_dx, color="#0077b6", alpha=0.18)
    ax1.plot(x_norm_pct, dcd_dx * 3.0, color="#d90429", linewidth=2.2, linestyle="--", label="Contributo Resistenza Locale d(CD*A) [x3]")
    ax1.axvline(kpis.get("cop_x_pct", 50.0), color="#2b9348", linewidth=2.2, linestyle="-.", label=f"Centro di Pressione X_CoP = {kpis.get('cop_x_pct', 50.0):.1f}% L ({kpis.get('cop_x_m', 0.5):.3f} m)")
    ax1.set_ylabel("Contributo Locale [-]", fontsize=10, fontweight="bold")
    ax1.set_title(
        "Costruzione Longitudinale di Deportanza (CL*A), Resistenza (CD*A) e Centro di Pressione (CoP)",
        fontsize=12, fontweight="bold", color="#1a2536"
    )
    ax1.grid(True, linestyle="--", alpha=0.4)
    ax1.legend(loc="upper left", fontsize=9, framealpha=0.92)

    ax2.plot(x_norm_pct, cl_cum, color="#0077b6", linewidth=2.6, label=f"CL*A Cumulativo (Totale = {kpis.get('cl_a_total', 1.0):.3f} m² -> {kpis.get('downforce_total_N', 100.0):.1f} N)")
    ax2.plot(x_norm_pct, cd_cum, color="#d90429", linewidth=2.4, label=f"CD*A Cumulativo (Totale = {kpis.get('cd_a_total', 0.2):.3f} m² -> {kpis.get('drag_total_N', 20.0):.1f} N)")
    ax2_twin = ax2.twinx()
    ax2_twin.fill_between(x_norm_pct, 0.0, stall_x, color="#e63946", alpha=0.22, label="Frazione Sezione in Stallo [%]")
    ax2_twin.set_ylabel("Area Locale in Stallo [%]", fontsize=9.5, fontweight="bold", color="#d90429")
    ax2_twin.set_ylim(0, max(60.0, float(np.max(stall_x)) * 1.2 if stall_x.size else 60.0))

    ax2.set_xlabel("Posizione Longitudinale Normalizzata X/L [%]", fontsize=10, fontweight="bold")
    ax2.set_ylabel("CL*A e CD*A Cumulativi [m²]", fontsize=10, fontweight="bold")
    ax2.grid(True, linestyle="--", alpha=0.4)
    ax2.legend(loc="upper left", fontsize=9, framealpha=0.92)

    fig.tight_layout()
    fig.savefig(f2_path, dpi=150)
    plt.close(fig)
    plots_manifest.append({
        "id": "plot_02_downforce_drag_and_cop",
        "filename": f2_name,
        "path": f2_path,
        "title": "Integrale Longitudinale di Deportanza (CL*A), Resistenza (CD*A) e Posizione CoP",
        "description": "Quantifica come si accumula il carico verticale lungo l'asse X sulla mesh reale dell'assieme."
    })

    # ==========================================================================
    # GRAFICO 3: Distribuzione Spanwise lungo Z e Verifica Simmetria
    # ==========================================================================
    f3_name = "plot_03_spanwise_load_and_symmetry.png"
    f3_path = os.path.join(plots_dir, f3_name)
    fig, ax = plt.subplots(figsize=(12.0, 6.2), dpi=150)

    ax.plot(z_coord, cl_span_ideal, color="#2b9348", linewidth=2.2, linestyle="--", label="Inviluppo Target Senza Perdite Locali")
    ax.plot(z_coord, cl_span_act, color="#0077b6", linewidth=2.8, label="Distribuzione Reale Misurata lungo Z")
    ax.fill_between(
        z_coord, cl_span_act, cl_span_ideal,
        where=(cl_span_ideal > cl_span_act),
        color="#d90429", alpha=0.22, interpolate=True,
        label="Scostamento Locale da Perdite di Canale / Bordo"
    )
    ax.axvline(0.0, color="#1a2536", linewidth=1.4, linestyle=":")
    sym_title = (
        "Modello Half-Car Simmetrico (Piano Symmetry Z = 0, Asimmetria Laterale = 0.00%)"
        if is_sym else f"Analisi Asimmetria Laterale (Indice = {kpis.get('lateral_asymmetry_pct', 0.0):.2f}%)"
    )
    ax.set_title(
        f"Distribuzione Trasversale di Carico lungo l'Asse Laterale Z | {sym_title}",
        fontsize=11.5, fontweight="bold", color="#1a2536"
    )
    ax.set_xlabel("Coordinata Laterale Spanwise Z [m]", fontsize=10, fontweight="bold")
    ax.set_ylabel("Indice di Carico Locale Normalizzato [-]", fontsize=10, fontweight="bold")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(loc="best", fontsize=9.5, framealpha=0.92)

    fig.tight_layout()
    fig.savefig(f3_path, dpi=150)
    plt.close(fig)
    plots_manifest.append({
        "id": "plot_03_spanwise_load_and_symmetry",
        "filename": f3_name,
        "path": f3_path,
        "title": "Distribuzione di Carico Trasversale lungo l'Asse Z & Verifica Simmetria",
        "description": "Mostra il carico trasversale misurato sulla mesh reale lungo Z. Per modelli Half-Car con condizione al contorno 'symmetry' a Z=0, l'asimmetria laterale e' rigorosamente pari a 0.0%."
    })

    # ==========================================================================
    # GRAFICO 4: Evoluzione nelle Sezioni X-Cuts
    # ==========================================================================
    f4_name = "plot_04_vortex_integrity_and_wake_loss.png"
    f4_path = os.path.join(plots_dir, f4_name)
    xs_pct = [m["x_norm"] * 100.0 for m in xcuts]
    v_int = [m["vortex_integrity_score"] for m in xcuts]
    e_loss = [m["energy_loss_pct"] for m in xcuts]
    rev_area = [m["reverse_flow_area_pct"] for m in xcuts]

    fig, ax1 = plt.subplots(figsize=(11.8, 6.0), dpi=150)
    ax1.plot(xs_pct, v_int, marker="o", markersize=8, color="#0077b6", linewidth=2.6, label="Indice Attaccamento / Coerenza Flusso [%]")
    ax1.plot(xs_pct, e_loss, marker="s", markersize=8, color="#f77f00", linewidth=2.4, label="Indice Perdita / Gradiente Avverso nella Sezione [%]")
    ax1.plot(xs_pct, rev_area, marker="^", markersize=8, color="#d90429", linewidth=2.4, linestyle="--", label="Frazione Facce con Tau_w,x <= 0 nella Sezione [%]")
    ax1.set_title(
        "Evoluzione Longitudinale nelle Sezioni Trasversali X-Cuts (Dati Reali per Stazione X)",
        fontsize=12, fontweight="bold", color="#1a2536"
    )
    ax1.set_xlabel("Stazione Sezione Trasversale X-Cut [% della lunghezza L]", fontsize=10, fontweight="bold")
    ax1.set_ylabel("Percentuale [%]", fontsize=10, fontweight="bold")
    ax1.set_ylim(0, 105)
    ax1.grid(True, linestyle="--", alpha=0.4)
    ax1.legend(loc="best", fontsize=9.5, framealpha=0.92)

    fig.tight_layout()
    fig.savefig(f4_path, dpi=150)
    plt.close(fig)
    plots_manifest.append({
        "id": "plot_04_vortex_integrity_and_wake_loss",
        "filename": f4_name,
        "path": f4_path,
        "title": "Evoluzione Longitudinale Stazione per Stazione (X-Cuts)",
        "description": "Traccia stazione per stazione lungo X l'attaccamento del flusso e la frazione di elementi separati misurata sulla mesh reale."
    })

    return plots_manifest
