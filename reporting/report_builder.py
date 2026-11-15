# -*- coding: utf-8 -*-
"""
Generatore del Report Diagnostico Aerodinamico Interattivo HTML/PDF e Markdown (report_builder.py).
Include:
  - Sezione di Audit e Verifica Rigorosa Dati (`verification_report`: CHK-01 .. CHK-07,
    dove CHK-07 verifica che i totali coincidano con la somma dei PID)
  - Tabella Quantitativa per Singolo PID (`pid_breakdown`: area, facce, forze, Cp_min, stallo %)
  - KPI Aerodinamici estratti da .cas e .dat (con supporto Half-Car Symmetry)
  - Schede delle Problematiche di Design (CRITICAL, WARNING, INFO) basate sui dati reali
  - Galleria interattiva delle foto (con switch Foto Annotata CV <-> Foto Originale)
  - Grafici ingegneristici ad alta risoluzione
"""

import os
import io
import re
import html
import base64
import zipfile
import datetime


_BRAND_MONOGRAM_CACHE = None


def _brand_monogram_uri() -> str:
    """
    Monogramma UC in data-URI per l'header del report (stringa vuota se manca).

    Il report deve restare un file unico e standalone: l'immagine viaggia
    dentro l'HTML in Base64, come tutte le altre.
    """
    global _BRAND_MONOGRAM_CACHE
    if _BRAND_MONOGRAM_CACHE is not None:
        return _BRAND_MONOGRAM_CACHE
    uri = ""
    try:
        import base64

        from brand import asset_path

        path = asset_path("uc-monogram-white.png")
        if path:
            with open(path, "rb") as handle:
                uri = "data:image/png;base64," + base64.b64encode(handle.read()).decode("ascii")
    except Exception:
        uri = ""
    _BRAND_MONOGRAM_CACHE = uri
    return uri


def _rel_path(target_path: str, base_dir: str) -> str:
    """Calcola il percorso relativo con forward slash per l'inclusione nell'HTML."""
    if not target_path:
        return ""
    try:
        return os.path.relpath(target_path, base_dir).replace("\\", "/")
    except Exception:
        return target_path.replace("\\", "/")


def _file_to_data_uri(target_path: str, fallback_base_dir: str = "") -> str:
    """
    Converte un'immagine PNG/GIF/JPG in un Data URI Base64 incorporato (data:image/...;base64,...)
    cosi' che l'intero report HTML sia 100% standalone in un UNICO file .html pronto da inviare
    senza bisogno della cartella delle immagini.
    """
    if not target_path:
        return ""
    if not os.path.isfile(target_path):
        return _rel_path(target_path, fallback_base_dir)
    try:
        ext = os.path.splitext(target_path)[1].lower()
        mime = "image/gif" if ext == ".gif" else ("image/jpeg" if ext in (".jpg", ".jpeg") else "image/png")
        with open(target_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return _rel_path(target_path, fallback_base_dir)


def _build_pid_excel_xlsx_bytes(excel_rows: list) -> bytes:
    """
    Genera in memoria un file Microsoft Excel nativo (.xlsx, OpenXML) contenente le colonne:
      - PID
      - Downforce [N] (x2)
      - Drag [N] (x2)
      - Efficienza (L/D)
    con i valori gia' moltiplicati per due (Full-Car).
    """
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="PID_Aero_2x" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )

    # Ordina le righe PID in ordine alfabetico (A-Z), mantenendo l'eventuale riga finale di TOTALE in fondo
    pid_items = [r for r in excel_rows if not str(r.get("pid", "")).upper().startswith("TOTALE")]
    total_items = [r for r in excel_rows if str(r.get("pid", "")).upper().startswith("TOTALE")]
    pid_items.sort(key=lambda x: str(x.get("pid", "")).strip().lower())
    sorted_excel_rows = pid_items + total_items

    sheet_rows_xml = [
        '<row r="1">'
        '<c r="A1" t="inlineStr"><is><t>PID</t></is></c>'
        '<c r="B1" t="inlineStr"><is><t>Downforce [N] (x2)</t></is></c>'
        '<c r="C1" t="inlineStr"><is><t>Drag Totale [N] (x2)</t></is></c>'
        '<c r="D1" t="inlineStr"><is><t>Drag Pressione [N] (x2)</t></is></c>'
        '<c r="E1" t="inlineStr"><is><t>Drag Viscosa [N] (x2)</t></is></c>'
        '<c r="F1" t="inlineStr"><is><t>Efficienza (L/D)</t></is></c>'
        '</row>'
    ]
    for r_idx, r_data in enumerate(sorted_excel_rows, start=2):
        pid_str = html.escape(str(r_data["pid"]))
        df_v = float(r_data["downforce_2x"])
        dr_tot_v = float(r_data.get("drag_total_2x", r_data.get("drag_2x", 0.0)))
        dr_p_v = float(r_data.get("drag_press_2x", 0.0))
        dr_v_v = float(r_data.get("drag_visc_2x", 0.0))
        ld_v = float(r_data["ld"])
        sheet_rows_xml.append(
            f'<row r="{r_idx}">'
            f'<c r="A{r_idx}" t="inlineStr"><is><t>{pid_str}</t></is></c>'
            f'<c r="B{r_idx}"><v>{df_v:.2f}</v></c>'
            f'<c r="C{r_idx}"><v>{dr_tot_v:.2f}</v></c>'
            f'<c r="D{r_idx}"><v>{dr_p_v:.2f}</v></c>'
            f'<c r="E{r_idx}"><v>{dr_v_v:.2f}</v></c>'
            f'<c r="F{r_idx}"><v>{ld_v:.2f}</v></c>'
            f'</row>'
        )

    sheet1_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<cols>'
        '<col min="1" max="1" width="28" customWidth="1"/>'
        '<col min="2" max="6" width="22" customWidth="1"/>'
        '</cols>'
        '<sheetData>' + "".join(sheet_rows_xml) + '</sheetData>'
        '</worksheet>'
    )

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet1_xml)
    return bio.getvalue()


