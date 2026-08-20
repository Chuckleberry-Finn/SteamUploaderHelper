#!/usr/bin/env python3
# app.py — PZ SteamUploader Helper GUI entry point.

# ── Startup check ──────────────────────────────────────────────────────────────
import sys

def _check_environment():
    errors = []
    if sys.version_info < (3, 8):
        errors.append(
            "Python 3.8+ is required — you are running " + sys.version.split()[0] + ".\n"
            "Download a newer version from https://python.org/downloads/"
        )
    try:
        import tkinter  # noqa: F401
    except ModuleNotFoundError:
        errors.append(
            "tkinter is not available in this Python installation.\n\n"
            "  Windows : Re-run the Python installer and tick 'tcl/tk and IDLE'.\n"
            "  macOS   : Install Python from https://python.org (includes Tk).\n"
            "  Ubuntu  : sudo apt install python3-tk\n"
            "  Fedora  : sudo dnf install python3-tkinter"
        )
    if errors:
        msg = "\n\n".join(errors)
        print("=" * 60, file=sys.stderr)
        print("PZ Toolkit — startup error", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(msg, file=sys.stderr)
        try:
            import tkinter as _tk, tkinter.messagebox as _mb
            _r = _tk.Tk(); _r.withdraw()
            _mb.showerror("PZ Toolkit — startup error", msg)
            _r.destroy()
        except Exception:
            pass
        sys.exit(1)

_check_environment()

# ── Imports ────────────────────────────────────────────────────────────────────
import io, os, re as import_re, threading, math
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox, colorchooser
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import regex_tool as rt
import uploader   as up


# ═══════════════════════════════════════════════════════════════════════════════
#  Palette & font
# ═══════════════════════════════════════════════════════════════════════════════

BG        = "#3c3c3c"
PANEL     = "#505456"
BORDER    = "#272727"
ACCENT    = "#828282"
ACCENT2   = "#808080"
SUCCESS   = "#6dce51"
WARN      = "#fdc137"
DANGER    = "#ff8a8a"
FG        = "#dbdbdb"
FG_DIM    = "#d2d2d2"
SELECT_BG = "#214283"
DANGER_BG = "#4b2c2b"
DANGER_BG_ACTIVE = "#5c3634"
ON_ACCENT = "#f5f5f5"

PALETTE_NAMES    = ["BG", "PANEL", "BORDER", "FG", "FG_DIM",
                    "ACCENT", "WARN", "SUCCESS", "DANGER", "ACCENT2",
                    "SELECT_BG", "ON_ACCENT", "DANGER_BG", "DANGER_BG_ACTIVE"]
DEFAULT_PALETTE  = {name: globals()[name] for name in PALETTE_NAMES}

_MONO_CANDIDATES = [
    "Cascadia Code", "Cascadia Mono", "Consolas",
    "Menlo", "Monaco", "DejaVu Sans Mono",
    "Liberation Mono", "Lucida Console", "Courier New",
]

def _resolve_mono() -> str:
    available = set(tkfont.families())
    for name in _MONO_CANDIDATES:
        if name in available:
            return name
    return "Courier New"


# ═══════════════════════════════════════════════════════════════════════════════
#  GUI-layer mod row  (wraps uploader.ModInfo with checkbox state)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ModRow:
    # Pairs a pure ModInfo with the GUI selection state.
    info:     up.ModInfo
    var:      tk.BooleanVar
    affected: bool = False

    @property
    def path(self):    return self.info.path
    @property
    def name(self):    return self.info.name
    @property
    def title(self):   return self.info.title
    @property
    def mod_id(self):  return self.info.mod_id

    def matches(self, pattern: str, field: str) -> bool:
        return self.info.matches(pattern, field)


# ═══════════════════════════════════════════════════════════════════════════════
#  Stdout redirector  (pipes upload print() output into the log widget)
# ═══════════════════════════════════════════════════════════════════════════════

class _TextRedirector(io.TextIOBase):
    def __init__(self, widget: tk.Text):
        self._w = widget

    def write(self, s: str) -> int:
        self._w.after(0, self._append, s)
        return len(s)

    def _append(self, s: str):
        self._w.configure(state="normal")
        self._w.insert(tk.END, s)
        self._w.see(tk.END)
        self._w.configure(state="disabled")

    def flush(self):
        pass


# ═══════════════════════════════════════════════════════════════════════════════
#  Scrollable checkbox list  (upload tab)
# ═══════════════════════════════════════════════════════════════════════════════

class _CheckList(tk.Frame):

    def __init__(self, master, **kw):
        kw.setdefault("bg", PANEL)
        super().__init__(master, **kw)
        self._canvas = tk.Canvas(self, bg=PANEL, borderwidth=0, highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._inner = tk.Frame(self._canvas, bg=PANEL)
        self._win   = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")

        self._inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind("<Enter>",
            lambda _: self._canvas.bind_all("<MouseWheel>", self._on_scroll))
        self._canvas.bind("<Leave>",
            lambda _: self._canvas.unbind_all("<MouseWheel>"))

    def _on_inner_configure(self, e):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, e):
        self._canvas.itemconfig(self._win, width=e.width)

    def _on_scroll(self, e):
        self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    def clear(self):
        for w in self._inner.winfo_children():
            w.destroy()
        self._canvas.yview_moveto(0)

    def add_row(self, var: tk.BooleanVar, label: str,
                sub: str = "", badge: str = "", badge_colour: str = FG_DIM):
        row = tk.Frame(self._inner, bg=PANEL)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Checkbutton(row, variable=var, style="Panel.TCheckbutton").pack(side="left")
        if badge:
            tk.Label(row, text=badge, width=2, bg=PANEL,
                     fg=badge_colour, font=("Segoe UI", 9)).pack(side="right", padx=(4, 0))
        col = tk.Frame(row, bg=PANEL)
        col.pack(side="left", fill="x", expand=True)
        tk.Label(col, text=label, bg=PANEL, fg=FG,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        if sub:
            tk.Label(col, text=sub, bg=PANEL, fg=FG_DIM,
                     font=("Segoe UI", 8)).pack(anchor="w")


# ═══════════════════════════════════════════════════════════════════════════════
#  Settings dialog
# ═══════════════════════════════════════════════════════════════════════════════

class SettingsDialog(tk.Toplevel):

    def __init__(self, parent, config: dict, on_save):
        super().__init__(parent)
        self.title("Settings")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.grab_set()
        self._config  = dict(config)
        self._on_save = on_save
        self._vars: dict = {}
        self._build()
        self.after(50, self._center)

    def _center(self):
        self.update_idletasks()
        px = self.master.winfo_rootx() + self.master.winfo_width()  // 2
        py = self.master.winfo_rooty() + self.master.winfo_height() // 2
        self.geometry("+%d+%d" % (px - self.winfo_width() // 2,
                                   py - self.winfo_height() // 2))

    def _build(self):
        P = 12
        for i, entry in enumerate(up.CONFIG_SCHEMA):
            tk.Label(self, text=entry["label"] + ":", bg=BG, fg=FG,
                     font=("Segoe UI", 9), anchor="w").grid(
                row=i, column=0, sticky="w", padx=P, pady=6)
            var = tk.StringVar(value=self._config.get(entry["key"], ""))
            self._vars[entry["key"]] = var
            ttk.Entry(self, textvariable=var, width=55,
                      style="Mono.TEntry").grid(
                row=i, column=1, sticky="ew", padx=P, pady=6)
        self.columnconfigure(1, weight=1)

        row = len(up.CONFIG_SCHEMA)
        tk.Frame(self, bg=BORDER, height=1).grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=P, pady=(4, 0))
        bf = tk.Frame(self, bg=BG)
        bf.grid(row=row + 1, column=0, columnspan=2, pady=P)
        ttk.Button(bf, text="Save",   command=self._save,
                   style="Accent.TButton", width=10).pack(side="left", padx=6)
        ttk.Button(bf, text="Cancel", command=self.destroy,
                   width=10).pack(side="left", padx=6)

    def _save(self):
        for key, var in self._vars.items():
            self._config[key] = var.get().strip()
        self._on_save(self._config)
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
#  Main application
# ═══════════════════════════════════════════════════════════════════════════════

class App(tk.Tk):

    PAD = 8

    def __init__(self):
        super().__init__()
        self._mono_family = _resolve_mono()
        self.title("PZ SteamUploader Helper")
        self.geometry("1150x780")
        self.minsize(900, 600)
        self.configure(bg=BG)

        # ── Shared state ──────────────────────────────────────────────────────
        self.rstate        = rt.RegexState()    # all regex inputs
        self._config: dict = {}
        self._settings:dict= {}
        self._rows:   list = []                 # list[ModRow]
        self._busy:   bool = False
        self._affected_dirs: set = set()        # bridge: dirs touched by regex

        self._rename_previews: list = []

        self._load_theme_overrides()
        self._apply_theme()
        self._build_ui()
        self._load_config_silent()
        self._refresh_mods()

    def _mono(self, size: int = 9) -> tuple:
        return (self._mono_family, size)

    # ── Theme ──────────────────────────────────────────────────────────────────

    def _apply_theme(self):
        s = ttk.Style(self)
        s.theme_use("clam")

        s.configure(".",
            background=BG, foreground=FG,
            fieldbackground=PANEL, bordercolor=BORDER,
            troughcolor=PANEL, selectbackground=ACCENT,
            selectforeground=ON_ACCENT, font=("Segoe UI", 10))

        s.configure("TFrame",  background=BG)
        s.configure("TLabel",  background=BG, foreground=FG)
        s.configure("Dim.TLabel",
            background=BG, foreground=FG_DIM, font=("Segoe UI", 9))
        s.configure("Accent.TLabel",
            background=BG, foreground=ACCENT, font=("Segoe UI", 9, "bold"))

        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab",
            background=PANEL, foreground=FG_DIM, padding=[14, 6], borderwidth=0)
        s.map("TNotebook.Tab",
            background=[("selected", BG)],
            foreground=[("selected", ACCENT)])

        s.configure("TPanedwindow", background=BG)

        s.configure("TEntry",
            fieldbackground=PANEL, foreground=FG,
            bordercolor=BORDER, insertcolor=FG, relief="flat", padding=5)
        s.configure("Mono.TEntry",
            fieldbackground=PANEL, foreground=FG,
            bordercolor=BORDER, insertcolor=FG, relief="flat", padding=5,
            font=self._mono(9))

        s.configure("TButton",
            background=PANEL, foreground=FG,
            borderwidth=1, relief="flat", padding=[10, 5])
        s.map("TButton",
            background=[("active", BORDER)],
            foreground=[("active", ACCENT)])

        s.configure("Accent.TButton",
            background=ACCENT, foreground=ON_ACCENT,
            borderwidth=0, relief="flat", padding=[12, 6])
        s.map("Accent.TButton",
            background=[("active", ACCENT2)])

        s.configure("Danger.TButton",
            background=DANGER_BG, foreground=DANGER,
            borderwidth=0, relief="flat", padding=[10, 5])
        s.map("Danger.TButton",
            background=[("active", DANGER_BG_ACTIVE)])

        s.configure("TCheckbutton", background=BG, foreground=FG)
        s.configure("TRadiobutton", background=BG, foreground=FG)
        s.configure("Panel.TCheckbutton", background=PANEL, foreground=FG)
        s.map("Panel.TCheckbutton",
            background=[("active", PANEL)])

        s.configure("TScrollbar",
            background=PANEL, troughcolor=BG,
            bordercolor=BG, arrowcolor=FG_DIM, relief="flat")

        s.configure("TLabelframe",
            background=BG, bordercolor=BORDER, relief="solid")
        s.configure("TLabelframe.Label",
            background=BG, foreground=ACCENT, font=("Segoe UI", 9, "bold"))

        s.configure("Treeview",
            background=PANEL, foreground=FG,
            fieldbackground=PANEL, rowheight=24, borderwidth=0)
        s.configure("Treeview.Heading",
            background=BORDER, foreground=FG_DIM, borderwidth=0, relief="flat")
        s.map("Treeview", background=[("selected", SELECT_BG)])

    # ── Top-level layout ───────────────────────────────────────────────────────

    def _load_theme_overrides(self):
        global BG, PANEL, BORDER, ACCENT, ACCENT2, SUCCESS, WARN, DANGER, FG, FG_DIM
        global SELECT_BG, ON_ACCENT, DANGER_BG, DANGER_BG_ACTIVE
        saved = up.load_config().get("theme", {})
        values = dict(DEFAULT_PALETTE)
        values.update({k: v for k, v in saved.items() if k in PALETTE_NAMES})
        (BG, PANEL, BORDER, FG, FG_DIM, ACCENT, WARN, SUCCESS, DANGER, ACCENT2,
         SELECT_BG, ON_ACCENT, DANGER_BG, DANGER_BG_ACTIVE) = (
            values[n] for n in PALETTE_NAMES)

    def _persist_theme(self):
        config = up.load_config()
        if all(globals()[n] == DEFAULT_PALETTE[n] for n in PALETTE_NAMES):
            config.pop("theme", None)
        else:
            config["theme"] = {n: globals()[n] for n in PALETTE_NAMES}
        up.save_config(config)
        self._config = config

    def _build_theme_bar(self, parent):
        cluster = tk.Frame(parent, bg=BG)
        cluster.pack(side="right")

        self._reset_canvas = tk.Canvas(cluster, width=16, height=16, bg=BG,
                                        highlightthickness=0, cursor="hand2")
        self._reset_canvas.pack(side="right", padx=(6, 0))
        self._draw_reset_icon(FG_DIM)
        self._reset_canvas.bind("<Button-1>", lambda e: self._reset_theme())
        self._reset_canvas.bind("<Enter>", lambda e: self._draw_reset_icon(ACCENT))
        self._reset_canvas.bind("<Leave>", lambda e: self._draw_reset_icon(FG_DIM))

        for name in reversed(PALETTE_NAMES):
            sw = tk.Frame(cluster, width=16, height=16,
                          bg=globals()[name], cursor="hand2",
                          highlightthickness=1, highlightbackground=BORDER)
            sw.pack(side="right", padx=(4, 0))
            sw.pack_propagate(False)
            sw.bind("<Button-1>", lambda e, n=name: self._pick_swatch_color(n))
            sw.bind("<Enter>", lambda e, n=name: self.status_var.set(
                n + "  " + globals()[n] + "  (click to change)"))
            sw.bind("<Leave>", lambda e: self.status_var.set("Ready."))

    def _draw_reset_icon(self, color: str):
        c = self._reset_canvas
        c.delete("all")
        c.create_arc(2, 2, 14, 14, start=45, extent=270,
                     style="arc", outline=color, width=1.6)
        ang = math.radians(45)
        tip = (8 + 6 * math.cos(ang), 8 - 6 * math.sin(ang))
        c.create_polygon(
            tip[0] + 3.5, tip[1] - 1,
            tip[0] - 1,   tip[1] - 4,
            tip[0] - 1.5, tip[1] + 2.5,
            fill=color, outline=color)

    def _pick_swatch_color(self, name: str):
        _, hex_color = colorchooser.askcolor(
            color=globals()[name], title="Choose " + name, parent=self)
        if not hex_color:
            return
        globals()[name] = hex_color
        self._persist_theme()
        self._rebuild_live()
        self.status_var.set(name + " updated to " + hex_color)

    def _reset_theme(self):
        global BG, PANEL, BORDER, ACCENT, ACCENT2, SUCCESS, WARN, DANGER, FG, FG_DIM
        global SELECT_BG, ON_ACCENT, DANGER_BG, DANGER_BG_ACTIVE
        (BG, PANEL, BORDER, FG, FG_DIM, ACCENT, WARN, SUCCESS, DANGER, ACCENT2,
         SELECT_BG, ON_ACCENT, DANGER_BG, DANGER_BG_ACTIVE) = (
            DEFAULT_PALETTE[n] for n in PALETTE_NAMES)
        self._persist_theme()
        self._rebuild_live()
        self.status_var.set("Theme reset to default.")

    # ── Live rebuild (re-applies the palette to every widget) ──────────────────

    def _capture_ui_state(self) -> dict:
        return {
            "outer_tab":   self._nb.index(self._nb.select()),
            "inner_tab":   self._inner_nb.index(self._inner_nb.select()),
            "find":        self.find_var.get(),
            "replace":     self.replace_var.get(),
            "ext":         self.ext_var.get(),
            "exc_entry":   self.exc_entry_var.get(),
            "ignorecase":  self.flag_ignorecase.get(),
            "multiline":   self.flag_multiline.get(),
            "dotall":      self.flag_dotall.get(),
            "literal":     self.flag_literal.get(),
            "recursive":   self.recursive_var.get(),
            "backup":      self.backup_var.get(),
            "rename_find": self.rename_find_var.get(),
            "rename_repl": self.rename_repl_var.get(),
            "rename_scope":       self.rename_scope.get(),
            "rename_ignorecase":  self.rename_ignorecase.get(),
            "filter":      self._filter_var.get(),
            "field":       self._field_var.get(),
            "upload_mode": self._upload_mode.get(),
            "dry_run":     self._dry_run_var.get(),
            "selected_mods": {str(r.info.path) for r in self._rows if r.var.get()},
        }

    def _restore_ui_state(self, state: dict):
        self.find_var.set(state["find"])
        self.replace_var.set(state["replace"])
        self.ext_var.set(state["ext"])
        self.exc_entry_var.set(state["exc_entry"])
        self.flag_ignorecase.set(state["ignorecase"])
        self.flag_multiline.set(state["multiline"])
        self.flag_dotall.set(state["dotall"])
        self.flag_literal.set(state["literal"])
        self.recursive_var.set(state["recursive"])
        self.rstate.recursive = state["recursive"]
        self.backup_var.set(state["backup"])
        self.rename_find_var.set(state["rename_find"])
        self.rename_repl_var.set(state["rename_repl"])
        self.rename_scope.set(state["rename_scope"])
        self.rename_ignorecase.set(state["rename_ignorecase"])
        self._filter_var.set(state["filter"])
        self._field_var.set(state["field"])
        self._upload_mode.set(state["upload_mode"])
        self._dry_run_var.set(state["dry_run"])

        for folder in self.rstate.folders:
            self.folder_list.insert("end", folder)
        for pattern in self.rstate.exclude_patterns:
            self.exc_list.insert("end", pattern)

        for row in self._rows:
            if str(row.info.path) in state["selected_mods"]:
                row.var.set(True)
        self._rebuild_mod_list()

        self._nb.select(state["outer_tab"])
        self._inner_nb.select(state["inner_tab"])

    def _rebuild_live(self):
        state = self._capture_ui_state()
        for child in self.winfo_children():
            child.destroy()
        self.configure(bg=BG)
        self._apply_theme()
        self._build_ui()
        self._restore_ui_state(state)

    def _build_ui(self):
        P = self.PAD

        topbar = tk.Frame(self, bg=BG)
        topbar.pack(fill="x", padx=P * 2, pady=(P * 2, 0))
        self._build_theme_bar(topbar)

        self._nb = ttk.Notebook(self)
        self._nb.pack(fill="both", expand=True, padx=P * 2, pady=(4, P))

        regex_frame  = ttk.Frame(self._nb)
        upload_frame = ttk.Frame(self._nb)
        self._nb.add(regex_frame,  text="  Regex  ")
        self._nb.add(upload_frame, text="  Upload  ")
        self._upload_tab_idx = 1
        self._nb.select(self._upload_tab_idx)

        self._build_regex_tab(regex_frame)
        self._build_upload_tab(upload_frame)

        self.status_var = tk.StringVar(value="Ready.")
        bar = tk.Frame(self, bg=PANEL, height=24)
        bar.pack(fill="x", side="bottom")
        tk.Label(bar, textvariable=self.status_var, bg=PANEL,
                 fg=FG_DIM, font=("Segoe UI", 9),
                 anchor="w", padx=12).pack(fill="x")

    # ══════════════════════════════════════════════════════════════════════════
    #  REGEX TAB
    # ══════════════════════════════════════════════════════════════════════════

    def _build_regex_tab(self, parent):
        P = self.PAD

        # Sidebar — plain scrollable frame; content fits without scrolling
        sidebar_outer = tk.Frame(parent, bg=BG, width=285)
        sidebar_outer.pack(side="left", fill="y", padx=(P, P))
        sidebar_outer.pack_propagate(False)

        self._build_regex_sidebar(sidebar_outer)

        inner_nb = ttk.Notebook(parent)
        inner_nb.pack(fill="both", expand=True, padx=(0, self.PAD))
        self._inner_nb = inner_nb
        t1 = ttk.Frame(inner_nb)
        t2 = ttk.Frame(inner_nb)
        inner_nb.add(t1, text="  Find & Replace  ")
        inner_nb.add(t2, text="  File Rename  ")
        self._build_replace_tab(t1)
        self._build_rename_tab(t2)

    # ── Regex sidebar ──────────────────────────────────────────────────────────

    def _build_regex_sidebar(self, parent):
        P = self.PAD
        S = 6   # tighter inner spacing

        def sep():
            tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(S, S + 2))

        # ── Folders ───────────────────────────────────────────────────────────
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(P, S))
        ttk.Label(row, text="FOLDERS", style="Accent.TLabel").pack(side="left")
        ttk.Button(row, text="Remove", command=self._remove_folders,
                   style="Danger.TButton").pack(side="right")
        ttk.Button(row, text="+ Add",
                   command=self._add_folders).pack(side="right", padx=(0, 4))

        lf = tk.Frame(parent, bg=PANEL,
                      highlightbackground=BORDER, highlightthickness=1)
        lf.pack(fill="x", pady=(0, 0))
        self.folder_list = tk.Listbox(lf,
            bg=PANEL, fg=FG, selectbackground=SELECT_BG,
            activestyle="none", borderwidth=0, highlightthickness=0,
            font=("Segoe UI", 9), selectforeground=ACCENT,
            selectmode="extended", height=4)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.folder_list.yview)
        self.folder_list.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.folder_list.pack(fill="both", expand=True, padx=2, pady=2)

        sep()

        # ── File filter ───────────────────────────────────────────────────────
        hrow = tk.Frame(parent, bg=BG)
        hrow.pack(fill="x", pady=(0, S))
        ttk.Label(hrow, text="FILE FILTER", style="Accent.TLabel").pack(side="left")
        ttk.Label(hrow, text="*.txt, workshop.*", style="Dim.TLabel").pack(
            side="right")

        self.ext_var = tk.StringVar()
        e = ttk.Entry(parent, textvariable=self.ext_var, style="Mono.TEntry")
        e.pack(fill="x")
        e.bind("<FocusOut>", lambda _: self._parse_file_filter())
        e.bind("<Return>",   lambda _: self._parse_file_filter())

        sep()

        # ── Exclude folders ───────────────────────────────────────────────────
        hrow2 = tk.Frame(parent, bg=BG)
        hrow2.pack(fill="x", pady=(0, S))
        ttk.Label(hrow2, text="EXCLUDE FOLDERS", style="Accent.TLabel").pack(side="left")
        ttk.Label(hrow2, text="media, /media, foo/bar",
                  style="Dim.TLabel").pack(side="right")

        exc_row = tk.Frame(parent, bg=BG)
        exc_row.pack(fill="x", pady=(0, S))
        self.exc_entry_var = tk.StringVar()
        exc_e = ttk.Entry(exc_row, textvariable=self.exc_entry_var, style="Mono.TEntry")
        exc_e.pack(side="left", fill="x", expand=True)
        exc_e.bind("<Return>", lambda _: self._add_exclusion())
        ttk.Button(exc_row, text="Add",
                   command=self._add_exclusion).pack(side="left", padx=(4, 0))
        ttk.Button(exc_row, text="✕", command=self._remove_exclusion,
                   style="Danger.TButton", width=3).pack(side="left", padx=(2, 0))

        exc_lf = tk.Frame(parent, bg=PANEL,
                          highlightbackground=BORDER, highlightthickness=1, height=60)
        exc_lf.pack(fill="x")
        exc_lf.pack_propagate(False)
        self.exc_list = tk.Listbox(exc_lf,
            bg=PANEL, fg=WARN, selectbackground=SELECT_BG,
            activestyle="none", borderwidth=0, highlightthickness=0,
            font=self._mono(9), selectforeground=ACCENT)
        exc_sb = ttk.Scrollbar(exc_lf, orient="vertical", command=self.exc_list.yview)
        self.exc_list.configure(yscrollcommand=exc_sb.set)
        exc_sb.pack(side="right", fill="y")
        self.exc_list.pack(fill="both", expand=True, padx=2, pady=2)

        sep()

        # ── Options ───────────────────────────────────────────────────────────
        ttk.Label(parent, text="OPTIONS", style="Accent.TLabel").pack(
            anchor="w", pady=(0, S))
        self.recursive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="Include subfolders",
                        variable=self.recursive_var,
                        command=lambda: setattr(self.rstate, "recursive",
                                                self.recursive_var.get())).pack(anchor="w")
        self.backup_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(parent, text="Backup before changes (.bak)",
                        variable=self.backup_var).pack(anchor="w", pady=(S, 0))

    # ── Find & Replace tab ─────────────────────────────────────────────────────

    def _build_replace_tab(self, parent):
        P = self.PAD
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=P, pady=P)

        g = ttk.Frame(top)
        g.pack(fill="x")
        g.columnconfigure(1, weight=1)

        ttk.Label(g, text="Find (regex)").grid(row=0, column=0, sticky="w", pady=3)
        self.find_var = tk.StringVar()
        ttk.Entry(g, textvariable=self.find_var, style="Mono.TEntry"
                  ).grid(row=0, column=1, sticky="ew", padx=(P, 0), pady=3)

        ttk.Label(g, text="Replace").grid(row=1, column=0, sticky="w", pady=3)
        self.replace_var = tk.StringVar()
        ttk.Entry(g, textvariable=self.replace_var, style="Mono.TEntry"
                  ).grid(row=1, column=1, sticky="ew", padx=(P, 0), pady=3)

        fr = ttk.Frame(top)
        fr.pack(fill="x", pady=(6, 0))
        self.flag_ignorecase = tk.BooleanVar()
        self.flag_multiline  = tk.BooleanVar()
        self.flag_dotall     = tk.BooleanVar()
        self.flag_literal    = tk.BooleanVar()
        for text, var, px in [
            ("Ignore case", self.flag_ignorecase, 0),
            ("Multiline",   self.flag_multiline,  10),
            ("Dot-all",     self.flag_dotall,      10),
            ("Literal",     self.flag_literal,     10),
        ]:
            ttk.Checkbutton(fr, text=text, variable=var).pack(side="left", padx=(px, 0))

        ttk.Label(top,
            text="Replace: \\1 or $1 = group 1  |  \\g<name> = named group  |  \\n = newline",
            style="Dim.TLabel").pack(anchor="w", pady=(2, 0))

        br = ttk.Frame(top)
        br.pack(fill="x", pady=(P, 0))
        ttk.Button(br, text="Preview Matches",
                   command=self._preview_content).pack(side="left")
        ttk.Button(br, text="Apply Replace",
                   command=self._apply_content_replace,
                   style="Accent.TButton").pack(side="left", padx=(P, 0))
        self.replace_count_lbl = ttk.Label(br, text="", style="Dim.TLabel")
        self.replace_count_lbl.pack(side="left", padx=(12, 0))

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=P)

        tf = ttk.Frame(parent)
        tf.pack(fill="both", expand=True, padx=P, pady=P)
        cols = ("file", "line", "original", "proposed")
        self.replace_tree = ttk.Treeview(tf, columns=cols,
                                          show="headings", selectmode="browse")
        for col, w, txt in [("file", 220, "File"), ("line", 50, "Line"),
                             ("original", 280, "Original"), ("proposed", 280, "Proposed")]:
            self.replace_tree.heading(col, text=txt)
            self.replace_tree.column(col, width=w, minwidth=60,
                                     anchor="e" if col == "line" else "w")
        self.replace_tree.tag_configure("changed", foreground=SUCCESS)
        vsb = ttk.Scrollbar(tf, orient="vertical",   command=self.replace_tree.yview)
        hsb = ttk.Scrollbar(tf, orient="horizontal", command=self.replace_tree.xview)
        self.replace_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right",  fill="y")
        hsb.pack(side="bottom", fill="x")
        self.replace_tree.pack(fill="both", expand=True)

    # ── File Rename tab ────────────────────────────────────────────────────────

    def _build_rename_tab(self, parent):
        P = self.PAD
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=P, pady=P)

        g = ttk.Frame(top)
        g.pack(fill="x")
        g.columnconfigure(1, weight=1)

        ttk.Label(g, text="Filename pattern").grid(row=0, column=0, sticky="w", pady=3)
        self.rename_find_var = tk.StringVar()
        ttk.Entry(g, textvariable=self.rename_find_var, style="Mono.TEntry"
                  ).grid(row=0, column=1, sticky="ew", padx=(P, 0), pady=3)

        ttk.Label(g, text="Replacement").grid(row=1, column=0, sticky="w", pady=3)
        self.rename_repl_var = tk.StringVar()
        ttk.Entry(g, textvariable=self.rename_repl_var, style="Mono.TEntry"
                  ).grid(row=1, column=1, sticky="ew", padx=(P, 0), pady=3)

        ttk.Label(g, text="Apply to").grid(row=2, column=0, sticky="w", pady=3)
        sr = ttk.Frame(g)
        sr.grid(row=2, column=1, sticky="w", padx=(P, 0))
        self.rename_scope = tk.StringVar(value="stem")
        for text, val in [("Stem (no ext)", "stem"), ("Full name", "full"), ("Extension", "ext")]:
            ttk.Radiobutton(sr, text=text, variable=self.rename_scope,
                            value=val).pack(side="left", padx=(0, 12))

        fr = ttk.Frame(top)
        fr.pack(fill="x", pady=(6, 0))
        self.rename_ignorecase = tk.BooleanVar()
        ttk.Checkbutton(fr, text="Ignore case",
                        variable=self.rename_ignorecase).pack(side="left")

        br = ttk.Frame(top)
        br.pack(fill="x", pady=(P, 0))
        ttk.Button(br, text="Preview Renames",
                   command=self._preview_renames).pack(side="left")
        ttk.Button(br, text="Apply Renames",
                   command=self._apply_renames,
                   style="Accent.TButton").pack(side="left", padx=(P, 0))
        self.rename_count_lbl = ttk.Label(br, text="", style="Dim.TLabel")
        self.rename_count_lbl.pack(side="left", padx=(12, 0))

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=P)

        tf = ttk.Frame(parent)
        tf.pack(fill="both", expand=True, padx=P, pady=P)
        cols = ("folder", "original", "proposed", "status")
        self.rename_tree = ttk.Treeview(tf, columns=cols,
                                         show="headings", selectmode="browse")
        for col, w, txt in [("folder", 200, "Folder"), ("original", 220, "Original"),
                             ("proposed", 220, "New Name"), ("status", 110, "Status")]:
            self.rename_tree.heading(col, text=txt)
            self.rename_tree.column(col, width=w, minwidth=60)
        self.rename_tree.tag_configure("changed",   foreground=SUCCESS)
        self.rename_tree.tag_configure("unchanged", foreground=FG_DIM)
        self.rename_tree.tag_configure("conflict",  foreground=WARN)
        self.rename_tree.tag_configure("error",     foreground=DANGER)
        vsb = ttk.Scrollbar(tf, orient="vertical",   command=self.rename_tree.yview)
        hsb = ttk.Scrollbar(tf, orient="horizontal", command=self.rename_tree.xview)
        self.rename_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right",  fill="y")
        hsb.pack(side="bottom", fill="x")
        self.rename_tree.pack(fill="both", expand=True)

    # ══════════════════════════════════════════════════════════════════════════
    #  UPLOAD TAB
    # ══════════════════════════════════════════════════════════════════════════

    def _build_upload_tab(self, parent):
        P = self.PAD
        paned = ttk.PanedWindow(parent, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=P, pady=(P, 0))
        left  = tk.Frame(paned, bg=BG, width=370)
        right = tk.Frame(paned, bg=BG)
        paned.add(left,  weight=1)
        paned.add(right, weight=2)
        self._build_mod_panel(left)
        self._build_upload_log(right)
        self._build_upload_bar(parent)

    def _build_mod_panel(self, parent):
        P = self.PAD

        # Header: title + Refresh + Settings
        hdr = tk.Frame(parent, bg=BG)
        hdr.pack(fill="x", padx=P, pady=(P, P))
        tk.Label(hdr, text="MODS", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Button(hdr, text="⚙", width=3,
                   command=self._open_settings).pack(side="right")
        ttk.Button(hdr, text="Refresh",
                   command=self._refresh_mods).pack(side="right", padx=(0, 4))

        # Search entry
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._rebuild_mod_list())
        ttk.Entry(parent, textvariable=self._filter_var).pack(
            fill="x", padx=P, pady=(0, 6))

        # Filter controls row: match-on radios  |  select buttons
        ctrl = tk.Frame(parent, bg=BG)
        ctrl.pack(fill="x", padx=P, pady=(0, P))

        self._field_var = tk.StringVar(value="name")
        for text, val in [("Name", "name"), ("Mod ID", "modid")]:
            ttk.Radiobutton(ctrl, text=text, variable=self._field_var,
                            value=val, command=self._rebuild_mod_list).pack(
                side="left", padx=(0, 6))

        tk.Frame(ctrl, bg=BORDER, width=1).pack(side="left", fill="y", padx=(4, 8))

        ttk.Button(ctrl, text="Affected",
                   command=self._select_affected).pack(side="left", padx=(0, 4))
        ttk.Button(ctrl, text="All",
                   command=self._select_all_mods).pack(side="left", padx=(0, 4))
        ttk.Button(ctrl, text="None",
                   command=self._select_no_mods).pack(side="left")

        # Mod list
        list_outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        list_outer.pack(fill="both", expand=True, padx=P, pady=(0, 0))
        self._checklist = _CheckList(list_outer)
        self._checklist.pack(fill="both", expand=True)

        # Footer: legend + count on one line
        footer = tk.Frame(parent, bg=BG)
        footer.pack(fill="x", padx=P, pady=(4, P))
        tk.Label(footer, text="●", bg=BG, fg=WARN,
                 font=("Segoe UI", 8)).pack(side="left")
        tk.Label(footer, text=" recently changed",
                 bg=BG, fg=FG_DIM, font=("Segoe UI", 8)).pack(side="left")
        self._mod_count_var = tk.StringVar(value="No mods loaded")
        tk.Label(footer, textvariable=self._mod_count_var,
                 bg=BG, fg=FG_DIM, font=("Segoe UI", 8)).pack(side="right")

    def _build_upload_log(self, parent):
        P = self.PAD
        hdr = tk.Frame(parent, bg=BG)
        hdr.pack(fill="x", padx=P, pady=(P, 4))
        tk.Label(hdr, text="LOG", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Button(hdr, text="Clear", command=self._clear_upload_log).pack(side="right")

        log_outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        log_outer.pack(fill="both", expand=True, padx=P, pady=(0, P))
        self._upload_log = tk.Text(log_outer,
            bg=PANEL, fg=FG, insertbackground=FG,
            font=self._mono(9), wrap="word",
            borderwidth=0, highlightthickness=0, state="disabled")
        vsb = ttk.Scrollbar(log_outer, orient="vertical",
                            command=self._upload_log.yview)
        self._upload_log.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._upload_log.pack(fill="both", expand=True, padx=2, pady=2)

    def _build_upload_bar(self, parent):
        P = self.PAD
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x", padx=P * 2, pady=P)

        # Primary action
        ttk.Button(bar, text="Upload Selected",
                   style="Accent.TButton",
                   command=self._run_upload).pack(side="left")

        # Divider
        tk.Frame(bar, bg=BORDER, width=1).pack(side="left", fill="y", padx=(P, P))

        # Upload mode
        self._upload_mode = tk.StringVar(value="full")
        tk.Label(bar, text="Mode:", bg=BG, fg=FG_DIM,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        ttk.Radiobutton(bar, text="Full",
                        variable=self._upload_mode, value="full").pack(side="left")
        ttk.Radiobutton(bar, text="Desc + Tags",
                        variable=self._upload_mode, value="desc_tags").pack(
            side="left", padx=(6, 0))

        # Divider
        tk.Frame(bar, bg=BORDER, width=1).pack(side="left", fill="y", padx=(P, P))

        # Options
        self._dry_run_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Dry run",
                        variable=self._dry_run_var).pack(side="left")

        # Status — right-aligned
        self._upload_status_var = tk.StringVar(value="Ready")
        tk.Label(bar, textvariable=self._upload_status_var,
                 bg=BG, fg=FG_DIM, font=("Segoe UI", 9)).pack(side="right")

    # ══════════════════════════════════════════════════════════════════════════
    #  Bridge — regex → upload
    # ══════════════════════════════════════════════════════════════════════════

    def _mark_affected(self, modified_paths: list):
        workshop_dir = self._settings.get("workshop_dir")
        if not workshop_dir:
            return
        for path_str in modified_paths:
            try:
                rel = Path(path_str).relative_to(workshop_dir)
                self._affected_dirs.add(str(workshop_dir / rel.parts[0]))
            except (ValueError, IndexError):
                pass
        self._refresh_affected()

    def _refresh_affected(self):
        count = 0
        for row in self._rows:
            if str(row.path) in self._affected_dirs:
                row.affected = True
                row.var.set(True)
            if row.affected:
                count += 1
        label = "  Upload  " if not count else "  Upload  (%d)  " % count
        self._nb.tab(self._upload_tab_idx, text=label)
        self._rebuild_mod_list()

    # ══════════════════════════════════════════════════════════════════════════
    #  Sidebar actions (regex)
    # ══════════════════════════════════════════════════════════════════════════

    def _add_folders(self):
        added = 0
        while True:
            d = filedialog.askdirectory(
                title="Select folder %d  (Cancel when done)" % (
                    len(self.rstate.folders) + added + 1))
            if not d:
                break
            if d not in self.rstate.folders:
                self.rstate.folders.append(d)
                self.folder_list.insert("end", d)
                added += 1

    def _remove_folders(self):
        for idx in reversed(list(self.folder_list.curselection())):
            self.rstate.folders.pop(idx)
            self.folder_list.delete(idx)

    def _parse_file_filter(self):
        self.rstate.file_patterns = rt.parse_file_filter(self.ext_var.get())

    def _add_exclusion(self):
        raw = self.exc_entry_var.get().strip()
        if not raw:
            return
        norm = raw.replace("\\", "/")
        if norm in self.rstate.exclude_patterns:
            return
        self.rstate.exclude_patterns.append(norm)
        self.exc_list.insert("end", norm)
        self.exc_entry_var.set("")

    def _remove_exclusion(self):
        sel = self.exc_list.curselection()
        if not sel:
            return
        idx = sel[0]
        self.rstate.exclude_patterns.pop(idx)
        self.exc_list.delete(idx)

    # ══════════════════════════════════════════════════════════════════════════
    #  Find & Replace logic
    # ══════════════════════════════════════════════════════════════════════════

    def _get_rx(self):
        raw = self.find_var.get()
        pat = import_re.escape(raw) if self.flag_literal.get() else raw
        flags = rt.build_flags(self.flag_ignorecase.get(),
                               self.flag_multiline.get(),
                               self.flag_dotall.get())
        return rt.compile_pattern(pat, flags)

    def _preview_content(self):
        self._parse_file_filter()
        if not self.find_var.get():
            messagebox.showwarning("No pattern", "Enter a regex pattern to search for.")
            return
        if not self.rstate.folders:
            messagebox.showwarning("No folders", "Add at least one folder first.")
            return
        rx, err = self._get_rx()
        if err:
            messagebox.showerror("Regex error", "Invalid pattern:\n" + err)
            return

        self.replace_tree.delete(*self.replace_tree.get_children())
        self.replace_count_lbl.config(text="")
        self._set_status("Scanning...")
        expanded = rt.expand_repl(self.replace_var.get())

        def worker():
            matches = rt.scan_content(self.rstate, rx, expanded)
            self.after(0, lambda: self._populate_replace_tree(matches))

        threading.Thread(target=worker, daemon=True).start()

    def _populate_replace_tree(self, matches: list):
        self.replace_tree.delete(*self.replace_tree.get_children())
        base = self.rstate.folders[0] if len(self.rstate.folders) == 1 else None
        for m in matches:
            rel = os.path.relpath(m.filepath, base) if base else m.filepath
            tag = "changed" if m.original != m.proposed else ""
            self.replace_tree.insert("", "end",
                values=(rel, m.line_no, m.original.strip(), m.proposed.strip()),
                tags=(tag,))
        n = len(matches)
        self.replace_count_lbl.config(text="%d match%s found" % (n, "es" if n != 1 else ""))
        self._set_status("Preview — %d match(es)." % n)

    def _apply_content_replace(self):
        self._parse_file_filter()
        if not self.find_var.get():
            messagebox.showwarning("No pattern", "Enter a regex pattern.")
            return
        if not self.rstate.folders:
            messagebox.showwarning("No folders", "Add at least one folder first.")
            return
        rx, err = self._get_rx()
        if err:
            messagebox.showerror("Regex error", "Invalid pattern:\n" + err)
            return
        if not messagebox.askyesno("Confirm",
                "Apply replacement to all matching files?\n"
                "This cannot be undone (unless backup is enabled)."):
            return

        self._set_status("Applying...")
        expanded = rt.expand_repl(self.replace_var.get())
        backup   = self.backup_var.get()

        def worker():
            changed_paths, skipped, errors = rt.apply_content(
                self.rstate, rx, expanded, backup)
            msg = "Done. %d changed, %d skipped, %d errors." % (
                len(changed_paths), skipped, errors)
            self.after(0, lambda: self._set_status(msg))
            if changed_paths:
                self.after(0, lambda p=changed_paths: self._mark_affected(p))
            self.after(0, self._preview_content)

        threading.Thread(target=worker, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════════════
    #  Rename logic
    # ══════════════════════════════════════════════════════════════════════════

    def _preview_renames(self):
        self._parse_file_filter()
        pat = self.rename_find_var.get()
        if not pat:
            messagebox.showwarning("No pattern", "Enter a filename pattern.")
            return
        if not self.rstate.folders:
            messagebox.showwarning("No folders", "Add at least one folder first.")
            return
        flags = rt.build_flags(ignorecase=self.rename_ignorecase.get())
        rx, err = rt.compile_pattern(pat, flags)
        if err:
            messagebox.showerror("Regex error", "Invalid pattern:\n" + err)
            return

        previews = rt.scan_renames(
            self.rstate, rx, self.rename_repl_var.get(), self.rename_scope.get())
        self._rename_previews = previews
        self._populate_rename_tree(previews)

    def _populate_rename_tree(self, previews: list):
        self.rename_tree.delete(*self.rename_tree.get_children())
        base    = self.rstate.folders[0] if len(self.rstate.folders) == 1 else None
        changed = 0
        for pv in previews:
            if pv.error == "conflict":
                tag, status = "conflict", "conflict"
            elif pv.error:
                tag, status = "error", "error"
            elif pv.changed:
                tag, status = "changed", "will rename"
                changed += 1
            else:
                tag, status = "unchanged", "-"
            rel = os.path.relpath(pv.folder, base) if base else pv.folder
            self.rename_tree.insert("", "end",
                values=(rel, pv.original, pv.proposed, status), tags=(tag,))
        self.rename_count_lbl.config(text="%d file(s) will be renamed" % changed)
        self._set_status("Rename preview: %d change(s)." % changed)

    def _apply_renames(self):
        if not self._rename_previews:
            messagebox.showwarning("No preview", "Run a preview first.")
            return
        to_do = [p for p in self._rename_previews if p.changed and not p.error]
        if not to_do:
            messagebox.showinfo("Nothing to do", "No valid renames queued.")
            return
        if not messagebox.askyesno("Confirm",
                "Rename %d file(s)?\nThis cannot be undone." % len(to_do)):
            return

        self._set_status("Renaming...")
        backup = self.backup_var.get()

        def worker():
            renamed_paths, errors = rt.apply_renames(to_do, backup)
            msg = "Done. %d renamed, %d error(s)." % (len(renamed_paths), errors)
            self.after(0, lambda: self._set_status(msg))
            if renamed_paths:
                self.after(0, lambda p=renamed_paths: self._mark_affected(p))
            self.after(0, lambda: self._populate_rename_tree(self._rename_previews))

        threading.Thread(target=worker, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════════════
    #  Upload logic
    # ══════════════════════════════════════════════════════════════════════════

    def _load_config_silent(self):
        saved = up.load_config()
        self._config, _ = up.resolve_config(saved, force_prompt=False, silent=True)
        self._settings  = up.config_to_settings(self._config)

    def _open_settings(self):
        SettingsDialog(self, self._config, self._on_settings_saved)

    def _on_settings_saved(self, new_config: dict):
        self._config   = new_config
        up.save_config(new_config)
        self._settings = up.config_to_settings(new_config)
        self._refresh_mods()

    def _refresh_mods(self):
        workshop_dir = self._settings.get("workshop_dir")
        if not workshop_dir or not workshop_dir.is_dir():
            self._mod_count_var.set("Workshop folder not configured")
            return
        self._rows = [
            ModRow(info=up.ModInfo(p), var=tk.BooleanVar(value=False))
            for p in sorted(workshop_dir.iterdir())
            if p.is_dir() and up.is_mod_dir(p)
        ]
        # Re-apply bridge flags from this session
        for row in self._rows:
            if str(row.path) in self._affected_dirs:
                row.affected = True
                row.var.set(True)
        self._rebuild_mod_list()

    def _rebuild_mod_list(self):
        pattern = self._filter_var.get()
        field   = self._field_var.get()
        self._checklist.clear()
        visible = 0
        for row in self._rows:
            if not row.matches(pattern, field):
                continue
            sub    = "Mod ID: " + (row.mod_id or "(none)")
            badge  = "●" if row.affected else ""
            colour = WARN if row.affected else FG_DIM
            self._checklist.add_row(row.var, row.title or row.name,
                                    sub, badge, colour)
            visible += 1
        selected = sum(1 for r in self._rows if r.var.get())
        self._mod_count_var.set(
            "%d of %d shown  •  %d selected" % (visible, len(self._rows), selected))

    def _select_all_mods(self):
        for r in self._rows: r.var.set(True)
        self._rebuild_mod_list()

    def _select_no_mods(self):
        for r in self._rows: r.var.set(False)
        self._rebuild_mod_list()

    def _select_affected(self):
        for r in self._rows: r.var.set(r.affected)
        self._rebuild_mod_list()

    def _clear_upload_log(self):
        self._upload_log.configure(state="normal")
        self._upload_log.delete("1.0", tk.END)
        self._upload_log.configure(state="disabled")

    def _run_upload(self):
        if self._busy:
            messagebox.showwarning("Busy", "An operation is already running.")
            return
        selected = [r for r in self._rows if r.var.get()]
        if not selected:
            messagebox.showwarning("Nothing selected",
                "Select at least one mod from the list.")
            return
        uploader_exe = self._settings.get("uploader_exe")
        if uploader_exe is None:
            messagebox.showwarning("Uploader not configured",
                "No SteamUploader.exe path set.\nOpen Settings to configure it.")
            return

        mod_dirs = [r.path for r in selected]
        dry_run  = self._dry_run_var.get()
        mode     = self._upload_mode.get()

        self._busy = True
        self._upload_status_var.set("Running...")

        def _thread():
            old = sys.stdout
            sys.stdout = _TextRedirector(self._upload_log)
            try:
                up.run_direct_upload(mod_dirs, uploader_exe, dry_run, mode)
                uploaded = {str(r.path) for r in selected}
                self._affected_dirs -= uploaded
                self.after(0, self._refresh_affected)
            except Exception as e:
                print("\nERROR: " + str(e) + "\n")
            finally:
                sys.stdout = old
                self._busy = False
                self.after(0, lambda: self._upload_status_var.set("Ready"))

        threading.Thread(target=_thread, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════════════
    #  Utilities
    # ══════════════════════════════════════════════════════════════════════════

    def _set_status(self, msg: str):
        self.status_var.set(msg)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
