# -*- coding: utf-8 -*-
"""
Modulo AI Vision Chief Aerodynamicist Verificato (ai_vision_advisor.py).
Costruisce la perizia ingegneristica basandosi esclusivamente sui dati reali estratti
dal file .cas e .dat (nodi, triangoli, integrali per singolo PID, condizione di simmetria)
e sulle immagini verificate.
"""

import base64
import io
import json
import os
import urllib.error
import urllib.request

# DeepSeek espone un endpoint compatibile con le Chat Completions di OpenAI sia
# per il testo sia per le immagini. Il modello con vision e' `deepseek-flash`
# (nome commerciale DeepSeek-V4.1-Flash); il thinking mode si controlla con
# `reasoning_effort` e con il blocco `thinking`.
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-flash"
DEEPSEEK_EFFORTS = ("low", "high", "max")
AI_PROVIDERS = ("gemini", "openai", "deepseek")

# MIME dichiarato nell'URL inline: DeepSeek riconosce comunque il formato dal
# contenuto, ma un MIME coerente evita ambiguita' nei proxy.
def _tiny_png_bytes() -> bytes:
    """
    PNG 1x1 nero **valido**, costruito a runtime (struct + zlib, nessun file).

    La versione precedente incorporava una stringa base64 scritta a mano che era
    corrotta: il server la rifiutava e la prova vision avrebbe dato un falso
    negativo ("il modello non accetta immagini"). Costruirlo e' verificabile.
    """
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)   # 1x1, 8 bit, RGB
    idat = zlib.compress(b"\x00" + b"\x00\x00\x00", 9)   # filtro 0 + pixel nero
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat)
            + chunk(b"IEND", b""))


# PNG 1x1 usato dalla prova vision di `deepseek_check`.
_TINY_PNG_B64 = base64.b64encode(_tiny_png_bytes()).decode("ascii")

# Limite di sicurezza per lato delle immagini inviate all'AI.
# DeepSeek rifiuta con HTTP 400 sopra 8192 px per lato (e 4096 se la richiesta
# contiene 15+ immagini): alcune nostre viste possono sforare, quindi si
# ridimensionano prima dell'invio.
MAX_VISION_IMAGE_SIDE = 4096

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _ai_status(mode: str, provider: str = "", reason: str = "", model: str = "") -> dict:
    """
    Stato della perizia AI: chi l'ha prodotta e, se e' il motore locale, perche'.

    Serve al report: senza questo campo il lettore vede solo "Fonte: motore
    esperto" e non sa se l'AI e' disattivata, senza chiave o in errore.
    """
    return {"mode": mode, "provider": provider, "model": model, "reason": reason}


def _short_error(exc) -> str:
    """Messaggio d'errore compatto per il report (senza stack)."""
    text = str(exc) or type(exc).__name__
    text = text.replace("\n", " ").strip()
    return text[:140]


def _read_http_error(exc) -> str:
    """Corpo della risposta d'errore (contiene il motivo vero del rifiuto)."""
    try:
        raw = exc.read().decode("utf-8", "ignore")
    except Exception:
        return ""
    return " ".join(raw.split())[:300]