def _md_to_simple_html(md_text: str) -> str:
    """Converte il Markdown della perizia tecnica in HTML pulito e formattato."""
    lines = md_text.splitlines()
    out = []
    in_list = False
    for line in lines:
        s = line.strip()
        if not s:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        if s == "---":
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append('<hr class="section-divider"/>')
            continue
        if s.startswith("### "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f'<h3 class="ai-subtitle">{html.escape(s[4:])}</h3>')
            continue
        if s.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f'<h2 class="ai-title">{html.escape(s[3:])}</h2>')
            continue
        if s.startswith("* ") or s.startswith("- ") or (len(s) > 3 and s[0].isdigit() and s[1:3] == ". "):
            if not in_list:
                out.append('<ul class="ai-list">')
                in_list = True
            item_txt = s[2:] if s[:2] in ("* ", "- ") else s[3:]
            item_txt = html.escape(item_txt)
            item_txt = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", item_txt)
            item_txt = re.sub(r"`(.+?)`", r'<code class="inline-code">\1</code>', item_txt)
            out.append(f"<li>{item_txt}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            p_txt = html.escape(s)
            p_txt = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", p_txt)
            p_txt = re.sub(r"`(.+?)`", r'<code class="inline-code">\1</code>', p_txt)
            out.append(f"<p>{p_txt}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def build_diagnostic_reports(
    config: dict,
    session_bundle: dict,
    cv_results: dict,
    plots_manifest: list,
    design_issues: list,
    ai_review: dict
) -> dict:
    """
    Genera il report interattivo `CFD_Aero_Diagnostic_Report.html` e il riepilogo
    `CFD_Aero_Diagnostic_Report.md` nella cartella `output_dir`.
    """
    output_dir = session_bundle["output_dir"]
    os.makedirs(output_dir, exist_ok=True)

    assembly_type = session_bundle.get("assembly_type", "undertray")
    asm_display = config.get("assemblies", {}).get(assembly_type, {}).get("display_name", assembly_type.upper())
    pdata = session_bundle.get("physics_data", {})
    kpis = pdata.get("summary_kpis", {})
    pid_breakdown = pdata.get("pid_breakdown", [])
    is_sym = bool(pdata.get("is_half_car_symmetric", False))
    ver_rep = session_bundle.get("verification_report") or cv_results.get("verification_report") or {}
    bbox = session_bundle.get("bounding_box", {})
    cas_file = session_bundle.get("cas_file") or ""
    dat_file = session_bundle.get("dat_file") or ""
    ses_file = session_bundle.get("ses_file_path") or ""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # "lift" di Fluent (proiezione su +Y) e convenzione scelta per il report
    lift_n = float(kpis.get("lift_N", kpis.get("lift_total_N", 0.0)))
    force_convention = str(kpis.get("force_convention", "lift") or "lift").lower()
    force_note = ("Deportanza secondo la definizione Fluent 'downforce' (positiva verso il basso)"
                  if force_convention == "downforce"
                  else "Deportanza secondo la definizione Fluent 'lift' (proiezione su +Y, negativa verso il basso)")
    visc_source = str(kpis.get("viscous_source", "n/d") or "n/d")
    cl_a = float(kpis.get("cl_a_total", kpis.get("CL_A", 0.0)))
    cd_a = float(kpis.get("cd_a_total", kpis.get("CD_A", 0.0)))
    df_n = float(kpis.get("downforce_total_N", kpis.get("downforce_N", 0.0)))
    drag_n = float(kpis.get("drag_total_N", kpis.get("drag_N", 0.0)))
    # Efficienza mostrata in valore assoluto: con la convenzione "lift" il
    # rapporto firmato sarebbe negativo, ma la bonta' aerodinamica non cambia segno.
    l_d_signed = float(kpis.get("efficiency_l_d", kpis.get("efficiency_L_over_D", 0.0)))
    l_d = abs(l_d_signed)
    cop_x = float(kpis.get("cop_x_m", 0.0))
    cop_pct = float(kpis.get("cop_x_pct", 50.0))
    cop_wb_raw = kpis.get("cop_wheelbase_pct")
    cop_wb = float(cop_wb_raw) if isinstance(cop_wb_raw, (int, float)) else None
    cop_wb_html = (
        f" &middot; {cop_wb:.1f}% del passo" if cop_wb is not None else ""
    )
    stall_val = float(kpis.get("stalled_area_percentage", kpis.get("stalled_surface_pct", 0.0)))
    cp_min = float(kpis.get("peak_suction_cp", -2.5))
    cp_min_x = float(kpis.get("peak_suction_x_pct", 60.0))
    asym_val = float(kpis.get("lateral_asymmetry_pct", 0.0))
    vortex_stab = float(kpis.get("vortex_stability_pct", 80.0))

    # 0. Costruzione Tabella Audit di Verifica Dati & Immagini
    ver_rows_html = []
    for chk in ver_rep.get("checks", []):
        st = chk.get("status", "PASS")
        st_cls = "badge-info" if st == "PASS" else ("badge-warning" if st == "WARN" else "badge-critical")
        ver_rows_html.append(f"""
        <tr>
            <td><code>{html.escape(chk.get('id', ''))}</code></td>
            <td><strong>{html.escape(chk.get('name', ''))}</strong></td>
            <td><span class="badge {st_cls}">{html.escape(st)}</span></td>
            <td><code>{html.escape(str(chk.get('measured', '')))}</code></td>
            <td>{html.escape(chk.get('details', ''))}</td>
        </tr>
        """)

    # 1. Costruzione Tabella Quantitativa per Singolo PID (Valori gia' moltiplicati x2 Full-Car + Export Excel .xlsx)
    pid_rows_html = []
    excel_rows = []
    sum_df_2x = 0.0
    sum_dr_2x = 0.0
    sum_dr_p_2x = 0.0
    sum_dr_v_2x = 0.0

    # Ordina per Downforce (x2) decrescente
    pids_sorted = sorted(
        pid_breakdown,
        key=lambda x: -float(x.get("downforce_2x_N", float(x.get("fy_N", 0.0)) * 2.0))
    )
    for p in pids_sorted:
        pb = p.get("bbox", {})
        pb_str = f"X:[{pb.get('xmin',0):.2f},{pb.get('xmax',0):.2f}] Y:[{pb.get('ymin',0):.2f},{pb.get('ymax',0):.2f}] Z:[{pb.get('zmin',0):.2f},{pb.get('zmax',0):.2f}]"
        st_p = float(p.get("stalled_area_pct", 0.0))
        st_col = "#E42320" if st_p >= 8.0 else ("#FDEB19" if st_p >= 2.0 else "#D8EEFC")

        pid_clean = str(p.get("zone_name", "")).split(":")[0].strip()
        df_2x = float(p.get("downforce_2x_N", float(p.get("fy_N", 0.0)) * 2.0))
        dr_tot_2x = float(p.get("drag_2x_N", -float(p.get("fx_N", 0.0)) * 2.0))
        dr_p_2x = float(p.get("drag_pressure_2x_N", dr_tot_2x))
        dr_v_2x = float(p.get("drag_viscous_2x_N", 0.0))
        ld_pid = round(abs(df_2x) / dr_tot_2x, 2) if abs(dr_tot_2x) > 0.01 else 0.0
        sum_df_2x += df_2x
        sum_dr_2x += dr_tot_2x
        sum_dr_p_2x = locals().get("sum_dr_p_2x", 0.0) + dr_p_2x
        sum_dr_v_2x = locals().get("sum_dr_v_2x", 0.0) + dr_v_2x

        excel_rows.append({
            "pid": pid_clean,
            "downforce_2x": round(df_2x, 2),
            "drag_total_2x": round(dr_tot_2x, 2),
            "drag_press_2x": round(dr_p_2x, 2),
            "drag_visc_2x": round(dr_v_2x, 2),
            "ld": ld_pid,
        })

        df_col = "#FDEB19" if df_2x >= 0.0 else "#FDEB19"
        df_html = f'<strong style="color:{df_col};">{df_2x:.2f} N</strong>'
        if df_2x < 0.0:
            df_html += ' <span style="font-size:0.75rem; color:#FDEB19; font-weight:normal;">(Portanza)</span>'

        pid_rows_html.append(f"""
        <tr>
            <td><strong>{html.escape(pid_clean)}</strong></td>
            <td>{df_html}</td>
            <td><strong style="color:#FF7A76;">{dr_tot_2x:.2f} N</strong></td>
            <td><strong style="color:#D8EEFC;">{ld_pid:.2f}</strong></td>
            <td>{p['n_faces']:,}</td>
            <td>{p['area_m2'] * 2.0:.4f} m&sup2;</td>
            <td><code>{p['cp_min']:.2f}</code></td>
            <td><code>{p['cp_mean']:.2f}</code></td>
            <td><strong style="color:{st_col};">{st_p:.2f}%</strong></td>
            <td style="font-size:0.78rem; font-family:monospace;">{html.escape(pb_str)}</td>
        </tr>
        """)

    tot_ld_2x = round(abs(sum_df_2x) / abs(sum_dr_2x), 2) if abs(sum_dr_2x) > 0.01 else 0.0
    excel_rows.append({
        "pid": "TOTALE ASSIEME (x2)",
        "downforce_2x": round(sum_df_2x, 2),
        "drag_total_2x": round(sum_dr_2x, 2),
        "drag_press_2x": round(sum_dr_p_2x, 2),
        "drag_visc_2x": round(sum_dr_v_2x, 2),
        "ld": tot_ld_2x,
    })
    pid_rows_html.append(f"""
        <tr style="background: rgba(253, 235, 25, 0.10); border-top: 2px solid #FDEB19;">
            <td><strong>TOTALE ASSIEME (x2)</strong></td>
            <td><strong style="color:#FDEB19; font-size:1.0rem;">{sum_df_2x:.2f} N</strong></td>
            <td><strong style="color:#FF7A76; font-size:1.0rem;">{sum_dr_2x:.2f} N</strong></td>
            <td><strong style="color:#D8EEFC; font-size:1.0rem;">{tot_ld_2x:.2f}</strong></td>
            <td colspan="6" style="color:var(--text-muted); font-size:0.84rem;">Somma di pressione e viscosa (Full-Car): &egrave; la forza finale che conta</td>
        </tr>
    """)

    xlsx_bytes = _build_pid_excel_xlsx_bytes(excel_rows)
    xlsx_b64_payload = base64.b64encode(xlsx_bytes).decode("ascii")
    xlsx_out_path = os.path.join(output_dir, "Tabella_PID_Aerodinamica_2x.xlsx")
    try:
        with open(xlsx_out_path, "wb") as fx:
            fx.write(xlsx_bytes)
    except Exception:
        pass

    # Salva una copia dell'Excel anche nella cartella dove risiedono i file .cas/.dat
    cas_dir = os.path.dirname(os.path.abspath(cas_file)) if cas_file else None
    if cas_dir and os.path.isdir(cas_dir):
        try:
            with open(os.path.join(cas_dir, "Tabella_PID_Aerodinamica_2x.xlsx"), "wb") as fx:
                fx.write(xlsx_bytes)
        except Exception:
            pass

    # 2. Costruzione Card Problematiche di Design
    issue_cards_html = []
    for iss in design_issues:
        sev = iss["severity"]
        badge_cls = "badge-critical" if sev == "CRITICAL" else ("badge-warning" if sev == "WARNING" else "badge-info")
        card_cls = "issue-critical" if sev == "CRITICAL" else ("issue-warning" if sev == "WARNING" else "issue-info")
        actions_li = "".join(f"<li>{html.escape(a)}</li>" for a in iss.get("cad_redesign_actions", []))
        issue_cards_html.append(f"""
        <div class="issue-card {card_cls}">
            <div class="issue-header">
                <div>
                    <span class="badge {badge_cls}">{html.escape(sev)}</span>
                    <span class="issue-id">{html.escape(iss['id'])}</span>
                    <h3 class="issue-title">{html.escape(iss['title'])}</h3>
                </div>
                <div class="issue-loc"><strong>Coordinate Reali (X, Y, Z):</strong> {html.escape(iss['location_xyz'])}</div>
            </div>
            <div class="issue-body">
                <p><strong>Evidenza Visiva nelle Mappe &amp; Grafici:</strong> <span class="highlight-ref">{html.escape(iss['visual_evidence'])}</span></p>
                <p><strong>Causa Fluidodinamica Misurata:</strong> {html.escape(iss['root_cause'])}</p>
                <p><strong>Impatto Quantificato:</strong> <span class="impact-text">{html.escape(iss['quantified_impact'])}</span></p>
                <div class="cad-actions-box">
                    <strong>Azioni di Riprogettazione CAD Consigliate:</strong>
                    <ul>{actions_li}</ul>
                </div>
            </div>
        </div>
        """)

    # 3. Costruzione Galleria Foto (100% Standalone con Base64 Data URI e switch Annotata CV vs Originale)
    photo_cards_html = []
    for idx, img in enumerate(cv_results.get("annotated_images", [])):
        raw_uri = _file_to_data_uri(img.get("path", ""), output_dir)
        ann_uri = _file_to_data_uri(img.get("annotated_path", ""), output_dir) or raw_uri
        findings_li = "".join(f"<li>{html.escape(f)}</li>" for f in img.get("visual_findings", []))
        cat_label = img.get("category", "meta_view").replace("_", " ").upper()
        title_esc = html.escape(img.get("title", img.get("filename", "")))
        photo_cards_html.append(f"""
        <div class="photo-card" data-category="{html.escape(img.get('category', 'all'))}">
            <div class="photo-header">
                <div>
                    <span class="cat-pill">{cat_label}</span>
                    <h4>{title_esc}</h4>
                </div>
                <div class="photo-controls">
                    <button class="btn-toggle active" onclick="switchImg('img_{idx}', 'ann', this)">Vista Annotata Verificata</button>
                    <button class="btn-toggle" onclick="switchImg('img_{idx}', 'raw', this)">Vista Pulita Originale</button>
                </div>
            </div>
            <div class="photo-img-wrapper">
                <img id="img_{idx}" src="{ann_uri}" data-ann="{ann_uri}" data-raw="{raw_uri}" alt="{title_esc}" loading="lazy" style="cursor: zoom-in;" onclick="openLightbox(this.src, this.alt)"/>
            </div>
            <div class="photo-footer">
                <p class="photo-desc">{html.escape(img.get('description', ''))}</p>
                {f'<ul class="photo-findings">{findings_li}</ul>' if findings_li else ''}
            </div>
        </div>
        """)

    # 4. Costruzione Sezione Grafici Aerodinamici (100% Standalone con Base64 Data URI)
    plot_cards_html = []
    for pl in plots_manifest:
        pl_uri = _file_to_data_uri(pl.get("path", ""), output_dir)
        pl_title = html.escape(pl.get("title", ""))
        plot_cards_html.append(f"""
        <div class="plot-card">
            <h4>{pl_title}</h4>
            <img src="{pl_uri}" alt="{pl_title}" loading="lazy" style="cursor: zoom-in;" onclick="openLightbox(this.src, this.alt)"/>
            <p>{html.escape(pl.get('description', ''))}</p>
        </div>
        """)

    # 4b. Costruzione Sezione Animazione GIF Sweep Progressivo X-Cut del Contour Cp (100% Standalone Base64)
    xcut_gif_path = session_bundle.get("xcut_cp_gif") or os.path.join(output_dir, "images_raw", "10_cp_xcut_progressive_sweep.gif")
    xcut_gif_section_html = ""
    if xcut_gif_path and os.path.isfile(xcut_gif_path):
        gif_uri = _file_to_data_uri(xcut_gif_path, output_dir)
        xcut_gif_section_html = f"""
    <!-- SEZIONE 4B: ANIMAZIONE GIF SWEEP PROGRESSIVO SEZIONI TRASVERSALI X-CUT CONTOUR CP -->
    <div class="section-box">
        <div class="section-title">
            <span>4b. Animazione GIF: Evoluzione Sezioni Trasversali (X-Cut) del Contour Cp (Anteriore &rarr; Posteriore)</span>
            <span class="badge badge-info">SWEEP 26 SEZIONI REALI X-MIN &rarr; X-MAX</span>
        </div>
        <div style="background: var(--bg-card-alt); border: 1px solid var(--border-col); border-radius: 10px; padding: 16px; text-align: center;">
            <img src="{gif_uri}" alt="Animazione GIF Sweep Sezioni Trasversali Cp" style="max-width: 100%; height: auto; border-radius: 8px; border: 1px solid var(--border-col); cursor: zoom-in;" onclick="openLightbox(this.src, this.alt)"/>
            <p style="margin-top: 10px; font-size: 0.90rem; color: var(--text-muted);">
                <strong>Pannello Sinistro:</strong> Mappa reale di aspirazione <em>C<sub>p</sub></em> con linea rossa del piano di taglio che scorre progressivamente dall'anteriore (<em>X<sub>min</sub></em>) al posteriore (<em>X<sub>max</sub></em>). &bull;
                <strong>Pannello Destro:</strong> Contour 2D reale del <em>C<sub>p</sub></em> sulla sezione trasversale <em>Y-Z</em> corrispondente, con evoluzione della depressione nei canali Venturi ed espansione nel diffusore.
            </p>
        </div>
    </div>
        """

    ai_html_body = _md_to_simple_html(ai_review.get("commentary_markdown", ""))
    stall_color = "#ef233c" if stall_val > 10.0 else ("#f77f00" if stall_val > 4.0 else "#D8EEFC")

    monogram_uri = _brand_monogram_uri()
    monogram_img = (
        f'<img class="brand-mark" src="{monogram_uri}" alt="UniNa Corse" />' if monogram_uri else ""
    )

    html_content = f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Report Diagnostico CFD Verificato - {html.escape(asm_display)}</title>
    <style>
        :root {{
            /* Brand identity UniNa Corse */
            --navy: #11255C;
            --navy-deep: #0B1B47;
            --navy-panel: #163079;
            --violet: #5B2581;
            --violet-soft: #A094C5;
            --gold: #FDEB19;
            --ice: #D8EEFC;
            --danger: #E42320;

            --bg-dark: var(--navy-deep);
            --bg-card: var(--navy);
            --bg-card-alt: var(--navy-panel);
            --text-main: #FFFFFF;
            --text-muted: #7E94B4;
            --accent: var(--gold);
            --border-col: #2A3D6E;

            /* alias storici: gli stili inline esistenti continuano a funzionare */
            --accent-blue: var(--gold);
            --accent-green: var(--ice);
            --accent-amber: var(--gold);
            --accent-red: var(--danger);
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Roboto', 'Roboto Condensed', 'Segoe UI', system-ui, -apple-system, sans-serif;
            background-color: var(--bg-dark);
            color: var(--text-main);
            line-height: 1.6;
            padding: 32px 40px;
            -webkit-font-smoothing: antialiased;
        }}
        .top-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 22px;
            background: var(--bg-card);
            border: none;
            border-radius: 20px;
            padding: 26px 30px;
            margin-bottom: 22px;
        }}
        .brand {{ display: flex; align-items: center; gap: 20px; }}
        .brand-mark {{ height: 48px; width: auto; display: block; }}
        .brand-text h1 {{ font-size: 1.42rem; font-weight: 700; color: #fff; margin-bottom: 5px; }}
        .top-bar .subtitle {{ color: var(--text-muted); font-size: 0.9rem; }}
        .chip-row {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 13px; }}
        .coord-badge, .verified-badge {{
            background: transparent;
            color: var(--ice);
            border: 1px solid rgba(216, 238, 252, 0.28);
            padding: 5px 13px;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 600;
            display: inline-block;
        }}
        .verified-badge {{ color: var(--gold); border-color: rgba(253, 235, 25, 0.45); }}
        .btn-print {{
            background: var(--gold);
            color: var(--navy-deep);
            border: none;
            padding: 12px 24px;
            border-radius: 999px;
            font-weight: 700;
            font-size: 0.9rem;
            cursor: pointer;
            white-space: nowrap;
        }}
        .btn-print:hover {{ background: #FFF06B; }}
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
            gap: 14px;
            margin-bottom: 26px;
        }}
        .kpi-card {{
            background: var(--bg-card);
            border: none;
            border-radius: 16px;
            padding: 18px 22px;
        }}
        .kpi-label {{
            color: var(--text-muted);
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-weight: 700;
        }}
        .kpi-value {{ font-size: 1.85rem; font-weight: 800; margin: 8px 0 3px 0; color: var(--gold); }}
        .kpi-sub {{ font-size: 0.8rem; color: var(--text-muted); }}
        .section-box {{
            background: var(--bg-card);
            border: none;
            border-radius: 20px;
            padding: 26px 30px;
            margin-bottom: 22px;
        }}
        .section-title {{
            font-size: 1.15rem;
            font-weight: 700;
            color: #fff;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 18px;
            padding: 0;
            border-bottom: none;
        }}
        .section-title::before {{
            content: "";
            display: inline-block;
            width: 3px;
            height: 18px;
            background: var(--gold);
            border-radius: 2px;
            margin-right: 12px;
            flex: 0 0 auto;
        }}
        .section-title > span:first-child {{ flex: 1 1 auto; }}
        .section-title > div {{ flex: 0 0 auto; }}
        .section-title button {{ white-space: nowrap; }}
        .section-title .badge {{ margin-left: auto; }}
        .issue-card {{
            background: var(--bg-card-alt);
            border-radius: 16px;
            padding: 20px 24px;
            margin-bottom: 16px;
            border-left: 3px solid var(--gold);
        }}
        .issue-critical {{ border-left-color: var(--danger); }}
        .issue-warning {{ border-left-color: var(--gold); }}
        .issue-info {{ border-left-color: var(--violet-soft); }}
        .issue-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 12px;
        }}
        .badge {{
            padding: 3px 11px;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 800;
            margin-right: 8px;
            letter-spacing: 0.03em;
            border: 1px solid transparent;
        }}
        .badge-critical {{ background: rgba(228, 35, 32, 0.16); color: #FF7A76; border-color: rgba(228, 35, 32, 0.45); }}
        .badge-warning  {{ background: rgba(253, 235, 25, 0.14); color: var(--gold); border-color: rgba(253, 235, 25, 0.40); }}
        .badge-info     {{ background: rgba(160, 148, 197, 0.18); color: var(--violet-soft); border-color: rgba(160, 148, 197, 0.40); }}
        .issue-id {{ color: var(--text-muted); font-family: 'Roboto Condensed', ui-monospace, monospace; font-size: 0.82rem; }}
        .issue-title {{ display: inline; font-size: 1.05rem; margin-left: 8px; color: #fff; font-weight: 700; }}
        .issue-loc {{
            background: var(--navy-deep);
            padding: 6px 14px;
            border-radius: 999px;
            font-size: 0.8rem;
            color: var(--ice);
            font-family: 'Roboto Condensed', ui-monospace, monospace;
            display: inline-block;
        }}
        .issue-body p {{ margin-bottom: 10px; font-size: 0.93rem; }}
        .highlight-ref {{ color: var(--gold); font-weight: 600; }}
        .impact-text {{ color: #FF9A9A; font-weight: 600; }}
        .cad-actions-box {{
            background: rgba(11, 27, 71, 0.55);
            border: 1px solid var(--border-col);
            border-radius: 12px;
            padding: 14px 18px;
            margin-top: 12px;
        }}
        .cad-actions-box ul {{ margin-left: 20px; margin-top: 8px; }}
        .cad-actions-box li {{ margin-bottom: 6px; color: var(--ice); }}
        .photo-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(560px, 1fr));
            gap: 20px;
        }}
        .photo-card {{
            background: var(--bg-card-alt);
            border: none;
            border-radius: 16px;
            overflow: hidden;
        }}
        .photo-header {{
            padding: 14px 18px;
            background: rgba(11, 27, 71, 0.45);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
        }}
        .cat-pill {{
            font-size: 0.68rem;
            background: rgba(253, 235, 25, 0.12);
            color: var(--gold);
            padding: 2px 9px;
            border-radius: 999px;
            font-weight: 700;
            display: inline-block;
            margin-bottom: 4px;
            letter-spacing: 0.04em;
        }}
        .photo-controls {{ display: flex; gap: 6px; }}
        .btn-toggle {{
            background: transparent;
            color: var(--text-muted);
            border: 1px solid var(--border-col);
            padding: 5px 12px;
            border-radius: 999px;
            cursor: pointer;
            font-size: 0.76rem;
            font-weight: 600;
        }}
        .btn-toggle.active {{
            background: var(--gold);
            color: var(--navy-deep);
            border-color: var(--gold);
        }}
        .photo-img-wrapper {{
            background: var(--navy-deep);
            text-align: center;
            border-bottom: none;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 10px;
            min-height: 260px;
        }}
        .photo-img-wrapper img {{
            max-width: 100%;
            max-height: 540px;
            width: auto;
            height: auto;
            object-fit: contain;
            display: block;
            margin: 0 auto;
            border-radius: 8px;
        }}
        .photo-footer {{ padding: 14px 18px; }}
        .photo-desc {{ font-size: 0.86rem; color: var(--ice); margin-bottom: 8px; }}
        .photo-findings {{ margin-left: 18px; font-size: 0.84rem; color: var(--gold); }}
        .plot-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(560px, 1fr));
            gap: 20px;
        }}
        .plot-card {{
            background: var(--bg-card-alt);
            border: none;
            border-radius: 16px;
            padding: 16px;
        }}
        .plot-card h4 {{ margin-bottom: 10px; color: #fff; font-size: 0.98rem; }}
        .plot-card img {{ width: 100%; border-radius: 10px; background: white; margin-bottom: 10px; }}
        .plot-card p {{ font-size: 0.86rem; color: var(--text-muted); }}
        .ai-review-content h3.ai-subtitle {{ color: var(--gold); margin: 18px 0 10px 0; font-size: 1.05rem; }}
        .ai-review-content ul.ai-list {{ margin-left: 22px; margin-bottom: 14px; }}
        .ai-review-content li {{ margin-bottom: 8px; }}
        .inline-code {{
            background: var(--navy-deep);
            color: var(--ice);
            padding: 2px 7px;
            border-radius: 6px;
            font-family: 'Roboto Condensed', ui-monospace, monospace;
            font-size: 0.86rem;
        }}
        .section-divider {{ border: none; border-top: 1px solid var(--border-col); margin: 18px 0; }}
        .meta-info-table {{ width: 100%; border-collapse: separate; border-spacing: 0; font-size: 0.86rem; margin-top: 8px; }}
        .meta-info-table th {{
            background: transparent;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.07em;
            font-size: 0.7rem;
            font-weight: 700;
            padding: 10px 12px;
            text-align: left;
            border-bottom: 1px solid var(--border-col);
        }}
        .meta-info-table td {{
            padding: 11px 12px;
            text-align: left;
            border-bottom: 1px solid rgba(42, 61, 110, 0.55);
            color: var(--ice);
            vertical-align: top;
        }}
        .meta-info-table tbody tr:hover td {{ background: rgba(22, 48, 121, 0.35); }}
        code {{ font-family: 'Roboto Condensed', ui-monospace, monospace; color: var(--gold); }}
        @media print {{
            body {{ background: #fff; color: #111; padding: 10px; }}
            .btn-print, .photo-controls {{ display: none; }}
            .section-box, .kpi-card, .issue-card, .photo-card, .plot-card {{
                background: #fff; color: #111; border: 1px solid #ccc; page-break-inside: avoid;
            }}
            .kpi-value, .highlight-ref, code {{ color: #6B5B00; }}
        }}
    </style>
</head>
<body>

    <div class="top-bar">
        <div class="brand">
            {monogram_img}
            <div class="brand-text">
                <h1>Dossier Diagnostico CFD</h1>
                <div class="subtitle">Assieme: <strong>{html.escape(asm_display)}</strong> &middot; generato il {now_str} &middot; <code>{html.escape(os.path.basename(cas_file))}</code></div>
                <div class="chip-row">
                    <span class="coord-badge">X = Longitudinale &middot; Y = Verticale &middot; Z = Laterale (Z=0 simmetria)</span>
                    <span class="verified-badge">&#10003; {pdata.get('nodes_read', 0):,} nodi &amp; {pdata.get('faces_read', 0):,} facce reali verificate</span>
                    <span class="coord-badge">{force_note}</span>
                    <span class="coord-badge">dato viscoso: {visc_source}</span>
                </div>
            </div>
        </div>
        <div>
            <button class="btn-print" onclick="window.print()">Stampa / Salva PDF</button>
        </div>
    </div>

    <!-- KPI DASHBOARD -->
    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-label">Deportanza Totale</div>
            <div class="kpi-value">{df_n:.0f} N</div>
            <div class="kpi-sub">CL&middot;A = <strong>{cl_a:.3f} m&sup2;</strong> &middot; lift Fluent = {lift_n:.1f} N<br/>{'2x Half-Car' if is_sym else 'Full-Car'}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Resistenza Totale (Drag)</div>
            <div class="kpi-value" style="color:#FF7A76;">{drag_n:.0f} N</div>
            <div class="kpi-sub">CD&middot;A = <strong>{cd_a:.3f} m&sup2;</strong> &middot; pressione + viscosa</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Efficienza Aerodinamica (|L|/D)</div>
            <div class="kpi-value" style="color: #D8EEFC;">{l_d:.2f}</div>
            <div class="kpi-sub">Rapporto |deportanza| / resistenza sull'assieme</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Centro di Pressione (X_CoP)</div>
            <div class="kpi-value">{cop_pct:.1f}% L</div>
            <div class="kpi-sub">Coordinata X = <strong>{cop_x:.3f} m</strong>{cop_wb_html}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Area con Tau_w,x &le; 0 (Stallo)</div>
            <div class="kpi-value" style="color: {stall_color};">{stall_val:.2f}%</div>
            <div class="kpi-sub">Calcolata sui triangoli reali dell'assieme</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Picco Aspirazione (Cp_min)</div>
            <div class="kpi-value">{cp_min:.2f}</div>
            <div class="kpi-sub">Raggiunto a X = {cp_min_x:.1f}% L</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Simmetria Modello (Z=0)</div>
            <div class="kpi-value">{'0.00%' if is_sym else f'{asym_val:.2f}%'}</div>
            <div class="kpi-sub">{'Half-Car Simmetrico (Symmetry BC)' if is_sym else 'Modello Full-Car'}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Indice Coerenza Flusso</div>
            <div class="kpi-value" style="color: #FDEB19;">{vortex_stab:.1f}%</div>
            <div class="kpi-sub">Frazione superficie con flusso attaccato</div>
        </div>
    </div>

    <!-- SEZIONE 0: AUDIT DI VERIFICA RIGOROSA DATI E IMMAGINI -->
    <div class="section-box">
        <div class="section-title">
            <span>0. Audit di Verifica Rigorosa Dati CFD (.CAS/.DAT) e Controllo Anti-Artefatti</span>
            <span class="badge badge-info">{html.escape(ver_rep.get('overall_status', 'VERIFIED_REAL_DATA'))}</span>
        </div>
        <table class="meta-info-table">
            <thead>
                <tr>
                    <th>ID Check</th>
                    <th>Controllo di Verifica</th>
                    <th>Esito</th>
                    <th>Valore Misurato</th>
                    <th>Dettagli Tecnici</th>
                </tr>
            </thead>
            <tbody>
                {"".join(ver_rows_html)}
            </tbody>
        </table>
    </div>

    <!-- SEZIONE 1: TABELLA QUANTITATIVA PER SINGOLO PID -->
    <div class="section-box">
        <div class="section-title">
            <span>1. Riparto Quantitativo Reale per Singolo Componente / PID ({html.escape(asm_display)}) - Valori Full-Car (x2)</span>
            <div style="display:flex; align-items:center; gap:12px;">
                <span style="font-size: 0.88rem; color: var(--text-muted);">{len(pid_breakdown)} PID unificate</span>
                <button onclick="exportPidExcel()" style="background: transparent; color: var(--gold); border: 1px solid rgba(253,235,25,0.45); padding: 8px 18px; border-radius: 999px; font-weight: 700; font-size: 0.85rem; cursor: pointer;">
                    Esporta tabella in Excel (.xlsx) &middot; valori x2
                </button>
            </div>
        </div>
        <table class="meta-info-table">
            <thead>
                <tr>
                    <th>PID (Componente)</th>
                    <th>Downforce [N] (x2)</th>
                    <th>Drag Totale [N] (x2)<br/><span style="font-size:0.74rem; font-weight:normal; opacity:0.8;">(Pressione + Viscosa)</span></th>
                    <th>Efficienza (L/D)</th>
                    <th>Facce 3D</th>
                    <th>Area Totale (x2)</th>
                    <th>Cp_min</th>
                    <th>Cp_mean</th>
                    <th>Stallo (&tau;<sub>w,x</sub>&le;0)</th>
                    <th>Bounding Box Reale [m]</th>
                </tr>
            </thead>
            <tbody>
                {"".join(pid_rows_html)}
            </tbody>
        </table>
    </div>

    <!-- SEZIONE 2: PROBLEMATICHE DEL DESIGN E SOLUZIONI CAD -->
    <div class="section-box">
        <div class="section-title">
            <span>2. Problematiche del Design Misurate sui Componenti &amp; Azioni Correttive CAD</span>
            <span style="font-size: 0.9rem; color: var(--text-muted);">{len(design_issues)} punti diagnostici</span>
        </div>
        {"".join(issue_cards_html)}
    </div>

    <!-- SEZIONE 3: PERIZIA TECNICA SUI DATI REALI -->
    <div class="section-box">
        <div class="section-title">
            <span>3. Relazione Tecnica Aerodinamica sui Dati Estratti</span>
            <span style="font-size: 0.85rem; color: var(--accent-blue);">Fonte: {html.escape(ai_review.get('source', ''))}</span>
        </div>
        <div class="ai-review-content">
            {ai_html_body}
        </div>
    </div>

    <!-- SEZIONE 4: GRAFICI INGEGNERISTICI QUANTITATIVI -->
    <div class="section-box">
        <div class="section-title">
            <span>4. Grafici Aerodinamici Quantitativi (Per Singolo PID &bull; Asse X &bull; Asse Z)</span>
        </div>
        <div class="plot-grid">
            {"".join(plot_cards_html)}
        </div>
    </div>

    {xcut_gif_section_html}

    <!-- SEZIONE 5: GALLERIA DIAGNOSTICA MAPPE E SEZIONI -->
    <div class="section-box">
        <div class="section-title">
            <span>5. Mappe Superficiali, Sezioni e Streamlines 3D (.CAS/.DAT &amp; META Post)</span>
            <span style="font-size: 0.85rem; color: var(--text-muted);">Usa i pulsanti per alternare Vista Annotata vs Vista Pulita</span>
        </div>
        <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:18px;">
            <button class="btn-toggle active" onclick="filterGallery('all', this)">Tutte le Viste</button>
            <button class="btn-toggle" onclick="filterGallery('streamlines', this)">Streamlines 3D (5 Prospettive)</button>
            <button class="btn-toggle" onclick="filterGallery('surface_pressure', this)">Mappe Cp / Pressione</button>
            <button class="btn-toggle" onclick="filterGallery('flow_separation', this)">Separazione / Wall Shear</button>
            <button class="btn-toggle" onclick="filterGallery('turbulence_mesh', this)">Turbolenza (TKE)</button>
            <button class="btn-toggle" onclick="filterGallery('x_cut_total_pressure', this)">Sezioni Trasversali X-Cuts (10 Piani)</button>
            <button class="btn-toggle" onclick="filterGallery('z_cut_longitudinal', this)">Piani Cp a diverse Z (10 Piani)</button>
        </div>
        <div class="photo-grid">
            {"".join(photo_cards_html)}
        </div>
    </div>

    <!-- SEZIONE 6: DETTAGLI TECNICI FILE .CAS / .DAT E SESSIONE META -->
    <div class="section-box">
        <div class="section-title">
            <span>6. Riferimenti File Binari ANSYS Fluent (.cas / .dat) &amp; Sessione BETA CAE META Post</span>
        </div>
        <table class="meta-info-table">
            <tr><th>File Geometria (.cas)</th><td><code>{html.escape(str(cas_file))}</code></td></tr>
            <tr><th>File Risultati (.dat)</th><td><code>{html.escape(str(dat_file))}</code></td></tr>
            <tr><th>Session File Batch META Post (.ses)</th><td><code>{html.escape(str(ses_file))}</code></td></tr>
            <tr><th>Session File Interattivo META Post (.ses)</th><td><code>{html.escape(str(session_bundle.get('interactive_ses_path', '')))}</code></td></tr>
            <tr><th>Eseguibile BETA CAE META Post Rilevato</th><td><code>{html.escape(str(session_bundle.get('meta_executable', '')))}</code></td></tr>
            <tr><th>Bounding Box Reale Assieme [m]</th><td>X = [{bbox.get('xmin', 0):.3f}, {bbox.get('xmax', 0):.3f}] m &bull; Y = [{bbox.get('ymin', 0):.3f}, {bbox.get('ymax', 0):.3f}] m &bull; Z = [{bbox.get('zmin', 0):.3f}, {bbox.get('zmax', 0):.3f}] m</td></tr>
        </table>
    </div>

    <!-- LIGHTBOX MODAL PER ZOOM IMMAGINI STANDALONE -->
    <div id="lightboxModal" onclick="closeLightbox()" style="display:none; position:fixed; z-index:9999; left:0; top:0; width:100%; height:100%; background:rgba(15,23,42,0.92); align-items:center; justify-content:center; flex-direction:column; padding:24px; cursor:zoom-out;">
        <div id="lightboxCaption" style="color:#f8fafc; font-size:1.05rem; font-weight:700; margin-bottom:12px; text-align:center;"></div>
        <img id="lightboxImg" src="" alt="" style="max-width:95vw; max-height:85vh; border-radius:8px; border:2px solid #FDEB19; box-shadow:0 12px 40px rgba(0,0,0,0.7);"/>
        <div style="color:#7E94B4; font-size:0.85rem; margin-top:10px;">Clicca ovunque per chiudere lo zoom</div>
    </div>

    <script>
        var PID_XLSX_B64 = "{xlsx_b64_payload}";

        function exportPidExcel() {{
            if (!PID_XLSX_B64) return;
            var binStr = atob(PID_XLSX_B64);
            var len = binStr.length;
            var bytes = new Uint8Array(len);
            for (var i = 0; i < len; i++) {{
                bytes[i] = binStr.charCodeAt(i);
            }}
            var blob = new Blob([bytes], {{ type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }});
            var url = URL.createObjectURL(blob);
            var a = document.createElement("a");
            a.href = url;
            a.download = "Tabella_PID_Aerodinamica_2x.xlsx";
            document.body.appendChild(a);
            a.click();
            setTimeout(function() {{
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }}, 150);
        }}

        function switchImg(imgId, mode, btnElem) {{
            var img = document.getElementById(imgId);
            if (img) {{
                var targetUri = img.getAttribute('data-' + mode);
                if (targetUri) img.src = targetUri;
            }}
            var parent = btnElem.parentElement;
            var buttons = parent.getElementsByTagName('button');
            for (var i = 0; i < buttons.length; i++) {{
                buttons[i].classList.remove('active');
            }}
            btnElem.classList.add('active');
        }}

        function filterGallery(cat, btnElem) {{
            var cards = document.querySelectorAll('.photo-card');
            cards.forEach(function(card) {{
                var cardCat = card.getAttribute('data-category') || '';
                if (cat === 'all') {{
                    card.style.display = '';
                }} else if (cat === 'sections') {{
                    if (cardCat.indexOf('cut') !== -1) {{
                        card.style.display = '';
                    }} else {{
                        card.style.display = 'none';
                    }}
                }} else if (cardCat === cat || (cat === 'streamlines' && cardCat.indexOf('streamline') !== -1)) {{
                    card.style.display = '';
                }} else {{
                    card.style.display = 'none';
                }}
            }});
            var parent = btnElem.parentElement;
            var buttons = parent.getElementsByTagName('button');
            for (var i = 0; i < buttons.length; i++) {{
                buttons[i].classList.remove('active');
            }}
            btnElem.classList.add('active');
        }}

        function openLightbox(srcUri, captionText) {{
            var modal = document.getElementById('lightboxModal');
            var mImg = document.getElementById('lightboxImg');
            var mCap = document.getElementById('lightboxCaption');
            if (modal && mImg) {{
                mImg.src = srcUri;
                if (mCap) mCap.textContent = captionText || '';
                modal.style.display = 'flex';
            }}
        }}

        function closeLightbox() {{
            var modal = document.getElementById('lightboxModal');
            if (modal) modal.style.display = 'none';
        }}
    </script>
</body>
</html>
"""

    html_report_path = os.path.join(output_dir, "CFD_Aero_Diagnostic_Report.html")
    with open(html_report_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    # Salva la copia standalone direttamente nella cartella in cui si trovano i file .cas e .dat
    cas_dir = os.path.dirname(os.path.abspath(cas_file)) if cas_file else os.path.dirname(os.path.abspath(output_dir))
    cas_stem = os.path.splitext(os.path.basename(cas_file))[0] if cas_file else "CFD"
    standalone_root_path = os.path.join(cas_dir, f"Report_CFD_{cas_stem}_{assembly_type}.html")
    try:
        with open(standalone_root_path, "w", encoding="utf-8") as f:
            f.write(html_content)
    except Exception:
        standalone_root_path = html_report_path

    # Report Markdown
    md_lines = [
        f"# Dossier Diagnostico CFD Verificato - {asm_display}",
        f"**Data:** {now_str} | **File:** `{os.path.basename(cas_file)}` & `{os.path.basename(dat_file)}`",
        f"**Nodi 3D letti:** `{pdata.get('nodes_read', 0):,}` | **Facce 3D lette:** `{pdata.get('faces_read', 0):,}` | **Half-Car Simmetrico:** `{is_sym}`",
        "",
        "## Riepilogo KPI Aerodinamici Verificati",
        f"- **Deportanza totale:** `{df_n:.1f} N` ($C_L \\cdot A$ = `{cl_a:.3f} m²`, lift Fluent = `{lift_n:.1f} N`)",
        f"- **Resistenza totale (drag):** `{drag_n:.1f} N` ($C_D \\cdot A$ = `{cd_a:.3f} m²`)",
        f"- **Efficienza ($L/D$):** `{l_d:.2f}`",
        f"- **Centro di Pressione ($X_{{\\text{{CoP}}}}$):** `{cop_pct:.1f}% L` (`X = {cop_x:.3f} m`)",
        f"- **Superficie con $\\tau_{{w,x}} \\le 0$ (Stallo):** `{stall_val:.2f}%`",
        "",
        "## Tabella Per Singolo PID",
        "| PID | Nome Zona | Facce | Area [m²] | Deportanza -Fy [N] | Drag Fx [N] | Cp_min | Cp_mean | Stallo [%] |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for p in sorted(pid_breakdown, key=lambda x: x.get("fy_N", 0.0)):
        md_lines.append(
            f"| {p['zone_id']} | `{p['zone_name']}` | {p['n_faces']:,} | {p['area_m2']:.4f} | {-p['fy_N']:.1f} | {p['fx_N']:.1f} | {p['cp_min']:.2f} | {p['cp_mean']:.2f} | {p['stalled_area_pct']:.2f}% |"
        )
    md_lines.extend(["", "## Problematiche del Design Rilevate"])
    for iss in design_issues:
        md_lines.extend([
            f"### [{iss['severity']}] {iss['id']} - {iss['title']}",
            f"- **Posizione Reale (X, Y, Z):** `{iss['location_xyz']}`",
            f"- **Evidenza Visiva:** {iss['visual_evidence']}",
            f"- **Causa Radice:** {iss['root_cause']}",
            f"- **Impatto Quantificato:** {iss['quantified_impact']}",
            "- **Azioni di Riprogettazione CAD:**",
        ])
        for act in iss.get("cad_redesign_actions", []):
            md_lines.append(f"  - {act}")
        md_lines.append("")

    md_lines.extend([
        "## Relazione Tecnica Aerodinamica",
        ai_review.get("commentary_markdown", "")
    ])

    md_report_path = os.path.join(output_dir, "CFD_Aero_Diagnostic_Report.md")
    with open(md_report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    return {
        "html_report": html_report_path,
        "standalone_html_report": standalone_root_path,
        "markdown_report": md_report_path
    }
