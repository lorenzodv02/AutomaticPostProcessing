# -*- coding: utf-8 -*-
"""
Launcher grafico di FS-MetaPostDiag (Tkinter, brand UniNa Corse).

Una finestra, quattro modalita':

    Singolo caso   report completo su una cartella con .cas/.dat
    Multi-caso     estrazione batch dai .cas + tabelle + suite (con tabella casi)
    Suite          su una cartella dati gia' pronta
    Geometria      solo geometria di un caso

Le lavorazioni girano in un thread, il log arriva in console e la tabella dei
casi si aggiorna man mano. L'annullamento e' cooperativo: si ferma tra un caso
e l'altro (una simulazione in corso non viene interrotta a meta').

Si apre con `FS-MetaPostDiag.exe --launcher`.
"""
from __future__ import annotations

import os
import queue
import re
import sys
import threading
import time
import webbrowser

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import brand


def _ui_components():
    """Importa i widget di brand solo quando serve (matplotlib non e' una
    dipendenza dei test: l'import a livello di modulo romperebbe la CI)."""
    from gui_app import GradientButton, _BrandBars

    return GradientButton, _BrandBars


def _families():
    try:
        return brand.families()
    except Exception:  # pragma: no cover - difesa
        return {"ui": "Segoe UI", "num": "Consolas", "display": "Segoe UI"}


FAMILIES = _families()
FONT_UI = FAMILIES["ui"]
FONT_NUM = FAMILIES["num"]

ASSEMBLIES = [("undertray", "solo fondo"), ("front_wing", "ala anteriore"),
              ("rear_wing", "ala posteriore"), ("full_car", "vettura completa")]
ASSEMBLY_LABELS = {value: label for value, label in ASSEMBLIES}
ASSEMBLY_VALUES = {label: value for value, label in ASSEMBLIES}


def _frozen_exe() -> str:
    # utile in sviluppo o in ambienti che confinano l'exe dentro il progetto
    override = os.environ.get("FS_METAPOSTDIAG_EXE")
    if override and os.path.isfile(override):
        return os.path.abspath(override)
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "dist", "FS-MetaPostDiag.exe"))