def normalize_image_bytes(path: str):
    """
    Byte e MIME di un'immagine pronta per l'invio all'AI.

    Se Pillow è disponibile: si converte in RGB e si riduce entro
    `MAX_VISION_IMAGE_SIDE` per lato (il server rifiuta le immagini troppo
    grandi con "unsupported image"). Solleva se il file non è un'immagine
    leggibile: il chiamante lo salta invece di far fallire tutta la richiesta.
    """
    try:
        from PIL import Image
    except Exception:
        # Senza Pillow si inviano i byte originali con il MIME dedotto.
        mime = _IMAGE_MIME.get(os.path.splitext(str(path))[1].lower(), "image/png")
        with open(path, "rb") as handle:
            return handle.read(), mime

    with Image.open(path) as image:
        image.load()
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        width, height = image.size
        longest = max(width, height)
        if longest > MAX_VISION_IMAGE_SIDE:
            scale = MAX_VISION_IMAGE_SIDE / float(longest)
            image = image.resize(
                (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
                Image.LANCZOS,
            )
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue(), "image/png"


def image_data_url(path: str) -> str:
    """Immagine locale come data-URL base64 (formato richiesto da DeepSeek/OpenAI)."""
    data, mime = normalize_image_bytes(path)
    return "data:%s;base64,%s" % (mime, base64.b64encode(data).decode("ascii"))


def build_deepseek_payload(ai_cfg: dict, prompt: str, image_paths,
                           max_total_bytes: int = 24 * 1024 * 1024) -> dict:
    """
    Body della richiesta DeepSeek: testo + immagini + thinking mode.

    Riferimenti (api-docs.deepseek.com): il thinking e' attivo di default con
    effort `high`; `reasoning_effort` accetta low/high/max e `thinking` accetta
    {"type": "enabled" | "disabled"}. In thinking mode temperatura e penalty
    sono ignorate, quindi non vengono inviate.
    """
    blocks = [{"type": "text", "text": prompt}]
    total = 0
    skipped = 0
    unreadable = 0
    for path in image_paths or []:
        try:
            url = image_data_url(path)
        except Exception as exc:
            # Un file illeggibile farebbe fallire tutta la richiesta (HTTP 400):
            # meglio una perizia con le immagini buone che nessuna.
            unreadable += 1
            print("[INFO] DeepSeek: immagine scartata (%s): %s"
                  % (os.path.basename(str(path)), _short_error(exc)))
            continue
        # DeepSeek rifiuta (HTTP 400) le richieste oltre 48 MiB: restiamo larghi
        # e scartiamo le immagini in eccesso invece di far fallire tutto.
        if total + len(url) > max_total_bytes:
            skipped += 1
            continue
        total += len(url)
        blocks.append({"type": "image_url", "image_url": {"url": url}})
    if skipped:
        print("[INFO] DeepSeek: %d immagini escluse per non superare il limite di richiesta." % skipped)
    if unreadable:
        print("[INFO] DeepSeek: %d immagini illeggibili non inviate." % unreadable)

    effort = str(ai_cfg.get("deepseek_reasoning_effort", "high") or "high").strip().lower()
    if effort not in DEEPSEEK_EFFORTS:
        effort = "high"
    thinking_enabled = bool(ai_cfg.get("deepseek_thinking", True))

    payload = {
        "model": str(ai_cfg.get("model_deepseek") or DEEPSEEK_DEFAULT_MODEL),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_AERO},
            {"role": "user", "content": blocks},
        ],
        "stream": False,
        "thinking": {"type": "enabled" if thinking_enabled else "disabled"},
    }
    if thinking_enabled:
        payload["reasoning_effort"] = effort
    return payload


def extract_deepseek_answer(response_json: dict):
    """(testo, ragionamento) dalla risposta Chat Completions di DeepSeek."""
    choices = response_json.get("choices") or []
    if not choices:
        return "", ""
    message = choices[0].get("message") or {}
    return (message.get("content") or "", message.get("reasoning_content") or "")


