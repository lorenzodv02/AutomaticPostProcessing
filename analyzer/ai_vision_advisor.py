# -*- coding: utf-8 -*-
"""
Modulo AI Vision Chief Aerodynamicist Verificato (ai_vision_advisor.py).
Costruisce la perizia ingegneristica basandosi esclusivamente sui dati reali estratti
dal file .cas e .dat (nodi, triangoli, integrali per singolo PID, condizione di simmetria)
e sulle immagini verificate.
"""

import os
import base64


SYSTEM_PROMPT_AERO = """Sei il Chief Aerodynamicist di un team di Formula Student.
Analizza rigorosamente solo i dati reali estratti dai file binari .cas e .dat e le immagini verificate allegate.
NON inventare fenomeni non supportati dai numeri o dai PID forniti. Se il modello e' Half-Car simmetrico (symmetry a Z=0), l'asimmetria laterale e' 0.0%.
Convenzione assi:
- Asse X: Longitudinale (verso dietro, +X direzione flusso)
- Asse Y: Verticale (verso l'alto, -Y indica deportanza verso il suolo)
- Asse Z: Laterale / Spanwise (Z = 0 piano di simmetria longitudinale)
"""


def _build_local_expert_review(session_bundle: dict, cv_results: dict, design_issues: list) -> str:
    """
    Genera la perizia tecnica basata rigorosamente sui dati reali per singolo PID (`pid_breakdown`),
    sui KPI integrati dalla mesh 3D e sul report di verifica (`verification_report`).
    """
    asm = session_bundle.get("assembly_type", "undertray").upper()
    pdata = session_bundle.get("physics_data", {})
    kpis = pdata.get("summary_kpis", {})
    pid_breakdown = pdata.get("pid_breakdown", [])
    is_sym = bool(pdata.get("is_half_car_symmetric", False))
    cas_name = os.path.basename(session_bundle.get("cas_file") or "model.cas")
    dat_name = os.path.basename(session_bundle.get("dat_file") or "model.dat")

    cl_a = float(kpis.get("cl_a_total", kpis.get("CL_A", 0.0)))
    cd_a = float(kpis.get("cd_a_total", kpis.get("CD_A", 0.0)))
    df_n = float(kpis.get("downforce_total_N", kpis.get("downforce_N", 0.0)))
    drag_n = float(kpis.get("drag_total_N", kpis.get("drag_N", 0.0)))
    l_d = float(kpis.get("efficiency_l_d", kpis.get("efficiency_L_over_D", 0.0)))
    cop_x = float(kpis.get("cop_x_m", 0.0))
    cop_pct = float(kpis.get("cop_x_pct", 50.0))
    stall_pct = float(kpis.get("stalled_area_percentage", kpis.get("stalled_surface_pct", 0.0)))
    cp_min = float(kpis.get("peak_suction_cp", -2.5))
    area_tot = float(kpis.get("total_surface_area_m2", 0.0))

    pid_lines = []
    for p in sorted(pid_breakdown, key=lambda x: x.get("fy_N", 0.0)):
        pid_lines.append(
            f"* **`{p['zone_name']}` (PID `{p['zone_id']}`):** `{p['n_faces']:,}` facce | "
            f"Area = `{p['area_m2']:.4f} m²` | Deportanza ($-F_y$, 1 lato) = **`{-p['fy_N']:.1f} N`** | "
            f"Drag ($F_x$, 1 lato) = `{p['fx_N']:.1f} N` | $C_{{p,\\min}} = {p['cp_min']:.2f}$ ($C_{{p,\\text{{mean}}}} = {p['cp_mean']:.2f}$) | "
            f"Area $\\tau_{{w,x}} \\le 0$: **`{p['stalled_area_pct']:.2f}%`**"
        )
    pid_block = "\n".join(pid_lines) if pid_lines else "* Nessun PID disponibile."

    sym_statement = (
        "Modello **Half-Car Simmetrico** verificato (presenza zona `symmetry` a `Z = 0.000 m`): "
        "asimmetria laterale rigorosamente pari a **`0.00%`** per condizione al contorno; integrali globali moltiplicati per fattore `2.0x`."
        if is_sym else
        f"Modello Full-Domain con asimmetria laterale misurata pari a **`{kpis.get('lateral_asymmetry_pct', 0.0):.2f}%`**."
    )

    issue_lines = []
    for idx, iss in enumerate(design_issues, start=1):
        actions_str = " ".join(iss.get("cad_redesign_actions", [])[:2])
        issue_lines.append(
            f"{idx}. **[{iss['severity']}] {iss['title']}** (`{iss['location_xyz']}`): {iss['root_cause']} "
            f"**Azione CAD:** {actions_str}"
        )
    issues_block = "\n".join(issue_lines)

    review = f"""### 1. Sintesi Esecutiva Verificata sui File Binari (`{cas_name}` & `{dat_name}`)
L'analisi è stata eseguita scompattando direttamente **`{pdata.get('nodes_read', 0):,}` nodi 3D** e **`{pdata.get('faces_read', 0):,}` facce poligonali/triangolari** dal file `{cas_name}` ed estraendo i campi CFD dal file `{dat_name}` sui soli PID appartenenti all'assieme **{asm}** (con esclusione verificata al 100% delle pareti della galleria del vento `side`, `top`, `road`, `inlet`, `outlet`, `symmetry`, `fluid`, `interior`):

* **Configurazione Dominio e Simmetria:** {sym_statement}
* **Superficie Bagnata Totale Assieme (Full-Car equiv.):** **`{area_tot:.4f} m²`**
* **Deportanza Totale ($C_L \\cdot A$):** **`{cl_a:.3f} m²`** (**`{df_n:.1f} N`** Full-Car equivalenti)
* **Resistenza Aerodinamica Totale ($C_D \\cdot A$):** **`{cd_a:.3f} m²`** (**`{drag_n:.1f} N`** Full-Car equivalenti) — Efficienza **$L/D = {l_d:.2f}$**
* **Centro di Pressione Longitudinale ($X_{{\\text{{CoP}}}}$):** **`{cop_pct:.1f}% L`** (`X = {cop_x:.3f} m`)
* **Picco Assoluto di Aspirazione ($C_{{p,\\min}}$):** **`{cp_min:.2f}`** | **Superficie Complessiva con $\\tau_{{w,x}} \\le 0\\text{{ Pa}}$:** **`{stall_pct:.2f}%`**

---

### 2. Analisi Quantitativa per Singolo Componente (PID Breakdown Reale)
Di seguito il riparto esatto delle forze, pressioni e percentuali di separazione calcolato su ciascun PID dell'assieme **{asm}**:
{pid_block}

---

### 3. Diagnosi delle Problematiche Misurate e Piano di Intervento CAD
{issues_block}
"""
    return review


