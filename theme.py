"""Dark clam theme for the desktop app. No third-party theme packs.

Windows vista/xpnative ignore most ttk color configures. clam honors them.
Native filedialog/messagebox stay system-light; that is documented, not a bug.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

BG = "#16181d"
PANEL = "#1e222a"
FIELD = "#12151b"
FG = "#e8eaed"
MUTED = "#9aa0a6"
ACCENT = "#3ddc97"
SELECT = "#1f6feb"
LINK = "#7dd3fc"
WARN = "#f5a524"
SOON = "#e6c07b"
CLOSED = "#6b7280"
ROW = "#252a33"
ROW_ALT = "#1a1e26"
HEAD = "#2b313c"
OK = "#3ddc97"
FAIL = "#f07178"

ZOOM_MIN = 0.7
ZOOM_MAX = 2.0
ZOOM_STEP = 0.1
_FONT = "Segoe UI"

DENSITY_ROW = {"comfortable": 26, "compact": 20}


def clamp_zoom(scale: float) -> float:
    stepped = round(scale / ZOOM_STEP) * ZOOM_STEP
    return max(ZOOM_MIN, min(ZOOM_MAX, round(stepped, 2)))


def _pt(base: int, scale: float) -> int:
    return max(6, int(round(base * scale)))


def display_zoom() -> float:
    """Slightly larger UI on 125%+ Windows scaling. 100% stays 1.0."""
    try:
        import ctypes

        awareness = getattr(ctypes.windll.shcore, "SetProcessDpiAwareness", None)
        if awareness is not None:
            awareness(1)
        factor = ctypes.windll.shcore.GetScaleFactorForDevice(0)
        scale = float(factor) / 100.0
        if scale >= 1.5:
            return 1.2
        if scale >= 1.25:
            return 1.1
    except Exception:
        pass
    return 1.0


def make_app_icon(root: tk.Tk) -> tk.PhotoImage:
    """32px radar mark in accent green. No image file on disk."""
    size = 32
    img = tk.PhotoImage(width=size, height=size)
    cx = cy = (size - 1) / 2.0
    for y in range(size):
        for x in range(size):
            dx = x - cx
            dy = y - cy
            r = (dx * dx + dy * dy) ** 0.5
            color = BG
            if 11.2 <= r <= 13.4:
                color = ACCENT
            elif abs(dx) <= 1.2 and 8 <= y <= 24:
                color = ACCENT
            elif dy > 0 and abs(dx) <= dy * 0.35 and r <= 13:
                color = ACCENT
            img.put(color, (x, y))
    root._discovery_icon = img  # keep a reference
    return img


def apply_zoom(
    root: tk.Tk,
    scale: float,
    log: tk.Text | None = None,
    density: str = "comfortable",
) -> float:
    """Scale ttk and log fonts. Returns the clamped scale."""
    scale = clamp_zoom(scale)
    style = ttk.Style(root)
    ui = _pt(10, scale)
    hint = _pt(9, scale)
    title = _pt(16, scale)
    brand = _pt(18, scale)
    style.configure("TLabel", font=(_FONT, ui))
    style.configure("Hint.TLabel", font=(_FONT, hint))
    style.configure("Title.TLabel", font=(_FONT, title, "bold"))
    style.configure("Brand.TLabel", font=(_FONT, brand, "bold"))
    style.configure("TButton", font=(_FONT, ui), padding=max(4, int(6 * scale)))
    style.configure(
        "Accent.TButton",
        font=(_FONT, ui, "bold"),
        padding=max(6, int(8 * scale)),
    )
    style.configure("TEntry", font=(_FONT, ui))
    row_h = DENSITY_ROW.get(density, 26)
    style.configure(
        "Treeview",
        font=(_FONT, ui),
        rowheight=max(16, int(row_h * scale)),
    )
    style.configure("Treeview.Heading", font=(_FONT, ui, "bold"))
    if log is not None:
        log.configure(font=(_FONT, ui))
    try:
        import tkinter.font as tkfont

        for name, base in (
            ("TkDefaultFont", 10),
            ("TkTextFont", 10),
            ("TkHeadingFont", 10),
        ):
            tkfont.nametofont(name).configure(size=_pt(base, scale))
    except tk.TclError:
        pass
    return scale


def apply_dark_theme(root: tk.Tk) -> ttk.Style:
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", background=PANEL, foreground=FG, fieldbackground=FIELD)
    style.configure("TFrame", background=PANEL)
    style.configure("Header.TFrame", background=BG)
    style.configure("Status.TFrame", background=HEAD)
    style.configure("TLabel", background=PANEL, foreground=FG)
    style.configure("Hint.TLabel", background=PANEL, foreground=MUTED)
    style.configure(
        "Title.TLabel",
        background=PANEL,
        foreground=FG,
        font=("Segoe UI", 16, "bold"),
    )
    style.configure(
        "Brand.TLabel",
        background=BG,
        foreground=FG,
        font=("Segoe UI", 18, "bold"),
    )
    style.configure("Header.TLabel", background=BG, foreground=FG)
    style.configure("HeaderHint.TLabel", background=BG, foreground=MUTED)
    style.configure("Status.TLabel", background=HEAD, foreground=MUTED)
    style.configure("TButton", background=HEAD, foreground=FG, padding=6)
    style.map(
        "TButton",
        background=[("active", SELECT), ("disabled", "#2a2f38")],
        foreground=[("disabled", MUTED)],
    )
    style.configure(
        "Accent.TButton",
        background=ACCENT,
        foreground="#0b1a12",
        padding=8,
        font=("Segoe UI", 10, "bold"),
    )
    style.map(
        "Accent.TButton",
        background=[("active", "#5ef0ad"), ("disabled", "#2a4a3a")],
    )
    style.configure(
        "Call.TButton",
        background=HEAD,
        foreground=FG,
        padding=(10, 4),
    )
    style.configure("TEntry", fieldbackground=FIELD, foreground=FG, insertcolor=FG)
    style.map(
        "TEntry",
        fieldbackground=[("disabled", "#1a1d23")],
        foreground=[("disabled", MUTED)],
    )
    style.configure(
        "TCheckbutton",
        background=PANEL,
        foreground=FG,
        focuscolor=PANEL,
    )
    style.map(
        "TCheckbutton",
        background=[("active", PANEL)],
        foreground=[("disabled", MUTED)],
    )
    style.configure(
        "TCombobox",
        fieldbackground=FIELD,
        background=HEAD,
        foreground=FG,
        arrowcolor=FG,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", FIELD), ("disabled", "#1a1d23")],
        foreground=[("readonly", FG), ("disabled", MUTED)],
    )
    style.configure("TLabelframe", background=PANEL, foreground=FG)
    style.configure("TLabelframe.Label", background=PANEL, foreground=MUTED)
    style.configure("TNotebook", background=BG, bordercolor=HEAD)
    style.configure("TNotebook.Tab", background=HEAD, foreground=FG, padding=(14, 7))
    style.map(
        "TNotebook.Tab",
        background=[("selected", SELECT), ("active", ROW)],
        foreground=[("selected", FG)],
    )
    style.configure("TProgressbar", troughcolor=FIELD, background=ACCENT, bordercolor=HEAD)
    style.configure(
        "Treeview",
        background=ROW,
        fieldbackground=ROW,
        foreground=FG,
        rowheight=26,
        bordercolor=HEAD,
    )
    style.configure("Treeview.Heading", background=HEAD, foreground=FG, relief="flat")
    style.map(
        "Treeview.Heading",
        background=[("active", SELECT)],
        foreground=[("active", FG)],
    )
    style.map(
        "Treeview",
        background=[("selected", SELECT)],
        foreground=[("selected", FG)],
    )
    style.configure("TScrollbar", background=HEAD, troughcolor=FIELD, arrowcolor=FG)
    style.configure("TPanedwindow", background=PANEL)
    style.configure("TSeparator", background=HEAD)
    return style