def _deepseek_http(method: str, path: str, api_key: str, body: dict = None, timeout: int = 120):
    url = DEEPSEEK_BASE_URL + path
    data = None
    headers = {
        "Authorization": "Bearer " + api_key,
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def deepseek_available_models(api_key: str) -> list:
    """
    Id dei modelli utilizzabili con questa chiave (GET /models).

    Serve solo a rendere leggibile l'errore quando il nome modello e' sbagliato:
    non fa fallire nulla se la chiamata non riesce.
    """
    try:
        payload = _deepseek_http("GET", "/models", api_key, None, timeout=20)
        return [str(item.get("id")) for item in (payload.get("data") or []) if item.get("id")]
    except Exception:
        return []


def deepseek_check(ai_cfg: dict) -> dict:
    """
    Diagnostica della configurazione DeepSeek: chiave, modelli, chiamata minima.

    Serve a rispondere a "perche' HTTP 400?": riporta l'elenco dei modelli
    disponibili per la chiave e il messaggio esatto del server, sia con thinking
    attivo sia senza (per capire se e' il payload o il modello).
    """
    key = str(ai_cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    model = str(ai_cfg.get("model_deepseek") or DEEPSEEK_DEFAULT_MODEL)
    info = {
        "base_url": DEEPSEEK_BASE_URL,
        "modalities": [],
        "vision_supported": None,
        "model": model,
        "key_present": bool(key),
        "key_masked": (key[:4] + "..." + key[-4:]) if len(key) > 8 else ("***" if key else ""),
        "models": [],
        "models_error": "",
        "model_available": None,
        "text_call": "",
        "thinking_call": "",
        "vision_probe": "",
    }
    if not key:
        return info

    try:
        payload = _deepseek_http("GET", "/models", key, None, timeout=20)
        entries = payload.get("data") or []
        info["models"] = [str(item.get("id")) for item in entries if item.get("id")]
        info["model_available"] = model in info["models"] if info["models"] else None
        for item in entries:
            if str(item.get("id")) == model:
                modalities = item.get("input_modalities")
                if isinstance(modalities, list):
                    info["modalities"] = [str(m) for m in modalities]
                    info["vision_supported"] = "image" in info["modalities"]
                break
    except urllib.error.HTTPError as exc:
        info["models_error"] = "HTTP %s: %s" % (exc.code, _read_http_error(exc))
    except Exception as exc:
        info["models_error"] = "%s: %s" % (type(exc).__name__, _short_error(exc))
    if info["models_error"]:
        return info

    base_body = {
        "model": model,
        "messages": [{"role": "user", "content": "Rispondi solo con: OK"}],
        "stream": False,
    }
    for label, extra in (
        ("thinking_call", {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}),
        ("text_call", {"thinking": {"type": "disabled"}}),
    ):
        body = dict(base_body)
        body.update(extra)
        try:
            answer = _deepseek_http("POST", "/chat/completions", key, body, timeout=90)
            text, _reasoning = extract_deepseek_answer(answer)
            info[label] = "ok" + (" (content: %s)" % text[:40] if text else " (senza testo)")
            break
        except urllib.error.HTTPError as exc:
            info[label] = "HTTP %s: %s" % (exc.code, _read_http_error(exc))
        except Exception as exc:
            info[label] = "%s: %s" % (type(exc).__name__, _short_error(exc))

    # Prova vision: un 1x1 PNG in linea. Se questo fallisce con 400, il modello
    # della chiave non accetta immagini (ed e' la ragione del "solo testo").
    vision_body = {
        "model": model,
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "Quanti pixel ha questa immagine? Rispondi in una riga."},
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64," + _TINY_PNG_B64}},
            ]},
        ],
        "stream": False,
        "thinking": {"type": "disabled"},
    }
    try:
        answer = _deepseek_http("POST", "/chat/completions", key, vision_body, timeout=90)
        text, _reasoning = extract_deepseek_answer(answer)
        info["vision_probe"] = "ok" + (" (content: %s)" % text[:40] if text else " (senza testo)")
        if info["vision_supported"] is None:
            info["vision_supported"] = True
    except urllib.error.HTTPError as exc:
        info["vision_probe"] = "HTTP %s: %s" % (exc.code, _read_http_error(exc))
        if exc.code == 400:
            info["vision_supported"] = False
    except Exception as exc:
        info["vision_probe"] = "%s: %s" % (type(exc).__name__, _short_error(exc))
    return info


