# -*- coding: utf-8 -*-
"""
Interfaccia Grafica Desktop (gui_app.py) per il Post-Processing CFD
& Diagnostica Design con BETA CAE META Post v25.1+.

UI moderna in Tkinter puro (nessuna dipendenza aggiuntiva):
  - Tema scuro "deep space" con accenti ciano/indaco
  - Pulsanti a gradiente e widget arrotondati disegnati su Canvas
  - Pannello configurazione scorrevole + console di esecuzione con tag colorati
  - Riepilogo file .cas/.dat, PID isolati e stato META Post in tempo reale
  - Esecuzione thread-safe: la pipeline non blocca mai l'interfaccia
"""

import math
import os
import queue
import subprocess
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import brand
from brand import asset_path as brand_asset
from brand import families as brand_families
from analyzer.ai_vision_advisor import AI_PROVIDERS
from config_bridge import manual_zone_ids, validate_config
from meta_driver.launcher import find_meta_executable
from file_discovery import try_discover
from meta_driver.fluent_parser import inspect_fluent_cas_zones


# ==============================================================================
#  PALETTE & COSTANTI
# ==============================================================================
# Palette brand UniNa Corse: #11255C (navy) · #5B2581 (viola) ·
# #FDEB19 (giallo) · #d8eefc (azzurro). Le sfumature sono mescolanze documentate
# in brand.py. I nomi delle costanti restano quelli storici, cosi' ogni widget
# continua a funzionare senza altre modifiche.
BG          = brand.NAVY_DEEP      # fondo applicazione
SURFACE     = brand.NAVY           # card
SURFACE_ALT = brand.NAVY_PANEL     # superfici secondarie (rampa brand)
INPUT_BG    = brand.INPUT_BG
BORDER      = brand.BORDER
BORDER_SOFT = brand.BORDER_SOFT
TEXT        = brand.WHITE
TEXT_SOFT   = brand.ICE
MUTED       = brand.TEXT_MUTED
FAINT       = brand.TEXT_FAINT
ACCENT      = brand.GOLD           # accento primario: CTA, valori, bordi attivi
ACCENT_DARK = brand.GOLD_DEEP      # base dei gradienti gialli
INDIGO      = brand.VIOLET         # accento secondario
SUCCESS     = brand.ICE
WARNING     = brand.GOLD
DANGER      = brand.DANGER
VIOLET_SOFT = brand.VIOLET_SOFT

# Roboto (SIL OFL) incluso in assets/fonts e registrato come font privato del
# processo; senza i file si ricade sui font di sistema.
_FAMILIES = brand_families()
FONT_UI    = _FAMILIES["ui"]
FONT_MONO  = _FAMILIES["num"]

ASSEMBLY_LABELS = {
    "undertray":  "Undertray · Fondo & Diffusore",
    "front_wing": "Ala Anteriore",
    "rear_wing":  "Ala Posteriore",
    "full_car":   "Vettura Completa",
}
LABEL_TO_ASSEMBLY = {v: k for k, v in ASSEMBLY_LABELS.items()}


# ==============================================================================
#  HELPERS COLORE / DISEGNO
# ==============================================================================
def _hex_to_rgb(color: str):
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def mix_color(c1: str, c2: str, t: float) -> str:
    """Interpola linearmente due colori esadecimali (t = 0 -> c1, t = 1 -> c2)."""
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex((r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t))


def lighten(color: str, amount: float = 0.12) -> str:
    return mix_color(color, "#ffffff", amount)