def _format_seconds(seconds) -> str:
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "-"
    if value < 60:
        return "%.0f s" % value
    return "%d m %02d s" % (int(value // 60), int(value % 60))


def ensure_batch_path():
    """Mette la cartella dei moduli batch su sys.path (sorgenti o _MEIPASS)."""
    here = os.path.dirname(os.path.abspath(__file__))
    bundle = getattr(sys, "_MEIPASS", None)
    for folder in (os.path.join(os.path.dirname(here), "batch"),
                   os.path.join(bundle, "batch") if bundle else ""):
        if folder and os.path.isdir(folder) and folder not in sys.path:
            sys.path.insert(0, folder)


def batch_plan(root_dir, out_dir, iter_pattern=None):
    """
    Elenca i casi da elaborare sotto `root_dir` riusando le regole del batch.

    Restituisce righe {case_id, relpath, dir, choice}. Le cartelle con solo i
    file di partenza risultano SCARTATO (come nel batch da riga di comando).
    """
    ensure_batch_path()
    import batch_extract  # noqa: WPS433

    pattern = iter_pattern or batch_extract.DEFAULT_ITER_PATTERN
    iter_re = re.compile(pattern, re.IGNORECASE)
    rows = []
    for case_dir in batch_extract.find_case_dirs(root_dir, out_dir):
        cas, dat = batch_extract.list_files(case_dir)
        choice = batch_extract.pick_inputs(case_dir, iter_re)
        rows.append({
            "case_id": batch_extract.case_id_for(case_dir, root_dir),
            "relpath": os.path.relpath(case_dir, root_dir),
            "dir": case_dir,
            "cas_presenti": "; ".join(cas),
            "dat_presenti": "; ".join(dat),
            "choice": choice,
        })
    return rows


class _QueueWriter:
    """Sostituisce sys.stdout durante il lavoro: ogni riga finisce in console."""

    def __init__(self, sink):
        self._sink = sink

    def write(self, text):
        if text:
            self._sink(text)

    def flush(self):
        pass


class LauncherApp:
    def __init__(self, cfg, args, pipeline):
        self.cfg = cfg
        self.args = args
        self.pipeline = pipeline
        self.queue = queue.Queue()
        self.worker = None
        self.busy = False
        self.cancel_requested = False
        self.last_output_dir = ""
        self.mode = "single"

        self.root = tk.Tk()
        self.root.title("FS · MetaPostDiag — Launcher")
        self.root.geometry("1060x820")
        self.root.minsize(940, 720)
        self.root.configure(bg=brand.NAVY_DEEP)
        self._set_window_icon()
        self._GradientButton, self._BrandBars = _ui_components()
        self._build()
        self._show_mode("single")
        self.root.after(120, self._poll)

    # ------------------------------------------------------------------ layout
    def _build(self):
        head = tk.Frame(self.root, bg=brand.NAVY_DEEP)
        head.pack(fill="x", padx=26, pady=(18, 4))
        self._mark = self._load_mark()
        if self._mark is not None:
            tk.Label(head, image=self._mark, bg=brand.NAVY_DEEP).pack(side="left", padx=(0, 16))
        titles = tk.Frame(head, bg=brand.NAVY_DEEP)
        titles.pack(side="left")
        tk.Label(titles, text="FS · MetaPostDiag", bg=brand.NAVY_DEEP, fg=brand.ICE,
                 font=(FONT_UI, 19, "bold")).pack(anchor="w")
        tk.Label(titles, text="Launcher  ·  UniNa Corse  ·  Aerodynamics & Cooling",
                 bg=brand.NAVY_DEEP, fg=brand.TEXT_MUTED,
                 font=(FONT_UI, 10)).pack(anchor="w")
        right = tk.Frame(head, bg=brand.NAVY_DEEP)
        right.pack(side="right")
        self._mark_word = self._load_png("wordmark-white.png", height=26)
        if self._mark_word is not None:
            tk.Label(right, image=self._mark_word, bg=brand.NAVY_DEEP).pack(anchor="e")
        self._BrandBars(right, width=150, height=38).pack(anchor="e", pady=(2, 0))
        tk.Frame(self.root, bg=brand.GOLD, height=3).pack(fill="x", padx=26, pady=(8, 12))

        modes = tk.Frame(self.root, bg=brand.NAVY_DEEP)
        modes.pack(fill="x", padx=26)
        self.mode_buttons = {}
        for key, label in (("single", "Singolo caso"), ("batch", "Multi-caso"),
                           ("suite", "Suite"), ("geometry", "Geometria")):
            button = tk.Button(modes, text=label, relief="flat", bd=0,
                               font=(FONT_UI, 10, "bold"), padx=16, pady=8, cursor="hand2",
                               bg=brand.NAVY_PANEL, fg=brand.ICE,
                               activebackground=brand.VIOLET, activeforeground=brand.WHITE,
                               command=lambda name=key: self._show_mode(name))
            button.pack(side="left", padx=(0, 8))
            self.mode_buttons[key] = button
        self._style_ttk()

        self.body = tk.Frame(self.root, bg=brand.NAVY_DEEP)
        self.body.pack(fill="both", expand=True, padx=26, pady=(12, 4))
        self.frames = {
            "single": self._build_single(),
            "batch": self._build_batch(),
            "suite": self._build_suite(),
            "geometry": self._build_geometry(),
        }

        bottom = tk.Frame(self.root, bg=brand.NAVY_DEEP)
        bottom.pack(fill="x", padx=26, pady=(2, 6))
        self.status = tk.Label(bottom, text="Pronto.", bg=brand.NAVY_DEEP, fg=brand.TEXT_MUTED,
                               font=(FONT_UI, 9), anchor="w")
        self.status.pack(side="left")
        self.cancel_button = tk.Button(
            bottom, text="Annulla", relief="flat", bd=0, padx=14, pady=5,
            font=(FONT_UI, 9, "bold"), bg=brand.NAVY_PANEL, fg=brand.ICE,
            activebackground=brand.DANGER, activeforeground=brand.WHITE,
            cursor="hand2", command=self._request_cancel, state="disabled")
        self.cancel_button.pack(side="right")

        console = tk.Frame(self.root, bg=brand.NAVY_PANEL)
        console.pack(fill="both", expand=True, padx=26, pady=(0, 16))
        tk.Frame(console, bg=brand.GOLD, height=3).pack(fill="x")
        header = tk.Frame(console, bg=brand.NAVY_PANEL)
        header.pack(fill="x", padx=12, pady=(6, 2))
        tk.Label(header, text="ATTIVITÀ", bg=brand.NAVY_PANEL, fg=brand.TEXT_MUTED,
                 font=(FONT_UI, 8, "bold")).pack(side="left")
        log_frame = tk.Frame(console, bg=brand.NAVY_PANEL)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(2, 10))
        scrollbar = tk.Scrollbar(log_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        self.log = tk.Text(log_frame, bg=brand.INPUT_BG, fg=brand.ICE, bd=0,
                           insertbackground=brand.ICE, font=(FONT_NUM, 9),
                           wrap="word", state="disabled", yscrollcommand=scrollbar.set,
                           height=9)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.log.yview)

    def _load_png(self, name, height=None):
        """Carica una PNG di assets/ ridimensionata in altezza (PIL, fallback Tk)."""
        path = brand.asset_path(name)
        if not path:
            return None
        try:
            from PIL import Image, ImageTk

            with Image.open(path) as image:
                if height:
                    ratio = height / float(image.height)
                    size = (max(1, int(image.width * ratio)), height)
                    resized = image.convert("RGBA").resize(size, Image.LANCZOS)
                else:
                    resized = image.convert("RGBA")
                return ImageTk.PhotoImage(resized)
        except Exception:  # niente PIL: si usa Tk puro
            try:
                image = tk.PhotoImage(file=path)
            except tk.TclError:
                return None
            if height:
                factor = max(1, round(image.height() / float(height)))
                return image.subsample(factor, factor)
            return image

    def _load_mark(self):
        return self._load_png("uc-monogram-white.png", height=54)

    def _set_window_icon(self):
        """Icona della finestra: .ico + PNG dell'app (come la GUI principale)."""
        icon_path = brand.asset_path("FS-MetaPostDiag.ico")
        if icon_path:
            try:
                self.root.iconbitmap(default=icon_path)
            except tk.TclError:
                pass
        png = brand.asset_path("FS-MetaPostDiag.png")
        if png:
            try:
                from PIL import Image, ImageTk

                with Image.open(png) as image:
                    icon = ImageTk.PhotoImage(image.convert("RGBA"))
                self.root.iconphoto(True, icon)
                self._window_icon = icon
            except Exception:
                pass

    def _style_ttk(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Suite.Treeview", background=brand.NAVY_PANEL,
                        fieldbackground=brand.NAVY_PANEL, foreground=brand.ICE,
                        rowheight=22, font=(FONT_NUM, 9), borderwidth=0)
        style.configure("Suite.Treeview.Heading", background=brand.NAVY,
                        foreground=brand.ICE, font=(FONT_UI, 9, "bold"), borderwidth=0)
        style.map("Suite.Treeview", background=[("selected", brand.VIOLET)],
                  foreground=[("selected", brand.WHITE)])
        style.configure("Suite.Horizontal.TProgressbar", troughcolor=brand.NAVY_DEEP,
                        background=brand.GOLD, thickness=6, borderwidth=0)

    def _card(self, parent, hint, expand=False):
        """Card senza cornice: superficie piena + barretta d'accento gialla."""
        card = tk.Frame(parent, bg=brand.NAVY_PANEL)
        card.pack(fill="both" if expand else "x", expand=expand, pady=(0, 12))
        tk.Frame(card, bg=brand.GOLD, height=3).pack(fill="x")
        tk.Label(card, text=hint, bg=brand.NAVY_PANEL, fg=brand.TEXT_MUTED,
                 font=(FONT_UI, 9), anchor="w", justify="left").pack(
            fill="x", padx=14, pady=(8, 4))
        return card

    def _inner(self, card):
        inner = tk.Frame(card, bg=brand.NAVY_PANEL)
        inner.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        return inner

    def _folder_row(self, parent, label, attribute):
        row = tk.Frame(parent, bg=brand.NAVY_PANEL)
        row.pack(fill="x", pady=(0, 8))
        tk.Label(row, text=label, width=16, anchor="w", bg=brand.NAVY_PANEL,
                 fg=brand.TEXT_MUTED, font=(FONT_UI, 9)).pack(side="left")
        entry = tk.Entry(row, bg=brand.INPUT_BG, fg=brand.ICE, bd=0,
                         insertbackground=brand.ICE, font=(FONT_UI, 10))
        entry.pack(side="left", fill="x", expand=True, ipady=5)
        setattr(self, attribute, entry)
        tk.Button(row, text="Sfoglia…", relief="flat", bd=0, padx=10, pady=3,
                  bg=brand.VIOLET, fg=brand.WHITE, activebackground=brand.VIOLET_RAMP[2],
                  activeforeground=brand.WHITE, cursor="hand2", font=(FONT_UI, 9),
                  command=lambda: self._browse(entry)).pack(side="left", padx=(6, 0))
        return entry

    def _browse(self, entry):
        folder = filedialog.askdirectory(parent=self.root, title="Scegli la cartella")
        if folder:
            entry.delete(0, "end")
            entry.insert(0, folder)

    def _check(self, parent, text, attribute, default=False):
        var = tk.BooleanVar(value=default)
        setattr(self, attribute, var)
        tk.Checkbutton(parent, text=text, variable=var, bg=brand.NAVY_PANEL, fg=brand.ICE,
                       activebackground=brand.NAVY_PANEL, activeforeground=brand.ICE,
                       selectcolor=brand.INPUT_BG, font=(FONT_UI, 9),
                       borderwidth=0, highlightthickness=0).pack(anchor="w", pady=1)
        return var

    # ------------------------------------------------------------------- modi
    def _build_single(self):
        card = self._card(self.body, "Report completo su una cartella con il caso "
                                     "(.cas + .dat): mesh, forze, immagini, META, report HTML/PDF.")
        body = self._inner(card)
        self._folder_row(body, "Cartella del caso", "single_dir")
        self._check(body, "Salta il rendering META (più veloce)", "single_skip_meta")
        self._check(body, "Apri il report alla fine", "single_open_report", default=True)
        self._GradientButton(body, text="Avvia analisi", command=self._start_single,
                       width=240, height=42).pack(anchor="w", pady=(8, 2))
        return card

    def _build_batch(self):
        wrapper = tk.Frame(self.body, bg=brand.NAVY_DEEP)
        card = self._card(wrapper, "Estrazione batch dai .cas sotto una cartella radice: "
                                   "un caso per sottocartella con .cas + .dat. Poi tabelle e suite.")
        body = self._inner(card)
        self._folder_row(body, "Cartella radice", "batch_root")
        self._folder_row(body, "Cartella dati", "batch_out")
        row = tk.Frame(body, bg=brand.NAVY_PANEL)
        row.pack(fill="x", pady=(0, 8))
        tk.Label(row, text="Assieme", width=16, anchor="w", bg=brand.NAVY_PANEL,
                 fg=brand.TEXT_MUTED, font=(FONT_UI, 9)).pack(side="left")
        self.batch_assembly = tk.StringVar(value=ASSEMBLY_LABELS["full_car"])
        menu = tk.OptionMenu(row, self.batch_assembly,
                             *[label for _name, label in ASSEMBLIES])
        menu.configure(bg=brand.INPUT_BG, fg=brand.ICE, activebackground=brand.VIOLET,
                       activeforeground=brand.WHITE, highlightthickness=0, bd=0,
                       font=(FONT_UI, 9))
        menu["menu"].configure(bg=brand.NAVY_PANEL, fg=brand.ICE,
                               activebackground=brand.VIOLET, activeforeground=brand.WHITE,
                               font=(FONT_UI, 9))
        menu.pack(side="left")
        self._check(body, "Rifai anche i casi già fatti", "batch_force")
        self._check(body, "Genera anche i report completi per ogni caso", "batch_full")
        self._GradientButton(body, text="Avvia batch", command=self._start_batch,
                       width=240, height=42).pack(anchor="w", pady=(8, 2))

        table_card = self._card(wrapper, "Casi in elaborazione", expand=True)
        inner = self._inner(table_card)
        self.tree = ttk.Treeview(inner, columns=("caso", "stato", "tempo"), show="headings",
                                 style="Suite.Treeview", height=5)
        for column, label, width in (("caso", "Caso", 470), ("stato", "Stato", 200),
                                     ("tempo", "Tempo", 90)):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, anchor="w" if column != "tempo" else "e")
        self.tree.pack(fill="both", expand=True)
        self.progress = ttk.Progressbar(inner, style="Suite.Horizontal.TProgressbar",
                                        mode="determinate", maximum=1, value=0)
        self.progress.pack(fill="x", pady=(8, 0))
        return wrapper

    def _build_suite(self):
        card = self._card(self.body, "Suite su una cartella dati già pronta (quella con "
                                     "dataset.csv): geometria, tabelle e dashboard.")
        body = self._inner(card)
        self._folder_row(body, "Cartella dati", "suite_dir")
        self._check(body, "I report completi per caso sono già stati fatti",
                    "suite_reports_done", default=True)
        self._GradientButton(body, text="Avvia suite", command=self._start_suite,
                       width=240, height=42).pack(anchor="w", pady=(8, 2))
        return card

    def _build_geometry(self):
        card = self._card(self.body, "Solo geometria di un caso: profili del fondo, ali, "
                                     "superfici per famiglia. Nessun report.")
        body = self._inner(card)
        self._folder_row(body, "Cartella del caso", "geometry_dir")
        self._GradientButton(body, text="Calcola geometria", command=self._start_geometry,
                       width=240, height=42).pack(anchor="w", pady=(8, 2))
        return card

    def _show_mode(self, mode):
        if self.busy:
            return
        for _key, frame in self.frames.items():
            frame.pack_forget()
        self.frames[mode].pack(fill="both", expand=True)
        self.mode = mode
        for key, button in self.mode_buttons.items():
            active = key == mode
            button.configure(bg=brand.GOLD if active else brand.NAVY_PANEL,
                             fg=brand.NAVY if active else brand.ICE)

    # ------------------------------------------------------------------- log
    def _append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "text":
                    self._append(payload)
                elif kind == "status":
                    self.status.configure(text=payload)
                elif kind == "case":
                    case_id, state, seconds = payload
                    if self.tree.exists(case_id):
                        self.tree.item(case_id, values=(case_id, state, _format_seconds(seconds)))
                    else:
                        self.tree.insert("", "end", iid=case_id,
                                         values=(case_id, state, _format_seconds(seconds)))
                elif kind == "progress":
                    done, total = payload
                    self.progress.configure(maximum=max(total, 1), value=done)
                elif kind == "done":
                    self._finish(payload)
                elif kind == "error":
                    self._finish(payload, error=True)
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(120, self._poll)

    def _finish(self, message, error=False):
        self.busy = False
        self.cancel_button.configure(state="disabled")
        for button in self.mode_buttons.values():
            button.configure(state="normal")
        self.status.configure(text="Errore." if error else "Completato.")
        if message:
            self._append("\n" + str(message) + "\n")
        if self.last_output_dir and os.path.isdir(self.last_output_dir):
            self._append("Cartella risultati: %s\n" % self.last_output_dir)

    def _request_cancel(self):
        if not self.busy:
            return
        self.cancel_requested = True
        self.status.configure(text="Annullamento richiesto: mi fermo dopo il caso in corso…")

    # ---------------------------------------------------------------- worker
    def _start_job(self, name, function):
        if self.busy:
            return
        self.busy = True
        self.cancel_requested = False
        self.cancel_button.configure(state="normal")
        for button in self.mode_buttons.values():
            button.configure(state="disabled")
        self.status.configure(text="%s in corso…" % name)
        self._append("\n=== %s ===\n" % name)
        self.worker = threading.Thread(target=self._run, args=(function,), daemon=True)
        self.worker.start()

    def _run(self, function):
        original = sys.stdout
        sys.stdout = _QueueWriter(lambda text: self.queue.put(("text", text)))
        try:
            function()
            self.queue.put(("done", "Lavoro completato."))
        except Exception as exc:  # noqa: BLE001 - mostrato in finestra e log
            self.queue.put(("done", "Errore: %s" % exc))
            self.queue.put(("error", None))
        finally:
            sys.stdout = original

    # ------------------------------------------------------------------ azioni
    def _start_single(self):
        folder = self.single_dir.get().strip().strip('"')
        if not os.path.isdir(folder):
            messagebox.showwarning("Cartella mancante", "Scegli la cartella del caso.", parent=self.root)
            return
        skip_meta = self.single_skip_meta.get()
        open_report = self.single_open_report.get()
        self.last_output_dir = os.path.join(folder, "output_diagnostics")

        def job():
            import copy

            local = copy.deepcopy(self.cfg)
            local.setdefault("project", {})["workspace_dir"] = folder
            result = self.pipeline(local, workspace_dir=folder, force_meta_batch=not skip_meta)
            reports = (result or {}).get("reports") or {}
            html = reports.get("html_report") or reports.get("standalone_html_report")
            self.queue.put(("text", "\nReport: %s\n" % (html or "(non trovato)")))
            if open_report and html and os.path.isfile(html):
                webbrowser.open("file:///" + html.replace(os.sep, "/"))

        self._start_job("Singolo caso", job)

    def _start_batch(self):
        root_dir = self.batch_root.get().strip().strip('"')
        out_dir = self.batch_out.get().strip().strip('"') or os.path.join(root_dir, "_dati_batch")
        if not os.path.isdir(root_dir):
            messagebox.showwarning("Cartella mancante", "Scegli la cartella radice delle analisi.",
                                   parent=self.root)
            return
        assembly = ASSEMBLY_VALUES.get(self.batch_assembly.get(), "full_car")
        force = self.batch_force.get()
        full = self.batch_full.get()
        self.last_output_dir = out_dir
        for item in self.tree.get_children():
            self.tree.delete(item)

        def job():
            import copy
            import csv
            import json

            from meta_driver.suite_mode import run_suite

            rows = batch_plan(root_dir, out_dir)
            to_run = [row for row in rows if row["choice"]["stato"] != "SCARTATO"]
            skipped = [row for row in rows if row["choice"]["stato"] == "SCARTATO"]
            self.queue.put(("text", "Cartelle trovate: %d | da elaborare: %d | scartate: %d\n"
                           % (len(rows), len(to_run), len(skipped))))
            import batch_extract

            os.makedirs(out_dir, exist_ok=True)
            temp_dir = os.path.join(out_dir, "_tmp")
            os.makedirs(temp_dir, exist_ok=True)
            env = dict(os.environ)
            env["TEMP"] = temp_dir
            env["TMP"] = temp_dir
            metadata_path = os.path.join(out_dir, "metadata.csv")
            if not os.path.isfile(metadata_path):
                with open(metadata_path, "w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.writer(handle, delimiter=";")
                    writer.writerow(["case_id", "nota", "velocita_nominale_ms", "parametro_1",
                                     "parametro_2", "parametro_3", "parametro_4"])
                    for row in to_run:
                        writer.writerow([row["case_id"], "", "", "", "", "", ""])
                self.queue.put(("text", "Template metadati creato: %s\n" % metadata_path))

            results = []
            total = len(to_run)
            for position, row in enumerate(to_run, 1):
                if self.cancel_requested:
                    self.queue.put(("text", "\nAnnullato: %d casi elaborati.\n" % (position - 1)))
                    break
                case_id = row["case_id"]
                choice = row["choice"]
                target = os.path.join(out_dir, case_id + ".json")
                self.queue.put(("status", "Caso %d/%d: %s" % (position, total, case_id)))
                self.queue.put(("case", (case_id, "in corso", 0)))
                if os.path.isfile(target) and not force:
                    payload = batch_extract.read_json(target)
                    kpis = (payload.get("physics_data") or {}).get("summary_kpis") or {}
                    results.append({"case_id": case_id, "relpath": row["relpath"],
                                    "stato": "GIA_FATTO", "secondi": 0,
                                    "downforce_N": kpis.get("downforce_total_N", kpis.get("downforce_N")),
                                    "drag_N": kpis.get("drag_total_N", kpis.get("drag_N"))})
                    self.queue.put(("case", (case_id, "già fatto", 0)))
                    self.queue.put(("progress", (position, total)))
                    continue
                run_dir = batch_extract.prepare_run_dir(row["dir"], choice)
                code, output, seconds = batch_extract.run_case(
                    _frozen_exe(), run_dir, assembly, None, 3600, env)
                diag = os.path.join(run_dir, "output_diagnostics", "cfd_extracted_data.json")
                payload = batch_extract.read_json(diag) if os.path.isfile(diag) else {}
                if payload:
                    with open(target, "w", encoding="utf-8") as handle:
                        json.dump(payload, handle, ensure_ascii=False)
                status, reason = batch_extract.status_from_output(code, output, payload)
                kpis = (payload.get("physics_data") or {}).get("summary_kpis") or {}
                results.append({"case_id": case_id, "relpath": row["relpath"],
                                "stato": status, "secondi": round(seconds, 1),
                                "downforce_N": kpis.get("downforce_total_N", kpis.get("downforce_N")),
                                "drag_N": kpis.get("drag_total_N", kpis.get("drag_N"))})
                with open(os.path.join(out_dir, case_id + ".log"), "w", encoding="utf-8",
                          errors="replace") as handle:
                    handle.write("== %s ==\ncartella: %s\nfile: %s + %s (%s)\ncodice: %s | secondi: %.1f\n\n%s"
                                 % (case_id, row["dir"], choice["cas"], choice["dat"],
                                    choice["modo"], code, seconds, output))
                self.queue.put(("case", (case_id, status + (" (%s)" % reason if reason else ""),
                                         round(seconds, 1))))
                self.queue.put(("progress", (position, total)))
                batch_extract.remove_run_dir(row["dir"], choice, keep_reports=False)
                self.queue.put(("text", "[%d/%d] %s · %s · %s\n"
                               % (position, total, case_id, status, _format_seconds(seconds))))

            index_path = os.path.join(out_dir, "index.csv")
            with open(index_path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(["case_id", "relpath", "stato", "secondi", "downforce_N", "drag_N"])
                for row in results:
                    writer.writerow([row["case_id"], row["relpath"], row["stato"],
                                     row["secondi"], row.get("downforce_N"), row.get("drag_N")])
            self.queue.put(("text", "\nIndice: %s\n" % index_path))
            ensure_batch_path()
            import check_dataset
            import make_tables

            for module, name in ((make_tables, "make_tables"), (check_dataset, "check_dataset")):
                saved_argv = sys.argv
                sys.argv = [name, "--data", out_dir]
                try:
                    module.main()
                except SystemExit as exc:
                    if exc.code not in (0, None):
                        self.queue.put(("text", "%s terminato con codice %s\n" % (name, exc.code)))
                finally:
                    sys.argv = saved_argv
            self.queue.put(("status", "Suite: geometria, tabelle e dashboard…"))
            self.queue.put(("text", "\nSuite:\n"))
            suite_args = type("Args", (), {"workspace": out_dir, "force": False,
                                           "skip_process": not full, "no_meta_batch": True,
                                           "only": None})()
            run_suite(copy.deepcopy(self.cfg), suite_args, self.pipeline)
            self.queue.put(("done", "Batch completato."))

        self._start_job("Multi-caso", job)

    def _start_suite(self):
        folder = self.suite_dir.get().strip().strip('"')
        if not os.path.isdir(folder):
            messagebox.showwarning("Cartella mancante", "Scegli la cartella dati.", parent=self.root)
            return
        skip_process = self.suite_reports_done.get()
        self.last_output_dir = folder

        def job():
            from meta_driver.suite_mode import run_suite

            suite_args = type("Args", (), {"workspace": folder, "force": False,
                                           "skip_process": skip_process,
                                           "no_meta_batch": True, "only": None})()
            run_suite(self.cfg, suite_args, self.pipeline)
            webbrowser.open("file:///" + os.path.join(folder, "Aero_Suite.html").replace(os.sep, "/"))

        self._start_job("Suite", job)

    def _start_geometry(self):
        folder = self.geometry_dir.get().strip().strip('"')
        if not os.path.isdir(folder):
            messagebox.showwarning("Cartella mancante", "Scegli la cartella del caso.", parent=self.root)
            return
        self.last_output_dir = os.path.join(folder, "output_diagnostics")

        def job():
            from meta_driver.suite_mode import geometry_for_workspace

            result = geometry_for_workspace(self.cfg, folder)
            payload = result["payload"]
            geometry = payload.get("geometry") or {}
            self.queue.put(("text", "Caso %s: %d zone | fondo %s | ali %s/%s\n"
                           % (payload["case"], len(geometry.get("zones") or []),
                              "sì" if (geometry.get("floor") or {}).get("available") else "no",
                              "sì" if (geometry.get("wings") or {}).get("front", {}).get("available") else "no",
                              "sì" if (geometry.get("wings") or {}).get("rear", {}).get("available") else "no")))
            self.queue.put(("text", "Scritto: %s\n" % result["path"]))

        self._start_job("Geometria", job)


def _hide_console_window():
    """Nasconde la console creata dal doppio clic (solo eseguibile Windows)."""
    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetConsoleWindow()
        if handle:
            ctypes.windll.user32.ShowWindow(handle, 0)
    except Exception:
        pass


def launch_launcher_gui(cfg, args, pipeline, hide_console: bool = False) -> int:
    app = LauncherApp(cfg, args, pipeline)
    if hide_console:
        _hide_console_window()
    app.root.mainloop()
    return 0