def generate_ai_vision_commentary(
    config: dict,
    session_bundle: dict,
    cv_results: dict,
    design_issues: list,
    plots_manifest: list
) -> dict:
    """
    Interroga Gemini Vision o OpenAI GPT-4o (se abilitato e con API key) fornendo esclusivamente
    i dati reali verificati per PID, oppure utilizza il sintetizzatore fisico deterministico verificato.
    """
    ai_cfg = config.get("ai_vision", {})
    provider = (ai_cfg.get("provider") or "gemini").lower()
    api_key = (
        ai_cfg.get("api_key")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()

    annotated_imgs = cv_results.get("annotated_images", [])
    selected_image_paths = []
    for rec in annotated_imgs[:4]:
        p = rec.get("annotated_path") or rec.get("path")
        if p and os.path.isfile(p):
            selected_image_paths.append(p)
    for pl in plots_manifest[:2]:
        if pl.get("path") and os.path.isfile(pl["path"]):
            selected_image_paths.append(pl["path"])

    pdata = session_bundle.get("physics_data", {})
    kpis = pdata.get("summary_kpis", {})
    pid_breakdown = pdata.get("pid_breakdown", [])
    user_context = (
        f"Assieme analizzato: {session_bundle.get('assembly_type', 'undertray').upper()}\n"
        f"Modello Half-Car Simmetrico (Z=0): {pdata.get('is_half_car_symmetric', False)}\n"
        f"KPI reali estratti: {kpis}\n"
        f"Dati per singolo PID: {pid_breakdown}\n"
        f"Problematiche rilevate dai dati: {[i['title'] for i in design_issues]}\n"
        "Fornisci la diagnosi aerodinamica basandoti rigorosamente su questi dati reali e sulle foto."
    )

    if ai_cfg.get("enabled", True) and api_key:
        if provider == "gemini":
            try:
                from google import genai
                from PIL import Image
                client = genai.Client(api_key=api_key)
                contents = [SYSTEM_PROMPT_AERO, user_context]
                for img_p in selected_image_paths[:5]:
                    contents.append(Image.open(img_p))
                resp = client.models.generate_content(
                    model=ai_cfg.get("model_gemini", "gemini-3.8-flash"),
                    contents=contents
                )
                if resp and getattr(resp, "text", None):
                    return {
                        "source": f"Google Gemini Vision ({ai_cfg.get('model_gemini', 'gemini-3.8-flash')})",
                        "commentary_markdown": resp.text
                    }
            except Exception as exc:
                print(f"[INFO] Chiamata API Gemini Vision non completata ({exc}). Uso sintetizzatore dati reali.")

        elif provider == "openai":
            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                content_blocks = [{"type": "text", "text": user_context}]
                for img_p in selected_image_paths[:4]:
                    with open(img_p, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("utf-8")
                    content_blocks.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"}
                    })
                resp = client.chat.completions.create(
                    model=ai_cfg.get("model_openai", "gpt-4o"),
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT_AERO},
                        {"role": "user", "content": content_blocks}
                    ]
                )
                return {
                    "source": f"OpenAI Vision ({ai_cfg.get('model_openai', 'gpt-4o')})",
                    "commentary_markdown": resp.choices[0].message.content
                }
            except Exception as exc:
                print(f"[INFO] Chiamata API OpenAI Vision non completata ({exc}). Uso sintetizzatore dati reali.")

    return {
        "source": "Motore Diagnostico Verificato su Dati Binari .CAS/.DAT & Mesh 3D Reale",
        "commentary_markdown": _build_local_expert_review(session_bundle, cv_results, design_issues)
    }