def _rounded_rect(canvas, x0, y0, x1, y1, radius, **kwargs):
    """Rettangolo arrotondato (poligono smussato): base delle card moderne."""
    r = max(1, min(radius, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    points = [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
        x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
        x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class RoundedPanel(tk.Canvas):
    """
    Card moderna: superficie piena, angoli arrotondati, **nessun bordo**.

    Ospita un Frame reale (`body`): chi la usa continua a pack/grid dentro
    `body` come faceva con il vecchio Frame bordato.

    `stretch=True` fa crescere il corpo fino all'altezza disponibile (serve ai
    pannelli che riempiono una cella della griglia, come la console).
    """

    def __init__(self, master, radius=16, fill=None, padx=20, pady=16, stretch=False):
        super().__init__(master, bd=0, highlightthickness=0, bg=master.cget("bg"))
        self._radius = radius
        self._fill = fill or SURFACE
        self._padx, self._pady = padx, pady
        self._stretch = stretch
        self.body = tk.Frame(self, bg=self._fill)
        self._win = self.create_window(padx, pady, window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._sync_height)
        self.bind("<Configure>", self._sync_geometry)

    def _sync_height(self, _e=None):
        if not self._stretch:
            self.configure(height=self.body.winfo_reqheight() + 2 * self._pady)

    def _sync_geometry(self, event):
        self.coords(self._win, self._padx, self._pady)
        self.itemconfigure(self._win, width=max(1, event.width - 2 * self._padx))
        if self._stretch:
            self.itemconfigure(self._win, height=max(1, event.height - 2 * self._pady))
        self._draw_bg(event.width, event.height)

    def _draw_bg(self, width, height):
        self.delete("panelbg")
        if width <= 1 or height <= 1:
            return
        _rounded_rect(self, 0, 0, width - 1, height - 1, self._radius,
                      fill=self._fill, outline="", tags="panelbg")
        self.tag_lower("panelbg")


def _rounded_polygon(canvas, x0, y0, x1, y1, r, **kwargs):
    """Disegna un rettangolo arrotondato morbido come poligono smussato."""
    r = max(1, min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    points = [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
        x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
        x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def _draw_gradient_round_rect(canvas, w, h, c1, c2, radius=14):
    """Gradiente verticale ritagliato con estremità arrotondate."""
    r = min(radius, h / 2.0, w / 2.0)
    for y in range(int(h)):
        if y < r:
            dx = r - math.sqrt(max(0.0, r * r - (r - y) ** 2))
        elif y > h - r:
            dx = r - math.sqrt(max(0.0, r * r - (y - (h - r)) ** 2))
        else:
            dx = 0.0
        x0, x1 = dx + 1, w - dx - 1
        if x1 > x0:
            canvas.create_line(
                x0, y, x1, y, width=1,
                fill=mix_color(c1, c2, y / max(h - 1, 1)),
            )


def _elide(text: str, limit: int = 42) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ==============================================================================
#  WIDGET PERSONALIZZATI
# ==============================================================================
class GradientButton(tk.Canvas):
    """Pulsante principale con gradiente, stati hover/disabled e angoli morbidi."""

    def __init__(self, master, text, command, width=340, height=48,
                 c1=ACCENT_DARK, c2=ACCENT, fg=brand.NAVY,
                 font=(FONT_UI, 10, "bold"), **kwargs):
        super().__init__(master, width=width, height=height, bd=0,
                         highlightthickness=0, bg=master.cget("bg"), **kwargs)
        self._text = text
        self._command = command
        self._pw, self._ph = width, height
        self._c1, self._c2, self._fg = c1, c2, fg
        self._font = font
        self._hover = False
        self._enabled = True
        self._pressed = False
        self.configure(cursor="hand2", takefocus=1)
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Return>", lambda _e: self._fire())
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width() if self.winfo_width() > 1 else self._pw
        h = self.winfo_height() if self.winfo_height() > 1 else self._ph
        if not self._enabled:
            fill, fg = SURFACE_ALT, FAINT
        elif self._hover:
            fill, fg = lighten(self._c1, 0.10), self._fg
        elif self._pressed:
            fill, fg = mix_color(self._c1, "#000000", 0.10), self._fg
        else:
            fill, fg = self._c1, self._fg
        # stile moderno: tinta piena e angoli morbidi, niente gradiente
        _rounded_rect(self, 1, 1, w - 1, h - 1, min(11, h / 2.0), fill=fill, outline="")
        self.create_text(w / 2.0, h / 2.0, text=self._text, fill=fg, font=self._font)

    def _on_enter(self, _e=None):
        if self._enabled:
            self._hover = True
            self._draw()

    def _on_leave(self, _e=None):
        self._hover = False
        self._pressed = False
        self._draw()

    def _on_press(self, _e=None):
        if self._enabled:
            self._pressed = True
            self._draw()

    def _on_release(self, event=None):
        if not self._enabled:
            return
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if was_pressed and event is not None:
            if 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
                self._fire()

    def _fire(self):
        if self._enabled and callable(self._command):
            self._command()

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        self._hover = False
        self._pressed = False
        self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()


class FlatButton(tk.Button):
    """
    Pulsante secondario moderno: **outline** o **ghost**, mai un blocco pieno.

    L'outline ha solo il contorno (1 px) e diventa superficie piena allo hover;
    il ghost e' testo nudo. Cosi' l'unico elemento pieno resta la call to action.
    """

    # kind -> (fg, hover_bg, bordo)
    _STYLES = {
        "secondary": (TEXT_SOFT, SURFACE_ALT, BORDER),
        "success":   (ACCENT, SURFACE_ALT, ACCENT),
        "ghost":     (MUTED, SURFACE_ALT, None),
    }

    def __init__(self, master, text, command=None, kind="secondary",
                 font=(FONT_UI, 9, "bold"), **kwargs):
        fg, hover, border = self._STYLES.get(kind, self._STYLES["secondary"])
        parent_bg = master.cget("bg")
        base = parent_bg
        self._base, self._fg, self._hover, self._border = base, fg, hover, border
        self._enabled = True
        super().__init__(
            master, text=text, command=command, bg=base, fg=fg,
            activebackground=hover, activeforeground=fg,
            disabledforeground=FAINT, relief="flat", bd=0,
            highlightthickness=1 if border else 0,
            highlightbackground=border or parent_bg,
            highlightcolor=border or parent_bg,
            padx=14, pady=8, cursor="hand2", font=font, **kwargs
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, _e=None):
        if self._enabled:
            self.configure(bg=self._hover)

    def _on_leave(self, _e=None):
        if self._enabled:
            self.configure(bg=self._base)

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        if enabled:
            self.configure(state=tk.NORMAL, bg=self._base, fg=self._fg,
                           cursor="hand2", activebackground=self._hover,
                           highlightbackground=self._border or self._base)
        else:
            self.configure(state=tk.DISABLED, bg=self._base, fg=FAINT,
                           cursor="arrow", activebackground=self._base,
                           highlightbackground=BORDER_SOFT)


class StatusPill(tk.Canvas):
    """Indicatore di stato arrotondato con pallino colorato."""

    def __init__(self, master, text="Pronto", color=SUCCESS, width=150, height=32):
        super().__init__(master, width=width, height=height, bd=0,
                         highlightthickness=0, bg=master.cget("bg"))
        self._pw, self._ph = width, height
        self._text, self._color = text, color
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h, color = self._pw, self._ph, self._color
        fill = mix_color(SURFACE_ALT, color, 0.14)
        outline = mix_color(SURFACE, color, 0.38)
        _rounded_polygon(self, 1, 1, w - 1, h - 1, (h - 2) / 2.0,
                         fill=fill, outline=outline, width=1)
        cy = h / 2.0
        self.create_oval(12, cy - 3.5, 19, cy + 3.5, fill=color, outline="")
        self.create_text(27, cy, text=self._text, anchor="w", fill=color,
                         font=(FONT_UI, 9, "bold"))

    def set(self, text: str, color: str):
        self._text, self._color = text, color
        self._draw()


class _BrandBars(tk.Canvas):
    """Le tre barre oblique del brand (giallo, viola, azzurro) come firma grafica."""

    COLORS = ((ACCENT, 46), (INDIGO, 26), (TEXT_SOFT, 8))

    def __init__(self, master, width=140, height=46):
        super().__init__(master, width=width, height=height, bd=0,
                         highlightthickness=0, bg=master.cget("bg"))
        # ATTENZIONE: `_w` e `_h` sono attributi interni di Tkinter (path del
        # widget): vanno usati nomi propri, altrimenti pack() riceve un intero.
        self._base_w, self._base_h = width, height
        self.bind("<Configure>", self._draw)

    def _draw(self, _e=None):
        self.delete("all")
        w = self.winfo_width() or self._base_w
        h = self.winfo_height() or self._base_h
        slant = h * 0.45
        for color, offset in self.COLORS:
            x = w - offset
            self.create_polygon(
                x, h, x + 8, h, x + 8 + slant, h * 0.10, x + slant, h * 0.10,
                fill=color, outline="",
            )


class GradientStrip(tk.Canvas):
    """
    Striscia sotto l'header con il segno grafico del brand.

    Ripete le barre oblique giallo/viola/navy/azzurro: sono disegnate su Canvas,
    quindi non serve includere nessuna immagine nel pacchetto.
    """

    BARS = ((ACCENT, 0.00), (INDIGO, 0.22), (SURFACE_ALT, 0.40), (TEXT_SOFT, 0.48))
    PERIOD = 240
    BAR_W = 5

    def __init__(self, master, height=6):
        super().__init__(master, height=height, bd=0, highlightthickness=0,
                         bg=master.cget("bg"))
        self._strip_h = height
        self.bind("<Configure>", self._draw)

    def _draw(self, _e=None):
        self.delete("all")
        width = max(self.winfo_width(), 1)
        if width <= 1:
            return
        h = self._strip_h
        # un filo continuo + tre accenti di brand raggruppati a sinistra
        self.create_line(0, h - 1, width, h - 1, fill=BORDER_SOFT)
        for index, color in enumerate((ACCENT, INDIGO, TEXT_SOFT)):
            x = 30 + index * 24
            if x + 18 < width:
                self.create_line(x, h - 1, x + 18, h - 1, fill=color, width=2)


class ScrollableFrame(tk.Frame):
    """Contenitore verticalmente scorrevole con scrollbar che appare solo se serve."""

    def __init__(self, master, bg=BG, **kwargs):
        super().__init__(master, bg=bg, **kwargs)
        self.canvas = tk.Canvas(self, bg=bg, bd=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical",
                                       command=self.canvas.yview,
                                       style="Modern.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", self._on_wheel))
        self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))

    def _on_inner_configure(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        needed = self.inner.winfo_reqheight() > self.canvas.winfo_height()
        if needed and not self.scrollbar.winfo_ismapped():
            self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        elif not needed and self.scrollbar.winfo_ismapped():
            self.scrollbar.pack_forget()

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)
        self._on_inner_configure()

    def _on_wheel(self, event):
        if self.inner.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


# ==============================================================================
#  HELPERS DI LAYOUT
# ==============================================================================
def card(parent, title=None, subtitle=None, icon=None, accent=None):
    """
    Card moderna: pannello arrotondato, superficie piena, **nessun bordo**.

    `icon` resta accettato per compatibilita' ma non viene disegnato: al suo
    posto c'e' una barretta d'accento colorata (piu' pulita dei dingbat ◈ ✦ ⚙).
    Restituisce `(panel, body)`.
    """
    panel = RoundedPanel(parent, radius=18, padx=22, pady=18)
    body = panel.body
    if title:
        head = tk.Frame(body, bg=SURFACE)
        head.pack(fill=tk.X)
        bar = tk.Frame(head, bg=accent or ACCENT, width=3, height=16)
        bar.pack(side=tk.LEFT, padx=(0, 11))
        bar.pack_propagate(False)
        tk.Label(head, text=title, bg=SURFACE, fg=TEXT,
                 font=(FONT_UI, 11, "bold")).pack(side=tk.LEFT)
        if subtitle:
            tk.Label(body, text=subtitle, bg=SURFACE, fg=MUTED,
                     font=(FONT_UI, 8), justify="left",
                     wraplength=350).pack(anchor="w", pady=(7, 14))
        else:
            tk.Frame(body, bg=SURFACE, height=12).pack(fill=tk.X)
    return panel, body


def field_label(parent, text, hint=None):
    """Etichetta di campo moderna: minuscolo maiuscoletto attenuato + unita'."""
    row = tk.Frame(parent, bg=SURFACE)
    tk.Label(row, text=text.upper(), bg=SURFACE, fg=MUTED,
             font=(FONT_UI, 8, "bold")).pack(side=tk.LEFT)
    if hint:
        tk.Label(row, text=hint, bg=SURFACE, fg=FAINT,
                 font=(FONT_UI, 8)).pack(side=tk.LEFT, padx=(7, 0))
    return row


def make_entry(parent, variable, width=20, show=None):
    return tk.Entry(
        parent, textvariable=variable, width=width, show=show,
        bg=INPUT_BG, fg=TEXT, insertbackground=ACCENT,
        disabledbackground=SURFACE_ALT, disabledforeground=MUTED,
        relief="flat", bd=0, highlightthickness=1,
        highlightbackground=BORDER_SOFT, highlightcolor=ACCENT,
        font=(FONT_UI, 10),
    )


# ==============================================================================
#  APPLICAZIONE PRINCIPALE
# ==============================================================================
class AeroDiagnosticsGUI:
    def __init__(self, root: tk.Tk, default_config: dict, pipeline_runner_fn):
        self.root = root
        self.config = default_config
        self.pipeline_runner_fn = pipeline_runner_fn

        self.last_report_path = None
        self.last_ses_path = None
        self._busy = False
        self._t0 = 0.0
        self.log_queue = queue.Queue()
        self._icon = None
        self._ai_check_running = False
        self._zone_vars = {}
        self._zone_catalog = []
        self._zone_mode = "auto"

        # ------------------------------------------------------------------ vars
        project = self.config.get("project", {})
        refs = self.config.get("reference_values", {})
        meta = self.config.get("meta", {})
        ai = self.config.get("ai_vision", {})

        asm_key = project.get("assembly_type", "undertray")
        if asm_key == "auto":
            asm_key = "undertray"
        self.var_workspace = tk.StringVar(value=os.path.abspath(project.get("workspace_dir", ".")))
        self.var_assembly = tk.StringVar(value=ASSEMBLY_LABELS.get(asm_key, ASSEMBLY_LABELS["undertray"]))
        self.var_meta_exe = tk.StringVar(value=find_meta_executable(meta.get("executable_path", "auto")) or "auto")
        self.var_vinf = tk.StringVar(value=str(refs.get("velocity_inf", 14.0)))
        self.var_rho = tk.StringVar(value=str(refs.get("density_air", 1.225)))
        self.var_apikey = tk.StringVar(value=ai.get("api_key", ""))
        self.var_provider = tk.StringVar(
            value=str(ai.get("provider", "gemini")).strip().lower()
            if str(ai.get("provider", "gemini")).strip().lower() in AI_PROVIDERS else "gemini"
        )
        self.var_auto_open = tk.BooleanVar(value=True)
        self.var_show_key = tk.BooleanVar(value=False)

        # ------------------------------------------------------------------ window
        self.root.title("FS · MetaPostDiag  —  CFD Post-Processing con BETA CAE META Post")
        self.root.configure(bg=BG)
        self.root.minsize(1040, 700)
        self._center_window(1240, 820)
        self._setup_style()
        self._make_window_icon()

        self._build_ui()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Control-r>", lambda _e: self._start_pipeline_thread())
        self.root.bind("<Control-o>", lambda _e: self._open_report())
        self.root.bind("<Control-l>", lambda _e: self._clear_log())

        self._log("[SISTEMA] Interfaccia pronta. Seleziona la cartella CFD e avvia la pipeline.")
        self.root.after(90, self._poll_log_queue)
        self.root.after(180, self._inspect_current_workspace)

    # ------------------------------------------------------------------ setup
    def _center_window(self, width, height):
        try:
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            width = min(width, sw - 60)
            height = min(height, sh - 80)
            x = max(0, (sw - width) // 2)
            y = max(0, (sh - height) // 2 - 18)
            self.root.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            self.root.geometry(f"{width}x{height}")

    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(
            "Modern.TCombobox",
            fieldbackground=INPUT_BG, background=INPUT_BG, foreground=TEXT,
            arrowcolor=MUTED, bordercolor=BORDER, lightcolor=BORDER,
            darkcolor=BORDER, selectbackground=SURFACE_ALT,
            selectforeground=TEXT, padding=6,
        )
        style.map(
            "Modern.TCombobox",
            fieldbackground=[("readonly", INPUT_BG), ("focus", INPUT_BG)],
            foreground=[("readonly", TEXT), ("focus", TEXT)],
            selectbackground=[("readonly", INPUT_BG)],
            selectforeground=[("readonly", TEXT)],
            bordercolor=[("focus", ACCENT)],
        )
        # Scrollbar sottile e discreta: thumb in tinta bordo, giallo allo hover
        style.configure(
            "Modern.Vertical.TScrollbar",
            background=BORDER, troughcolor=BG, bordercolor=BG,
            arrowcolor=FAINT, darkcolor=BORDER, lightcolor=BORDER,
            width=6, arrowsize=8, relief="flat",
        )
        style.map("Modern.Vertical.TScrollbar",
                  background=[("active", ACCENT), ("pressed", ACCENT)],
                  arrowcolor=[("active", brand.NAVY)])
        style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor=SURFACE_ALT, background=ACCENT, bordercolor=SURFACE_ALT,
            lightcolor=ACCENT, darkcolor=ACCENT, thickness=4,
        )
        self.root.option_add("*TCombobox*Listbox.background", SURFACE)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DARK)
        self.root.option_add("*TCombobox*Listbox.selectForeground", BG)
        self.root.option_add("*TCombobox*Listbox.font", f"{{{FONT_UI}}} 10")

    def _load_image(self, name, height):
        """
        Carica una PNG di `assets/` ridimensionata in altezza.

        Restituisce None se la risorsa o Pillow non sono disponibili: l'UI deve
        funzionare anche senza immagini.
        """
        path = brand_asset(name)
        if not path:
            return None
        try:
            from PIL import Image, ImageTk

            image = Image.open(path)
            ratio = float(height) / max(image.height, 1)
            size = (max(1, int(round(image.width * ratio))), int(height))
            photo = ImageTk.PhotoImage(image.resize(size, Image.LANCZOS))
            return photo
        except Exception:
            return None

    def _make_window_icon(self):
        """Icona della finestra: l'icona di brand, con segnaposto se manca."""
        icon = self._load_image("FS-MetaPostDiag.png", 64)
        if icon is not None:
            try:
                self.root.iconphoto(True, icon)
                self._icon = icon
                return
            except Exception:
                pass
        try:
            size, radius = 32, 7
            img = tk.PhotoImage(width=size, height=size)
            for y in range(size):
                for x in range(size):
                    inside = True
                    for cx, cy in ((radius, radius), (size - 1 - radius, radius),
                                   (radius, size - 1 - radius),
                                   (size - 1 - radius, size - 1 - radius)):
                        if ((x < radius and y < radius) or (x > size - 1 - radius and y < radius)
                                or (x < radius and y > size - 1 - radius)
                                or (x > size - 1 - radius and y > size - 1 - radius)):
                            if (x - cx) ** 2 + (y - cy) ** 2 > radius ** 2:
                                inside = False
                    if inside:
                        img.put(mix_color(ACCENT_DARK, INDIGO, y / (size - 1)),
                                to=(x, y, x + 1, y + 1))
            self.root.iconphoto(True, img)
            self._icon = img
        except Exception:
            pass

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self._build_header()

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=28, pady=(18, 8))
        body.grid_columnconfigure(0, minsize=470, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self.left = ScrollableFrame(body)
        self.left.grid(row=0, column=0, sticky="nsew", padx=(0, 18))

        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        self._build_source_card(self.left.inner)
        # Prima la scelta delle zone (serve a far tornare i conti con Fluent),
        # poi i parametri di esecuzione.
        self._build_zone_card(self.left.inner)
        self._build_execution_card(self.left.inner)
        self._build_action_card(right)
        self._build_log_card(right)
        self._set_status("Pronto", SUCCESS)
        # Coerenza del config: gli errori silenziosi (assi invertiti, valori non
        # fisici) vanno visti qui, non scoperti da numeri sbagliati nel report.
        for warning in validate_config(self.config):
            self._log("[CONFIG-WARN] " + warning)

        self._build_footer()

    def _build_header(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill=tk.X)

        inner = tk.Frame(header, bg=BG, padx=28)
        inner.pack(fill=tk.X, pady=(18, 14))

        # destra: stato META + segno grafico del brand
        bars = _BrandBars(inner)
        bars.pack(side=tk.RIGHT, padx=(18, 0))

        meta_box = tk.Frame(inner, bg=BG)
        meta_box.pack(side=tk.RIGHT)
        chip = tk.Label(meta_box, text="  META Post v25.1+  ", bg=SURFACE_ALT,
                        fg=ACCENT, font=(FONT_UI, 8, "bold"), pady=3)
        chip.pack(anchor="e")
        tk.Label(meta_box, text="dati reali .cas/.dat", bg=BG, fg=FAINT,
                 font=(FONT_UI, 8)).pack(anchor="e", pady=(4, 0))

        # sinistra: monogramma UC del brand + titoli
        monogram = self._load_image("uc-monogram-white.png", 38)
        if monogram is not None:
            self._img_monogram = monogram
            tk.Label(inner, image=monogram, bg=BG).pack(side=tk.LEFT, padx=(0, 14))

        titles = tk.Frame(inner, bg=BG)
        titles.pack(side=tk.LEFT)
        tk.Label(titles, text="FS · MetaPostDiag", bg=BG, fg=TEXT,
                 font=(FONT_UI, 17, "bold")).pack(anchor="w")
        tk.Label(
            titles,
            text="Post-Processing CFD automatico · Design Diagnostics · UniNa Corse",
            bg=BG, fg=MUTED, font=(FONT_UI, 8),
        ).pack(anchor="w", pady=(1, 0))

        GradientStrip(self.root, height=3).pack(fill=tk.X)

    # ------------------------------------------------------------------ left column
    def _build_source_card(self, parent):
        outer, body = card(
            parent, "Sorgente CFD",
            "Cartella di analisi e isolamento dei PID dal file .cas",
            icon="◈",
        )
        outer.pack(fill=tk.X, pady=(0, 12))

        field_label(body, "Cartella analisi", ".cas / .dat").pack(anchor="w", pady=(0, 6))
        row = tk.Frame(body, bg=SURFACE)
        row.pack(fill=tk.X)
        entry = make_entry(row, self.var_workspace)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6)
        FlatButton(row, "Sfoglia", command=self._browse_workspace, kind="secondary").pack(
            side=tk.LEFT, padx=(8, 0))

        files = RoundedPanel(body, radius=12, fill=SURFACE_ALT, padx=14, pady=6)
        files.pack(fill=tk.X, pady=(12, 0))
        self.lbl_cas_name, self.lbl_cas_size = self._file_row(files.body, ACCENT, "Nessun file .cas")
        tk.Frame(files.body, bg=BORDER_SOFT, height=1).pack(fill=tk.X, pady=5)
        self.lbl_dat_name, self.lbl_dat_size = self._file_row(files.body, VIOLET_SOFT, "Nessun file .dat")

        field_label(body, "Assieme da isolare").pack(anchor="w", pady=(12, 5))
        asm_row = tk.Frame(body, bg=SURFACE)
        asm_row.pack(fill=tk.X)
        self.cmb_assembly = ttk.Combobox(
            asm_row, textvariable=self.var_assembly,
            values=list(ASSEMBLY_LABELS.values()), state="readonly",
            style="Modern.TCombobox", font=(FONT_UI, 10),
        )
        self.cmb_assembly.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.cmb_assembly.bind("<<ComboboxSelected>>", lambda _e: self._inspect_current_workspace())
        FlatButton(asm_row, "Analizza .CAS", command=self._inspect_current_workspace,
                   kind="secondary").pack(side=tk.LEFT, padx=(8, 0))

        self.lbl_zone_summary = tk.Label(
            body, text="Zone isolate: —", bg=SURFACE, fg=MUTED,
            font=(FONT_UI, 8), justify="left", anchor="w",
        )
        self.lbl_zone_summary.pack(fill=tk.X, pady=(6, 0))

    def _file_row(self, parent, color, placeholder):
        row = tk.Frame(parent, bg=SURFACE_ALT)
        row.pack(fill=tk.X, pady=2)
        row.grid_columnconfigure(1, weight=1)
        tk.Label(row, text="●", bg=SURFACE_ALT, fg=color,
                 font=(FONT_UI, 8)).grid(row=0, column=0)
        name = tk.Label(row, text=placeholder, bg=SURFACE_ALT, fg=MUTED,
                        font=(FONT_UI, 9), anchor="w")
        name.grid(row=0, column=1, sticky="w", padx=(7, 6))
        size = tk.Label(row, text="", bg=SURFACE_ALT, fg=FAINT,
                        font=(FONT_UI, 8))
        size.grid(row=0, column=2, sticky="e")
        return name, size

    def _build_execution_card(self, parent):
        outer, body = card(
            parent, "Esecuzione META",
            "Percorso dell'eseguibile e condizioni di riferimento per il calcolo dei coefficienti",
            icon="⚙",
        )
        outer.pack(fill=tk.X, pady=(0, 12))

        field_label(body, "Eseguibile META Post").pack(anchor="w", pady=(0, 6))
        row = tk.Frame(body, bg=SURFACE)
        row.pack(fill=tk.X)
        make_entry(row, self.var_meta_exe).pack(side=tk.LEFT, fill=tk.X,
                                               expand=True, ipady=6)
        FlatButton(row, "Cerca", command=self._browse_meta_exe, kind="secondary").pack(
            side=tk.LEFT, padx=(8, 0))

        values = tk.Frame(body, bg=SURFACE)
        values.pack(fill=tk.X, pady=(12, 0))
        values.grid_columnconfigure(0, weight=1, uniform="val")
        values.grid_columnconfigure(1, weight=1, uniform="val")

        v1 = tk.Frame(values, bg=SURFACE)
        v1.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        field_label(v1, "Velocità V∞", "[m/s]").pack(anchor="w", pady=(0, 5))
        make_entry(v1, self.var_vinf, width=10).pack(fill=tk.X, ipady=6)

        v2 = tk.Frame(values, bg=SURFACE)
        v2.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        field_label(v2, "Densità aria", "[kg/m³]").pack(anchor="w", pady=(0, 5))
        make_entry(v2, self.var_rho, width=10).pack(fill=tk.X, ipady=6)

        field_label(body, "API Key Vision AI", "opzionale").pack(anchor="w", pady=(12, 5))
        key_row = tk.Frame(body, bg=SURFACE)
        key_row.pack(fill=tk.X)
        self.ent_apikey = make_entry(key_row, self.var_apikey, show="*")
        self.ent_apikey.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6)
        self.btn_show_key = FlatButton(key_row, "Mostra", command=self._toggle_key,
                                       kind="ghost", font=(FONT_UI, 8, "bold"))
        self.btn_show_key.pack(side=tk.LEFT, padx=(8, 0))

        provider_row = tk.Frame(body, bg=SURFACE)
        provider_row.pack(fill=tk.X, pady=(8, 0))
        field_label(provider_row, "Provider AI", "gemini · openai · deepseek").pack(side=tk.LEFT)
        self.cmb_provider = ttk.Combobox(
            provider_row, textvariable=self.var_provider, values=list(AI_PROVIDERS),
            state="readonly", width=11, style="Modern.TCombobox", font=(FONT_UI, 9),
        )
        self.cmb_provider.pack(side=tk.RIGHT)

        tk.Label(
            body, text="Gemini, OpenAI o DeepSeek per il commento aerodinamico sulle immagini. "
                       "Con DeepSeek si usa il modello con vision e il thinking mode "
                       "(config.yaml: model_deepseek, deepseek_reasoning_effort). "
                       "Può essere lasciata vuota: il motore esperto offline resta attivo.",
            bg=SURFACE, fg=FAINT, font=(FONT_UI, 8), wraplength=370,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        # Il pulsante sta nella riga della chiave: cosi' resta visibile senza scorrere.
        # Stessa diagnostica di `--ai-check`, senza uscire dall'app.
        self.btn_ai_check = FlatButton(
            key_row, "Verifica AI", command=self._check_ai_config,
            kind="ghost", font=(FONT_UI, 8, "bold"),
        )
        self.btn_ai_check.pack(side=tk.LEFT, padx=(6, 0))

    # ------------------------------------------------------------ selezione zone
    def _build_zone_card(self, parent):
        """
        Selezione manuale delle zone **wall** incluse nel computo delle forze.

        Serve quando il numero di Fluent non coincide: si sceglie lo stesso
        elenco di zone usato nel report Fluent.
        """
        outer, body = card(
            parent, "PID nel computo",
            "Zone wall incluse nel calcolo delle forze: selezionale come nel report Fluent",
            accent=VIOLET_SOFT,
        )
        outer.pack(fill=tk.X, pady=(0, 12))

        self.lbl_zone_count = tk.Label(
            body, text="Nessun .cas analizzato", bg=SURFACE, fg=FAINT,
            font=(FONT_UI, 8), justify="left", anchor="w",
        )
        self.lbl_zone_count.pack(fill=tk.X, pady=(0, 6))

        self.zone_scroll = ScrollableFrame(body, bg=SURFACE)
        self.zone_scroll.canvas.configure(height=150)
        self.zone_scroll.pack(fill=tk.X)

        actions = tk.Frame(body, bg=SURFACE)
        actions.pack(fill=tk.X, pady=(8, 0))
        FlatButton(actions, "Tutti", command=lambda: self._set_all_zones(True),
                   kind="ghost", font=(FONT_UI, 8, "bold")).pack(side=tk.LEFT)
        FlatButton(actions, "Nessuno", command=lambda: self._set_all_zones(False),
                   kind="ghost", font=(FONT_UI, 8, "bold")).pack(side=tk.LEFT, padx=(4, 0))
        FlatButton(actions, "Automatico", command=self._reset_zone_selection,
                   kind="secondary", font=(FONT_UI, 8, "bold")).pack(side=tk.RIGHT)

    def _populate_zone_list(self, info: dict, asm_key: str):
        """Riempie le checkbox con le zone wall del .cas appena letto."""
        for child in self.zone_scroll.inner.winfo_children():
            child.destroy()
        self._zone_vars.clear()
        self._zone_catalog = []

        aero = info.get("aero_zones") or []
        target_ids = {int(z.get("id", -1)) for z in (info.get("target_zones") or [])}
        manual = set(manual_zone_ids(self.config, asm_key))
        self._zone_mode = "manual" if manual else "auto"
        selected = manual if manual else target_ids

        for zone in sorted(aero, key=lambda z: str(z.get("name", ""))):
            try:
                zid = int(zone.get("id", -1))
            except (TypeError, ValueError):
                continue
            if zid < 0:
                continue
            var = tk.BooleanVar(value=zid in selected)
            names = zone.get("raw_names") or []
            label = str(zone.get("name", "?"))
            detail = "" if len(names) <= 1 else "  (%d nomi)" % len(names)
            chk = tk.Checkbutton(
                self.zone_scroll.inner, text="%s  · id %d%s" % (label, zid, detail),
                variable=var, command=self._on_zone_toggle,
                bg=SURFACE, fg=TEXT_SOFT, activebackground=SURFACE,
                activeforeground=TEXT, selectcolor=ACCENT,
                bd=0, highlightthickness=0, anchor="w", font=(FONT_UI, 8),
            )
            chk.pack(anchor="w", padx=2)
            self._zone_vars[zid] = var
            self._zone_catalog.append({"id": zid, "name": label})
        self._update_zone_summary()

    def _on_zone_toggle(self):
        self._zone_mode = "manual"
        self._update_zone_summary()

    def _set_all_zones(self, value: bool):
        for var in self._zone_vars.values():
            var.set(bool(value))
        self._zone_mode = "manual"
        self._update_zone_summary()

    def _reset_zone_selection(self):
        """Torna alla selezione automatica per keyword."""
        if not self._zone_catalog:
            return
        self._zone_mode = "auto"
        self.config.get("assemblies", {}).get(self._assembly_key(), {}).pop("manual_zone_ids", None)
        self._log("[ZONE] Selezione automatica ripristinata.")
        self._update_zone_summary()

    def _update_zone_summary(self):
        total = len(self._zone_vars)
        if not total:
            self.lbl_zone_count.configure(text="Nessun .cas analizzato", fg=FAINT)
            return
        chosen = sum(1 for var in self._zone_vars.values() if var.get())
        mode = "manuale" if self._zone_mode == "manual" else "automatica"
        self.lbl_zone_count.configure(
            text="Zone wall: %d  ·  incluse: %d  ·  selezione %s" % (total, chosen, mode),
            fg=TEXT_SOFT if chosen else DANGER,
        )

    def _apply_zone_selection_to_config(self):
        """Scrive la scelta nel config (o la rimuove se si usa l'automatico)."""
        asm_key = self._assembly_key()
        profile = self.config.setdefault("assemblies", {}).setdefault(asm_key, {})
        if self._zone_mode == "manual" and self._zone_vars:
            ids = [zid for zid, var in self._zone_vars.items() if var.get()]
            if ids:
                profile["manual_zone_ids"] = ids
                self._log("[ZONE] Zone wall selezionate a mano: %d (id %s)"
                          % (len(ids), ", ".join(str(i) for i in sorted(ids))))
                return
        profile.pop("manual_zone_ids", None)

    # ------------------------------------------------------------------ right column
    def _build_action_card(self, parent):
        outer = RoundedPanel(parent, radius=18, padx=22, pady=18)
        outer.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        body = outer.body

        top = tk.Frame(body, bg=SURFACE)
        top.pack(fill=tk.X)
        titles = tk.Frame(top, bg=SURFACE)
        titles.pack(side=tk.LEFT, anchor="w")
        tk.Label(titles, text="Pipeline di analisi", bg=SURFACE, fg=TEXT,
                 font=(FONT_UI, 15, "bold")).pack(anchor="w")
        tk.Label(titles, text="Mesh reale · META Post · Computer Vision · Report HTML standalone",
                 bg=SURFACE, fg=MUTED, font=(FONT_UI, 8)).pack(anchor="w", pady=(2, 0))
        self.status_pill = StatusPill(top, "Pronto", SUCCESS)
        self.status_pill.pack(side=tk.RIGHT, anchor="e", padx=(10, 0))

        buttons = tk.Frame(body, bg=SURFACE)
        buttons.pack(fill=tk.X, pady=(18, 0))
        # unico elemento pieno dell'interfaccia: la call to action
        self.btn_run = GradientButton(
            buttons, "AVVIA POST-PROCESSING", command=self._start_pipeline_thread,
            width=300, height=46, c1=ACCENT, c2=ACCENT, fg=brand.NAVY,
            font=(FONT_UI, 10, "bold"),
        )
        self.btn_run.pack(side=tk.LEFT)
        chk = tk.Checkbutton(
            buttons, text="Apri report al termine", variable=self.var_auto_open,
            bg=SURFACE, fg=MUTED, activebackground=SURFACE, activeforeground=TEXT,
            selectcolor=ACCENT, bd=0, highlightthickness=0, cursor="hand2",
            font=(FONT_UI, 8),
        )
        chk.pack(side=tk.LEFT, padx=(18, 0))

        tools = tk.Frame(body, bg=SURFACE)
        tools.pack(fill=tk.X, pady=(12, 0))
        self.btn_open_report = FlatButton(tools, "Apri report", command=self._open_report,
                                          kind="success")
        self.btn_open_report.pack(side=tk.LEFT)
        self.btn_open_report.set_enabled(False)
        self.btn_open_output = FlatButton(tools, "Cartella output", command=self._open_output,
                                          kind="secondary")
        self.btn_open_output.pack(side=tk.LEFT, padx=(8, 0))
        self.btn_open_meta = FlatButton(tools, "Sessione META", command=self._open_meta_session,
                                        kind="secondary")
        self.btn_open_meta.pack(side=tk.LEFT, padx=(8, 0))
        self.btn_open_meta.set_enabled(False)

        self.progress = ttk.Progressbar(body, style="Accent.Horizontal.TProgressbar",
                                        mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=(16, 0))

        stats = tk.Frame(body, bg=SURFACE)
        stats.pack(fill=tk.X, pady=(16, 0))
        for i in range(3):
            stats.grid_columnconfigure(i, weight=1, uniform="stat")
        cas_card, self.stat_cas = self._stat_card(stats, "FILE .CAS", "—", ACCENT)
        cas_card.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        pid_card, self.stat_pid = self._stat_card(stats, "PID ISOLATI", "—", VIOLET_SOFT)
        pid_card.grid(row=0, column=1, sticky="ew", padx=5)
        from meta_locator import describe_meta

        meta_info = describe_meta(find_meta_executable(
            self.config.get("meta", {}).get("executable_path", "auto")))
        meta_found = bool(meta_info["found"])
        if meta_found and meta_info["version"]:
            meta_value = "v" + meta_info["version"]
        else:
            meta_value = "OK" if meta_found else "N/D"
        meta_card, self.stat_meta = self._stat_card(
            stats, "META POST", meta_value,
            SUCCESS if meta_found else WARNING)
        meta_card.grid(row=0, column=2, sticky="ew", padx=(5, 0))

    def _stat_card(self, parent, label, value, color):
        """Tile KPI moderna: etichetta minuta e attenuata, valore grande."""
        frame = RoundedPanel(parent, radius=14, fill=SURFACE_ALT, padx=16, pady=12)
        tk.Label(frame.body, text=label, bg=SURFACE_ALT, fg=FAINT,
                 font=(FONT_UI, 7, "bold")).pack(anchor="w")
        val = tk.Label(frame.body, text=value, bg=SURFACE_ALT, fg=color,
                       font=(FONT_UI, 19, "bold"))
        val.pack(anchor="w", pady=(3, 0))
        return frame, val

    def _build_log_card(self, parent):
        outer = RoundedPanel(parent, radius=18, padx=18, pady=14, stretch=True)
        outer.grid(row=1, column=0, sticky="nsew")
        body = outer.body

        head = tk.Frame(body, bg=SURFACE)
        head.pack(fill=tk.X, pady=(0, 10))
        bar = tk.Frame(head, bg=ACCENT, width=3, height=15)
        bar.pack(side=tk.LEFT, padx=(0, 10))
        bar.pack_propagate(False)
        tk.Label(head, text="Console di esecuzione", bg=SURFACE, fg=TEXT,
                 font=(FONT_UI, 11, "bold")).pack(side=tk.LEFT)
        tk.Label(head, text="verifica PID · mesh 3D · evidenze diagnostiche",
                 bg=SURFACE, fg=FAINT, font=(FONT_UI, 8)).pack(side=tk.LEFT, padx=(10, 0))
        FlatButton(head, "Copia", command=self._copy_log, kind="ghost",
                   font=(FONT_UI, 8)).pack(side=tk.RIGHT)
        FlatButton(head, "Pulisci", command=self._clear_log, kind="ghost",
                   font=(FONT_UI, 8)).pack(side=tk.RIGHT, padx=(0, 4))

        # superficie incassata senza bordo: piu' pulita di un riquadro bordato
        wrap = tk.Frame(body, bg=INPUT_BG)
        wrap.pack(fill=tk.BOTH, expand=True)
        self.txt_log = tk.Text(
            wrap, bg=INPUT_BG, fg=TEXT_SOFT, insertbackground=ACCENT,
            relief="flat", bd=0, padx=16, pady=14, wrap="word",
            font=(FONT_MONO, 9), state=tk.DISABLED, spacing1=2, spacing3=3,
            selectbackground=BORDER, selectforeground=TEXT,
        )
        scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.txt_log.yview,
                               style="Modern.Vertical.TScrollbar")
        self.txt_log.configure(yscrollcommand=scroll.set)
        self.txt_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.txt_log.tag_configure("time", foreground=FAINT)
        self.txt_log.tag_configure("info", foreground=TEXT_SOFT)
        self.txt_log.tag_configure("step", foreground=VIOLET_SOFT)
        self.txt_log.tag_configure("ok", foreground=SUCCESS)
        self.txt_log.tag_configure("warn", foreground=WARNING)
        self.txt_log.tag_configure("error", foreground=DANGER)

    def _build_footer(self):
        bar = tk.Frame(self.root, bg=BG, padx=28, pady=10)
        bar.pack(fill=tk.X)
        wordmark = self._load_image("wordmark-white.png", 16)
        if wordmark is not None:
            self._img_wordmark = wordmark
            tk.Label(bar, image=wordmark, bg=BG).pack(side=tk.LEFT, padx=(0, 12))
        tk.Label(
            bar, text="X = Longitudinale  ·  Y = Verticale  ·  Z = Laterale (Z=0 simmetria)",
            bg=BG, fg=FAINT, font=(FONT_UI, 8),
        ).pack(side=tk.LEFT)
        tk.Label(
            bar, text="Ctrl+R avvia  ·  Ctrl+O report  ·  Ctrl+L pulisci log",
            bg=BG, fg=FAINT, font=(FONT_UI, 8),
        ).pack(side=tk.RIGHT)

    # ------------------------------------------------------------------ helpers UI
    def _assembly_key(self) -> str:
        return LABEL_TO_ASSEMBLY.get(self.var_assembly.get().strip(), "undertray")

    def _toggle_key(self):
        show = not self.var_show_key.get()
        self.var_show_key.set(show)
        self.ent_apikey.configure(show="" if show else "*")
        self.btn_show_key.configure(text="Nascondi" if show else "Mostra")

    def _update_file_labels(self, cas_file, dat_file):
        if cas_file:
            self.lbl_cas_name.configure(
                text=_elide(os.path.basename(cas_file), 34), fg=TEXT)
            self.lbl_cas_size.configure(
                text=f"{os.path.getsize(cas_file) / (1024 * 1024):.0f} MB")
            self.stat_cas.configure(
                text=f"{os.path.getsize(cas_file) / (1024 * 1024):.0f} MB")
        else:
            self.lbl_cas_name.configure(text="Nessun file .cas trovato", fg=DANGER)
            self.lbl_cas_size.configure(text="")
            self.stat_cas.configure(text="—")
        if dat_file:
            self.lbl_dat_name.configure(
                text=_elide(os.path.basename(dat_file), 34), fg=TEXT)
            self.lbl_dat_size.configure(
                text=f"{os.path.getsize(dat_file) / (1024 * 1024):.0f} MB")
        else:
            self.lbl_dat_name.configure(text="Nessun file .dat trovato", fg=WARNING)
            self.lbl_dat_size.configure(text="")

    def _set_status(self, text: str, color: str, busy: bool = False):
        self.status_pill.set(text, color)
        if busy:
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            # a riposo la barra resta neutra (non deve sembrare un divisorio giallo)
            self.progress["value"] = 0

    # ------------------------------------------------------------------ log console
    def _log(self, msg: str):
        """Thread-safe: accoda sempre; il drain avviene sul thread Tk."""
        self.log_queue.put((time.strftime("%H:%M:%S"), str(msg)))

    def _poll_log_queue(self):
        try:
            for _ in range(400):
                ts, msg = self.log_queue.get_nowait()
                self._append_log(ts, msg)
        except queue.Empty:
            pass
        except tk.TclError:
            return
        try:
            self.root.after(80, self._poll_log_queue)
        except tk.TclError:
            pass

    @staticmethod
    def _tag_for(line: str) -> str:
        upper = line.upper()
        if "[ERRORE" in upper or "TRACEBACK" in upper or "ERROR" in upper:
            return "error"
        if "[AVVISO" in upper or "WARN" in upper or "ATTENZIONE" in upper:
            return "warn"
        if "COMPLETAT" in upper or "SUCCESSO" in upper or "[OK" in upper:
            return "ok"
        if ("[FASE" in upper or "[AVVIO" in upper or "[ISPEZIONE" in upper
                or "[LAUNCHER" in upper or "[SCAN" in upper or "[REPORT" in upper):
            return "step"
        return "info"

    def _append_log(self, ts: str, msg: str):
        try:
            if not self.txt_log.winfo_exists():
                return
            self.txt_log.configure(state=tk.NORMAL)
            for line in (msg.splitlines() or [""]):
                self.txt_log.insert(tk.END, f"{ts}  ", "time")
                self.txt_log.insert(tk.END, line + "\n", self._tag_for(line))
            total = int(self.txt_log.index("end-1c").split(".")[0])
            if total > 5000:
                self.txt_log.delete("1.0", f"{total - 4000}.0")
            self.txt_log.see(tk.END)
            self.txt_log.configure(state=tk.DISABLED)
        except tk.TclError:
            pass

    def _clear_log(self):
        try:
            self.txt_log.configure(state=tk.NORMAL)
            self.txt_log.delete("1.0", tk.END)
            self.txt_log.configure(state=tk.DISABLED)
        except tk.TclError:
            pass

    def _copy_log(self):
        try:
            content = self.txt_log.get("1.0", "end-1c")
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self._log("[UI] Contenuto della console copiato negli appunti.")
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ ispezione .cas
    def _inspect_current_workspace(self):
        ws = self.var_workspace.get().strip()
        asm_key = self._assembly_key()
        # `try_discover` non solleva: un'eccezione qui dentro diventerebbe un
        # "Exception in Tkinter callback" su stderr (callback `after`), invisibile
        # all'utente invece che mostrato nella console dell'app.
        cas_file, dat_file, discovery_error = try_discover(ws)
        self._update_file_labels(cas_file, dat_file)

        if not cas_file:
            self.stat_pid.configure(text="—")
            self.lbl_zone_summary.configure(
                text="Zone isolate: —  ·  nessun file .cas nella cartella selezionata")
            message = discovery_error or f"Nessun file .cas trovato in: {ws}"
            for line in message.splitlines():
                text = line.strip()
                if text:
                    self._log(f"[SCAN] {text}")
            return

        try:
            info = inspect_fluent_cas_zones(cas_file, requested_assembly=asm_key)
        except Exception as exc:
            self._log(f"[ERRORE] Lettura PID dal file .cas non riuscita: {exc}")
            return

        target_names = [z["name"] for z in info.get("target_zones", [])]
        domain_names = [z["name"] for z in info.get("domain_zones", [])]
        symmetric = bool(info.get("is_half_car_symmetric", False))
        size_mb = info.get("cas_size_mb", 0)

        self.stat_pid.configure(text=str(len(target_names)))
        self.lbl_zone_summary.configure(
            text=f"Zone isolate: {len(target_names)} PID  ·  "
                 f"modello {'half-car simmetrico' if symmetric else 'full-domain'}"
        )
        self._populate_zone_list(info, asm_key)
        self._log("─" * 76)
        self._log(f"[SCAN] {os.path.basename(cas_file)} · {size_mb} MB  |  "
                  f"assieme {asm_key.upper()}")
        self._log(f"       PID isolate ({len(target_names)}): "
                  f"{', '.join(target_names) if target_names else 'nessuna'}")
        if domain_names:
            self._log(f"       Galleria del vento esclusa ({len(domain_names)}): "
                      f"{', '.join(domain_names[:8])}{'…' if len(domain_names) > 8 else ''}")
        self._log("─" * 76)

    # ------------------------------------------------------------------ filesystem
    def _browse_workspace(self):
        initial = self.var_workspace.get().strip() or os.getcwd()
        chosen = filedialog.askdirectory(initialdir=initial, title="Seleziona cartella CFD")
        if chosen:
            self.var_workspace.set(os.path.abspath(chosen))
            self._inspect_current_workspace()

    def _browse_meta_exe(self):
        chosen = filedialog.askopenfilename(
            title="Seleziona eseguibile BETA CAE META Post",
            filetypes=[("META Post", "*.bat *.exe"), ("Tutti i file", "*.*")],
        )
        if chosen:
            self.var_meta_exe.set(chosen)
            self.stat_meta.configure(text="OK", fg=SUCCESS)
            self._log(f"[META] Eseguibile impostato: {chosen}")

    def _output_dir(self) -> str:
        ws = self.var_workspace.get().strip() or "."
        rel = self.config.get("project", {}).get("output_dir", "./output_diagnostics")
        return os.path.abspath(os.path.join(ws, rel))

    def _open_output(self):
        path = self._output_dir()
        try:
            os.makedirs(path, exist_ok=True)
            if hasattr(os, "startfile"):
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            messagebox.showerror("Cartella output", f"Impossibile aprire:\n{path}\n\n{exc}")

    def _open_meta_session(self):
        path = self.last_ses_path
        if not path or not os.path.isfile(path):
            messagebox.showinfo(
                "Sessione META",
                "La sessione interattiva sarà disponibile al termine della pipeline.")
            return
        try:
            if hasattr(os, "startfile"):
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            messagebox.showerror("Sessione META", f"Impossibile aprire:\n{path}\n\n{exc}")

    # ------------------------------------------------------------------ pipeline
    def _start_pipeline_thread(self):
        if self._busy:
            return
        ws = self.var_workspace.get().strip()
        if not os.path.isdir(ws):
            messagebox.showerror("Cartella non valida",
                                 f"La cartella di analisi non esiste:\n{ws}")
            return
        try:
            vinf = float(self.var_vinf.get().replace(",", "."))
            rho = float(self.var_rho.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Parametri non validi",
                                 "Velocità V∞ e densità aria devono essere valori numerici.")
            return

        asm_key = self._assembly_key()
        self.config.setdefault("project", {})["workspace_dir"] = ws
        self.config["project"]["assembly_type"] = asm_key
        self.config.setdefault("meta", {})["executable_path"] = (
            self.var_meta_exe.get().strip() or "auto")
        self.config.setdefault("reference_values", {})["velocity_inf"] = vinf
        self.config["reference_values"]["density_air"] = rho
        if self.var_apikey.get().strip():
            ai_cfg = self.config.setdefault("ai_vision", {})
        ai_cfg["api_key"] = self.var_apikey.get().strip()
        ai_cfg["provider"] = self.var_provider.get().strip().lower()
        self._apply_zone_selection_to_config()

        self._busy = True
        self.btn_run.set_enabled(False)
        self.btn_open_report.set_enabled(False)
        self.btn_open_meta.set_enabled(False)
        self._set_status("Elaborazione…", ACCENT, busy=True)

        self._log("")
        self._log("═" * 76)
        self._log(f"[AVVIO] Assieme {asm_key.upper()} · V∞ = {vinf:g} m/s · ρ = {rho:g} kg/m³")
        self._log(f"        Workspace: {ws}")
        self._t0 = time.monotonic()

        threading.Thread(
            target=self._run_task, args=(self.config, ws), daemon=True
        ).start()

    # -------------------------------------------------------------- verifica AI
    def _check_ai_config(self):
        """
        Esegue la diagnostica della configurazione AI (rete) in un thread.

        Non usa il config salvato ma i valori attuali della GUI (provider e chiave
        appena digitata), così si capisce subito se il problema è chiave, modello
        o payload. I risultati finiscono nella console dell'app.
        """
        if self._ai_check_running:
            return
        provider = self.var_provider.get().strip().lower()
        api_key = self.var_apikey.get().strip()
        if not api_key and provider == "deepseek":
            api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        ai_cfg = dict(self.config.get("ai_vision", {}) or {})
        ai_cfg.update({"provider": provider, "api_key": api_key})
        self._ai_check_running = True
        self._log("[AI-VERIFICA] provider '%s' — controllo in corso..." % provider)
        threading.Thread(target=self._run_ai_check, args=(ai_cfg,), daemon=True).start()

    def _run_ai_check(self, ai_cfg: dict):
        try:
            from analyzer.ai_vision_advisor import deepseek_check

            provider = str(ai_cfg.get("provider", "")).lower()
            if provider != "deepseek":
                self._log("[AI-VERIFICA] la diagnostica dettagliata copre il provider 'deepseek'; "
                          "per '%s' controlla chiave e modello nel config." % provider)
            info = deepseek_check(ai_cfg)
            self._log("[AI-VERIFICA] endpoint: %s" % info["base_url"])
            self._log("[AI-VERIFICA] modello richiesto: %s" % info["model"])
            self._log("[AI-VERIFICA] chiave: %s" % (
                "presente (" + info["key_masked"] + ")" if info["key_present"] else "ASSENTE"))
            if info["models_error"]:
                self._log("[AI-VERIFICA] errore su GET /models -> %s" % info["models_error"])
            elif info["models"]:
                self._log("[AI-VERIFICA] modelli disponibili: %s" % ", ".join(info["models"]))
                if info["model_available"] is False:
                    self._log("[AI-VERIFICA] ATTENZIONE: '%s' NON è tra i modelli disponibili."
                              % info["model"])
            else:
                self._log("[AI-VERIFICA] GET /models non ha restituito modelli.")
            if info["thinking_call"]:
                self._log("[AI-VERIFICA] chiamata con thinking: %s" % info["thinking_call"])
            if info["text_call"]:
                self._log("[AI-VERIFICA] chiamata senza thinking: %s" % info["text_call"])
            if info["models_error"] or (info["thinking_call"] and not info["thinking_call"].startswith("ok")):
                self._log("[AI-VERIFICA] suggerimento: chiave di platform.deepseek.com, modello tra quelli "
                          "elencati, credito disponibile.")
            else:
                self._log("[AI-VERIFICA] configurazione utilizzabile.")
        except Exception as exc:
            self._log("[AI-VERIFICA] errore imprevisto: %s" % exc)
        finally:
            self._ai_check_running = False

    def _run_task(self, cfg: dict, ws: str):
        import traceback
        try:
            result = self.pipeline_runner_fn(cfg, workspace_dir=ws, log_fn=self._log)
            self._ui(self._on_pipeline_success, result)
        except Exception as exc:
            self._ui(self._on_pipeline_error, exc, traceback.format_exc())

    def _ui(self, fn, *args):
        """Marshalling sicuro di una callback dal worker thread al thread Tk."""
        try:
            self.root.after(0, fn, *args)
        except Exception:
            pass

    def _on_pipeline_success(self, result):
        self._busy = False
        self.btn_run.set_enabled(True)
        elapsed = time.monotonic() - self._t0
        result = result or {}
        reports = result.get("reports", {}) or {}
        bundle = result.get("session_bundle", {}) or {}

        self.last_report_path = (
            reports.get("standalone_html_report") or reports.get("html_report"))
        ses_path = bundle.get("interactive_ses_path")
        if ses_path and os.path.isfile(ses_path):
            self.last_ses_path = ses_path
            self.btn_open_meta.set_enabled(True)

        report_ok = bool(self.last_report_path and os.path.isfile(self.last_report_path))
        self.btn_open_report.set_enabled(report_ok)
        self._set_status("Completato", SUCCESS)

        self._log("")
        self._log(f"[OK] Pipeline completata in "
                  f"{int(elapsed // 60)}m {int(elapsed % 60):02d}s")
        if report_ok:
            self._log(f"[REPORT] {self.last_report_path}")
            if reports.get("markdown_report"):
                self._log(f"[REPORT] {reports['markdown_report']}")
        else:
            self._log("[AVVISO] Report HTML non trovato: controlla il log della pipeline.")
        if self.last_ses_path:
            self._log(f"[META] Sessione interattiva: {self.last_ses_path}")

        if report_ok and self.var_auto_open.get():
            self.root.after(600, self._open_report)

    def _on_pipeline_error(self, exc, tb):
        self._busy = False
        self.btn_run.set_enabled(True)
        self._set_status("Errore", DANGER)
        self._log("")
        self._log(f"[ERRORE] Esecuzione pipeline non riuscita: {exc}")
        if tb:
            self._log(tb)
        messagebox.showerror("Errore di esecuzione", str(exc))

    # ------------------------------------------------------------------ apertura report
    def _open_report(self):
        if not self.last_report_path or not os.path.isfile(self.last_report_path):
            messagebox.showinfo(
                "Report non disponibile",
                "Esegui prima la pipeline: il report HTML verrà generato al termine.")
            return
        webbrowser.open("file:///" + self.last_report_path.replace(os.sep, "/"))

    def _on_close(self):
        if self._busy and not messagebox.askyesno(
                "Uscita", "La pipeline è ancora in esecuzione.\nUscire comunque?"):
            return
        self.root.destroy()


# ==============================================================================
#  ENTRYPOINT GUI
# ==============================================================================
def _apply_window_icon(root):
    """
    Imposta l'icona della finestra da `assets/FS-MetaPostDiag.ico`.

    Funziona sia dai sorgenti sia dall'eseguibile PyInstaller (dove le risorse
    stanno in sys._MEIPASS). Su piattaforme che non supportano il formato .ico
    l'errore viene ignorato: l'icona e' estetica, non deve impedire l'avvio.
    """
    try:
        from config_bridge import app_dir, bundled_dir

        for base in (bundled_dir(), app_dir()):
            icon_path = os.path.join(base, "assets", "FS-MetaPostDiag.ico")
            if os.path.isfile(icon_path):
                root.iconbitmap(default=icon_path)
                return icon_path
    except Exception:
        return None
    return None


def launch_gui(config: dict, pipeline_runner_fn):
    root = tk.Tk()
    _apply_window_icon(root)
    AeroDiagnosticsGUI(root, config, pipeline_runner_fn)
    root.mainloop()