def deepseek_ask(api_key: str, payload: dict) -> dict:
    """POST /chat/completions con il body gia' costruito."""
    return _deepseek_http("POST", "/chat/completions", api_key, payload)


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
    provider = (ai_cfg.get("provider") or "gemini").strip().lower()
    if provider not in AI_PROVIDERS:
        print("[INFO] Provider AI '%s' non riconosciuto: uso 'gemini'." % provider)
        provider = "gemini"
    local_reason = ""
    api_key = (
        ai_cfg.get("api_key")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
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
                        "commentary_markdown": resp.text,
                        "ai_status": _ai_status("ai", "gemini", "",
                                                ai_cfg.get("model_gemini", "gemini-3.8-flash")),
                    }
            except Exception as exc:
                local_reason = "Gemini non ha risposto (%s)." % _short_error(exc)
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
                    "commentary_markdown": resp.choices[0].message.content,
                    "ai_status": _ai_status("ai", "openai", "",
                                            ai_cfg.get("model_openai", "gpt-4o")),
                }
            except Exception as exc:
                local_reason = "OpenAI non ha risposto (%s)." % _short_error(exc)
                print(f"[INFO] Chiamata API OpenAI Vision non completata ({exc}). Uso sintetizzatore dati reali.")

        elif provider == "deepseek":
            # Fonte: api-docs.deepseek.com (chat completions compatibile OpenAI,
            # vision con image_url data-URL, thinking mode con reasoning_effort).
            payload = None
            degraded_text_only = False
            try:
                payload = build_deepseek_payload(ai_cfg, user_context, selected_image_paths[:4])
                try:
                    body = deepseek_ask(api_key, payload)
                except urllib.error.HTTPError as exc:
                    # Se il rifiuto riguarda le immagini (o il payload in generale),
                    # riprova una volta senza immagini: meglio una perizia solo testo
                    # che nessuna perizia.
                    has_images = len(payload["messages"][1]["content"]) > 1
                    if exc.code != 400 or not has_images:
                        raise
                    print("[INFO] DeepSeek ha rifiutato la richiesta con immagini (HTTP 400): "
                          "riprovo senza immagini.")
                    payload = build_deepseek_payload(ai_cfg, user_context, [])
                    body = deepseek_ask(api_key, payload)
                    degraded_text_only = True
                text, reasoning = extract_deepseek_answer(body)
                if text:
                    effort = payload.get("reasoning_effort")
                    label = payload["model"]
                    if effort:
                        label += ", thinking " + str(effort)
                    if degraded_text_only:
                        label += ", solo testo (immagini rifiutate)"
                    if reasoning:
                        print("[INFO] DeepSeek thinking: %d caratteri di ragionamento." % len(reasoning))
                    return {
                        "source": "DeepSeek Vision (%s)" % label,
                        "commentary_markdown": text,
                        "ai_status": _ai_status("ai", "deepseek", "", payload["model"]),
                    }
                local_reason = "DeepSeek ha risposto senza testo utile."
                print("[INFO] DeepSeek non ha restituito testo utile. Uso sintetizzatore dati reali.")
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", "ignore")[:300]
                except Exception:
                    detail = ""
                hint = ""
                if exc.code in (400, 404):
                    models = deepseek_available_models(api_key)
                    if models:
                        hint = " Modelli disponibili: " + ", ".join(models[:8]) + "."
                model = (payload or {}).get("model", DEEPSEEK_DEFAULT_MODEL)
                local_reason = "DeepSeek ha risposto HTTP %s (modello '%s')" % (exc.code, model)
                server_detail = " ".join(detail.split())
                if server_detail:
                    local_reason += ": " + server_detail
                else:
                    local_reason += ": nessun dettaglio dal server."
                print(f"[INFO] DeepSeek API non completata (HTTP {exc.code}, modello '{model}').{hint} "
                      f"Dettaglio: {detail}")
            except Exception as exc:
                local_reason = "DeepSeek non ha risposto (%s)." % _short_error(exc)
                print(f"[INFO] Chiamata API DeepSeek non completata ({exc}). Uso sintetizzatore dati reali.")

    if not local_reason:
        if not ai_cfg.get("enabled", True):
            local_reason = "AI Vision disattivata nel config (ai_vision.enabled = false)."
        elif not api_key:
            local_reason = ("Nessuna API key configurata per il provider '%s': la perizia viene dal "
                            "motore esperto locale." % provider)
        else:
            local_reason = "AI Vision non disponibile: perizia dal motore esperto locale."

    return {
        "source": "Motore Diagnostico Verificato su Dati Binari .CAS/.DAT & Mesh 3D Reale",
        "commentary_markdown": _build_local_expert_review(session_bundle, cv_results, design_issues),
        "ai_status": _ai_status("local", provider, local_reason),
    }
