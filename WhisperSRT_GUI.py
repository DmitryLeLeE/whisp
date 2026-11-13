# -*- coding: utf-8 -*-
"""Whisper SRT: graphical interface for creating (and machine-translating) subtitles with faster-whisper."""
from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


_ffmpeg_dir = resource_path("ffmpeg_bin")
if _ffmpeg_dir.is_dir():
    os.environ["PATH"] = str(_ffmpeg_dir) + os.pathsep + os.environ.get("PATH", "")

import i18n  # noqa: E402
import translator as mt  # noqa: E402  (light import: heavy libraries are loaded on first use)
import whisper_universal as core  # noqa: E402  (light import: faster-whisper is loaded later)
from hub import Cancelled  # noqa: E402
from i18n import t  # noqa: E402

try:
    import sv_ttk
except Exception:  # the theme is optional
    sv_ttk = None

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # drag and drop is optional
    DND_FILES = None
    TkinterDnD = None

APP_USER_MODEL_ID = "DmitryLeLeE.WhisperSRT"
UI_LANGUAGE_NAMES = {"ru": "Русский", "en": "English"}
MODE_CODES = ("transcribe", "translate", "mt")
DEVICE_CODES = ("auto", "cpu")
MT_FRACTION = 0.15  # share of the progress bar given to translation when it is enabled

DEFAULT_SETTINGS = {
    "ui_language": "auto",
    "model": "small",
    "language": "ru",
    "mode": "transcribe",
    "mt_target": "en",
    "mt_variants": ["original", "translated"],
    "device": "auto",
    "model_dir": "",
    "output_dir": "",
    "overwrite": False,
    "notify": True,
    "formats": ["srt"],
    "split": False,
    "max_line_chars": 42,
    "max_lines": 2,
    "max_duration": 7.0,
    "theme": "system",
    "size": "",
    "input_dir": "",
}

THEME_COLORS = {
    "dark": {
        "log_bg": "#1c1c1c", "log_fg": "#e4e4e4",
        "done": "#6fd48a", "error": "#ff8080", "skip": "#9a9a9a", "work": "#6cb6ff",
    },
    "light": {
        "log_bg": "#ffffff", "log_fg": "#1a1a1a",
        "done": "#1b7f3b", "error": "#c62828", "skip": "#777777", "work": "#0b63ce",
    },
}


def app_title() -> str:
    return t("ui.title")


def language_labels() -> dict[str, str]:
    """Label -> code for the speech language list (current UI language)."""
    labels = {t("lang.auto"): "auto"}
    for code in mt.LANGUAGE_CODES:
        labels[t(f"lang.{code}")] = code
    return labels


def target_labels() -> dict[str, str]:
    return {t(f"lang.{code}"): code for code in mt.LANGUAGE_CODES}


def mode_labels() -> dict[str, str]:
    return {t(f"ui.mode.{code}"): code for code in MODE_CODES}


def device_labels() -> dict[str, str]:
    return {t(f"ui.device.{code}"): code for code in DEVICE_CODES}


def label_for(labels: dict[str, str], code: str) -> str:
    return next((label for label, value in labels.items() if value == code), next(iter(labels)))


# --------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------
def settings_path() -> Path:
    override = os.environ.get("WHISPERSRT_SETTINGS")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or os.path.join(str(Path.home()), ".config")
    return Path(base) / "WhisperSRT" / "settings.json"


def load_settings() -> dict:
    settings = {key: (list(value) if isinstance(value, list) else value) for key, value in DEFAULT_SETTINGS.items()}
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key, default in DEFAULT_SETTINGS.items():
                if key in data and isinstance(data[key], type(default)):
                    settings[key] = data[key]
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings: dict) -> None:
    path = settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def system_prefers_dark() -> bool:
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
        except Exception:
            return False
    return True


def set_titlebar_dark(root: tk.Misc, dark: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE on different Windows 10/11 builds
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def format_duration(seconds: float) -> str:
    if seconds <= 0:
        return "—"
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


def format_eta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return t("ui.eta.sec", s=seconds)
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return t("ui.eta.min", m=minutes, s=secs)
    hours, minutes = divmod(minutes, 60)
    return t("ui.eta.hour", h=hours, m=minutes)


# --------------------------------------------------------------------------------------
# Icon, taskbar identity and completion notification
# --------------------------------------------------------------------------------------
def set_app_user_model_id() -> None:
    """Lets Windows show our own icon in the taskbar instead of the Python one."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def apply_icon(root: tk.Tk) -> object | None:
    """Sets the window icon. Returns the PhotoImage that must be kept alive."""
    keep = None
    ico = resource_path("assets/icon.ico")
    png = resource_path("assets/icon.png")
    if sys.platform == "win32" and ico.is_file():
        try:
            root.iconbitmap(default=str(ico))
        except Exception:
            pass
    if png.is_file():
        try:
            keep = tk.PhotoImage(file=str(png))
            root.iconphoto(True, keep)
        except Exception:
            keep = None
    return keep


_TOAST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$title = [System.Security.SecurityElement]::Escape($env:WSRT_TITLE)
$text = [System.Security.SecurityElement]::Escape($env:WSRT_TEXT)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$title</text><text>$text</text></binding></visual></toast>")
$appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""


def notify_completion(root: tk.Tk, title: str, text: str) -> None:
    """Sound; and, if the window is not in the foreground, a taskbar flash and a Windows toast. Never raises."""
    try:
        if sys.platform == "win32":
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        else:
            root.bell()
    except Exception:
        pass
    if sys.platform != "win32":
        return
    try:
        in_background = root.focus_displayof() is None or root.state() == "iconic"
    except tk.TclError:
        in_background = True
    if not in_background:
        return
    try:
        import ctypes
        from ctypes import wintypes

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND), ("dwFlags", wintypes.DWORD),
                        ("uCount", wintypes.UINT), ("dwTimeout", wintypes.DWORD)]

        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x0000000F | 0x0000000C, 3, 0)  # ALL | TIMERNOFG
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except Exception:
        pass
    try:
        environment = dict(os.environ, WSRT_TITLE=title, WSRT_TEXT=text)
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", _TOAST_SCRIPT],
            env=environment, creationflags=0x08000000,  # CREATE_NO_WINDOW
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


class QueueLogHandler(logging.Handler):
    def __init__(self, target_queue: queue.Queue):
        super().__init__()
        self.target_queue = target_queue
        self.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.target_queue.put(("log", self.format(record)))
        except Exception:
            self.handleError(record)


class QueueStream:
    encoding = "utf-8"

    def __init__(self, target_queue: queue.Queue):
        self.target_queue = target_queue
        self._buffer = ""

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._buffer += str(text)
        while "\n" in self._buffer or "\r" in self._buffer:
            positions = [p for p in (self._buffer.find("\n"), self._buffer.find("\r")) if p >= 0]
            index = min(positions)
            line = self._buffer[:index].strip()
            self._buffer = self._buffer[index + 1:]
            if line:
                self.target_queue.put(("log", line))
        return len(text)

    def flush(self) -> None:
        line = self._buffer.strip()
        if line:
            self.target_queue.put(("log", line))
        self._buffer = ""

    def isatty(self) -> bool:
        return False

    def writable(self) -> bool:
        return True


@dataclass
class FileItem:
    path: Path
    iid: str
    duration: float = 0.0
    tracks: list = field(default_factory=list)  # [(stream index, label)]
    choice: object = "auto"  # "auto" or an FFmpeg stream index
    probed: bool = False
    status_key: str = "ui.st.reading"
    status_args: dict = field(default_factory=dict)
    status_tag: str = ""


class WhisperSRTApp:
    def __init__(self, root: tk.Tk, dnd: bool = False, configure_logging: bool = True):
        self.root = root
        self.dnd = dnd and DND_FILES is not None
        self.settings = load_settings()
        self.ui_language = i18n.set_language(self.settings["ui_language"])
        self.settings["ui_language"] = self.ui_language
        self.icon_image = apply_icon(root)
        self.root.title(app_title())
        self.root.minsize(940, 760)
        self.root.geometry(self.settings["size"] or "1060x900")

        self.messages: queue.Queue = queue.Queue()
        self.items: dict[str, FileItem] = {}
        self.item_order: list[str] = []
        self.counter = 0
        self.worker: threading.Thread | None = None
        self.stop_after_current = threading.Event()
        self.cancel_event = threading.Event()
        self.busy = False
        self.theme_mode = "dark"
        self.track_values: list[tuple[object, str]] = []
        self.status_key = "ui.stat.add_files"
        self.status_args: dict = {}
        self.status_eta = ""
        self.model_state = "checking"
        self.mt_state = "checking"
        self.outer: ttk.Frame | None = None

        s = self.settings
        self.model_var = tk.StringVar(value=s["model"] if s["model"] in core.MODEL_CHOICES else "small")
        self.language_var = tk.StringVar(value=label_for(language_labels(), s["language"]))
        self.mode_var = tk.StringVar(value=label_for(mode_labels(), s["mode"]))
        self.target_var = tk.StringVar(value=label_for(target_labels(), s["mt_target"]))
        self.device_var = tk.StringVar(value=label_for(device_labels(), s["device"]))
        self.ui_language_var = tk.StringVar(value=UI_LANGUAGE_NAMES[self.ui_language])
        self.model_dir_var = tk.StringVar(value=s["model_dir"])
        self.output_dir_var = tk.StringVar(value=s["output_dir"])
        self.overwrite_var = tk.BooleanVar(value=s["overwrite"])
        self.notify_var = tk.BooleanVar(value=s["notify"])
        self.format_vars = {fmt: tk.BooleanVar(value=fmt in s["formats"]) for fmt in core.OUTPUT_FORMATS}
        self.variant_vars = {v: tk.BooleanVar(value=v in s["mt_variants"]) for v in core.VARIANTS}
        self.split_var = tk.BooleanVar(value=s["split"])
        self.max_chars_var = tk.IntVar(value=s["max_line_chars"])
        self.max_lines_var = tk.IntVar(value=s["max_lines"])
        self.max_duration_var = tk.DoubleVar(value=s["max_duration"])
        self.track_var = tk.StringVar(value=t("ui.track.auto_label"))
        self.status_var = tk.StringVar(value="")
        self.model_status_var = tk.StringVar(value="")
        self.mt_status_var = tk.StringVar(value="")
        self.file_percent_var = tk.StringVar(value="0%")
        self.total_percent_var = tk.StringVar(value="0%")

        self._build_ui()
        if configure_logging:
            self._configure_logging()
        self._apply_theme(self._initial_theme())
        self._refresh_widget_states()
        self._on_selection_changed()
        self._set_status("ui.stat.add_files")
        self._refresh_model_status()
        self.model_var.trace_add("write", lambda *_: self._refresh_model_status())
        self.model_dir_var.trace_add("write", lambda *_: self._refresh_model_status())
        self.root.after(100, self._poll_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Control-o>", lambda _e: self._choose_files())
        self.root.bind("<Delete>", lambda _e: self._remove_selected())

    # ------------------------------------------------------------------ interface
    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=(16, 12, 16, 12))
        outer.pack(fill="both", expand=True)
        self.outer = outer
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=3)
        outer.rowconfigure(5, weight=2)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Whisper SRT", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(header, text=t("ui.subtitle", version=core.__version__), foreground="gray").grid(
            row=0, column=1, sticky="w", padx=(12, 0))
        self.ui_language_box = ttk.Combobox(header, textvariable=self.ui_language_var, state="readonly", width=10,
                                            values=[UI_LANGUAGE_NAMES[code] for code in i18n.LANGUAGES])
        self.ui_language_box.grid(row=0, column=2, sticky="e", padx=(0, 8))
        self.ui_language_box.bind("<<ComboboxSelected>>", lambda _e: self._on_ui_language_chosen())
        self.theme_button = ttk.Button(header, text=t("ui.theme"), width=16, command=self._toggle_theme)
        self.theme_button.grid(row=0, column=3, sticky="e")

        # --- files
        files_frame = ttk.LabelFrame(outer, text=t("ui.files"), padding=10)
        files_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        files_frame.columnconfigure(0, weight=1)
        files_frame.rowconfigure(1, weight=1)

        buttons = ttk.Frame(files_frame)
        buttons.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.choose_button = ttk.Button(buttons, text=t("ui.add_files"), command=self._choose_files)
        self.choose_button.pack(side="left")
        self.folder_button = ttk.Button(buttons, text=t("ui.add_folder"), command=self._choose_folder)
        self.folder_button.pack(side="left", padx=(8, 0))
        self.remove_button = ttk.Button(buttons, text=t("ui.remove_selected"), command=self._remove_selected)
        self.remove_button.pack(side="left", padx=(8, 0))
        self.clear_button = ttk.Button(buttons, text=t("ui.clear_list"), command=self._clear_files)
        self.clear_button.pack(side="left", padx=(8, 0))
        hint = t("ui.drop_hint") if self.dnd else ""
        ttk.Label(buttons, text=hint, foreground="gray").pack(side="right")

        columns = ("name", "duration", "track", "status")
        self.tree = ttk.Treeview(files_frame, columns=columns, show="headings", selectmode="extended", height=6)
        self.tree.heading("name", text=t("ui.col.file"))
        self.tree.heading("duration", text=t("ui.col.duration"))
        self.tree.heading("track", text=t("ui.col.track"))
        self.tree.heading("status", text=t("ui.col.status"))
        self.tree.column("name", width=380, anchor="w", stretch=True)
        self.tree.column("duration", width=100, anchor="center", stretch=False)
        self.tree.column("track", width=240, anchor="w", stretch=False)
        self.tree.column("status", width=180, anchor="w", stretch=False)
        tree_scroll = ttk.Scrollbar(files_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        tree_scroll.grid(row=1, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_selection_changed())

        track_row = ttk.Frame(files_frame)
        track_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        track_row.columnconfigure(1, weight=1)
        ttk.Label(track_row, text=t("ui.track.of_selected")).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.track_box = ttk.Combobox(track_row, textvariable=self.track_var, state="readonly",
                                      values=(t("ui.track.auto_label"),))
        self.track_box.grid(row=0, column=1, sticky="ew")
        self.track_box.bind("<<ComboboxSelected>>", lambda _e: self._on_track_chosen())

        if self.dnd:
            for widget in (self.tree, files_frame):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)

        # --- settings
        settings_row = ttk.Frame(outer)
        settings_row.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        settings_row.columnconfigure(0, weight=1, uniform="cols")
        settings_row.columnconfigure(1, weight=1, uniform="cols")

        recog = ttk.LabelFrame(settings_row, text=t("ui.recognition"), padding=10)
        recog.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        recog.columnconfigure(1, weight=1)

        ttk.Label(recog, text=t("ui.model")).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        model_cell = ttk.Frame(recog)
        model_cell.grid(row=0, column=1, sticky="ew", pady=3)
        model_cell.columnconfigure(0, weight=1)
        self.model_box = ttk.Combobox(model_cell, textvariable=self.model_var, values=core.MODEL_CHOICES,
                                      state="readonly", width=12)
        self.model_box.grid(row=0, column=0, sticky="ew")
        self.download_button = ttk.Button(model_cell, text=t("ui.download"), command=self._download_model)
        self.download_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(recog, textvariable=self.model_status_var, foreground="gray", wraplength=330).grid(
            row=1, column=1, sticky="w")

        ttk.Label(recog, text=t("ui.speech_language")).grid(row=2, column=0, sticky="w", padx=(0, 8), pady=3)
        self.language_box = ttk.Combobox(recog, textvariable=self.language_var, values=tuple(language_labels()),
                                         state="readonly")
        self.language_box.grid(row=2, column=1, sticky="ew", pady=3)

        ttk.Label(recog, text=t("ui.result")).grid(row=3, column=0, sticky="w", padx=(0, 8), pady=3)
        self.mode_box = ttk.Combobox(recog, textvariable=self.mode_var, values=tuple(mode_labels()), state="readonly")
        self.mode_box.grid(row=3, column=1, sticky="ew", pady=3)
        self.mode_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh_widget_states())

        ttk.Label(recog, text=t("ui.translate_to")).grid(row=4, column=0, sticky="w", padx=(0, 8), pady=3)
        self.target_box = ttk.Combobox(recog, textvariable=self.target_var, values=tuple(target_labels()),
                                       state="readonly")
        self.target_box.grid(row=4, column=1, sticky="ew", pady=3)
        ttk.Label(recog, textvariable=self.mt_status_var, foreground="gray", wraplength=330).grid(
            row=5, column=1, sticky="w")

        ttk.Label(recog, text=t("ui.device")).grid(row=6, column=0, sticky="w", padx=(0, 8), pady=3)
        self.device_box = ttk.Combobox(recog, textvariable=self.device_var, values=tuple(device_labels()),
                                       state="readonly")
        self.device_box.grid(row=6, column=1, sticky="ew", pady=3)

        ttk.Label(recog, text=t("ui.model_dir")).grid(row=7, column=0, sticky="w", padx=(0, 8), pady=3)
        model_dir_cell = ttk.Frame(recog)
        model_dir_cell.grid(row=7, column=1, sticky="ew", pady=3)
        model_dir_cell.columnconfigure(0, weight=1)
        self.model_dir_entry = ttk.Entry(model_dir_cell, textvariable=self.model_dir_var)
        self.model_dir_entry.grid(row=0, column=0, sticky="ew")
        self.model_dir_button = ttk.Button(model_dir_cell, text="…", width=3, command=self._choose_model_dir)
        self.model_dir_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(recog, text=t("ui.model_dir_hint"), foreground="gray").grid(row=8, column=1, sticky="w")

        result = ttk.LabelFrame(settings_row, text=t("ui.subtitles_and_saving"), padding=10)
        result.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        result.columnconfigure(0, weight=1)

        formats_row = ttk.Frame(result)
        formats_row.grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Label(formats_row, text=t("ui.formats")).pack(side="left", padx=(0, 8))
        self.format_checks = []
        for fmt in core.OUTPUT_FORMATS:
            check = ttk.Checkbutton(formats_row, text=fmt.upper(), variable=self.format_vars[fmt])
            check.pack(side="left", padx=(0, 10))
            self.format_checks.append(check)

        variants_row = ttk.Frame(result)
        variants_row.grid(row=1, column=0, sticky="w", pady=(0, 6))
        ttk.Label(variants_row, text=t("ui.variants")).pack(side="left", padx=(0, 8))
        self.variant_checks = []
        for variant in core.VARIANTS:
            check = ttk.Checkbutton(variants_row, text=t(f"ui.variant.{variant}"), variable=self.variant_vars[variant])
            check.pack(side="left", padx=(0, 10))
            self.variant_checks.append(check)

        self.split_check = ttk.Checkbutton(result, text=t("ui.split"), variable=self.split_var,
                                           command=self._refresh_widget_states)
        self.split_check.grid(row=2, column=0, sticky="w")

        limits = ttk.Frame(result)
        limits.grid(row=3, column=0, sticky="w", pady=(4, 0))
        ttk.Label(limits, text=t("ui.chars_per_line")).grid(row=0, column=0, sticky="w")
        ttk.Label(limits, text=t("ui.lines")).grid(row=0, column=1, sticky="w", padx=(14, 0))
        ttk.Label(limits, text=t("ui.cue_seconds")).grid(row=0, column=2, sticky="w", padx=(14, 0))
        self.max_chars_spin = ttk.Spinbox(limits, from_=10, to=80, increment=1, width=6,
                                          textvariable=self.max_chars_var)
        self.max_chars_spin.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.max_lines_spin = ttk.Spinbox(limits, from_=1, to=3, increment=1, width=6,
                                          textvariable=self.max_lines_var)
        self.max_lines_spin.grid(row=1, column=1, sticky="w", padx=(14, 0), pady=(2, 0))
        self.max_duration_spin = ttk.Spinbox(limits, from_=1, to=30, increment=0.5, width=8,
                                             textvariable=self.max_duration_var)
        self.max_duration_spin.grid(row=1, column=2, sticky="w", padx=(14, 0), pady=(2, 0))
        ttk.Label(result, text=t("ui.split_hint"), foreground="gray", wraplength=400).grid(
            row=4, column=0, sticky="w", pady=(4, 6))

        ttk.Label(result, text=t("ui.output_dir")).grid(row=5, column=0, sticky="w")
        out_cell = ttk.Frame(result)
        out_cell.grid(row=6, column=0, sticky="ew", pady=(2, 0))
        out_cell.columnconfigure(0, weight=1)
        self.output_entry = ttk.Entry(out_cell, textvariable=self.output_dir_var)
        self.output_entry.grid(row=0, column=0, sticky="ew")
        self.output_button = ttk.Button(out_cell, text=t("ui.choose"), command=self._choose_output)
        self.output_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(result, text=t("ui.output_dir_hint"), foreground="gray").grid(row=7, column=0, sticky="w")
        self.overwrite_check = ttk.Checkbutton(result, text=t("ui.overwrite"), variable=self.overwrite_var)
        self.overwrite_check.grid(row=8, column=0, sticky="w", pady=(6, 0))
        self.notify_check = ttk.Checkbutton(result, text=t("ui.notify"), variable=self.notify_var)
        self.notify_check.grid(row=9, column=0, sticky="w", pady=(4, 0))

        # --- actions
        action_row = ttk.Frame(outer)
        action_row.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        action_row.columnconfigure(4, weight=1)
        self.start_button = ttk.Button(action_row, text=t("ui.start"), command=self._start, style="Accent.TButton")
        self.start_button.grid(row=0, column=0)
        self.stop_button = ttk.Button(action_row, text=t("ui.stop_after"), command=self._request_stop, state="disabled")
        self.stop_button.grid(row=0, column=1, padx=(8, 0))
        self.cancel_button = ttk.Button(action_row, text=t("ui.cancel_now"), command=self._request_cancel,
                                        state="disabled")
        self.cancel_button.grid(row=0, column=2, padx=(8, 0))
        self.open_button = ttk.Button(action_row, text=t("ui.open_folder"), command=self._open_folder)
        self.open_button.grid(row=0, column=3, padx=(8, 0))
        ttk.Label(action_row, textvariable=self.status_var, anchor="w").grid(row=0, column=4, sticky="ew", padx=(14, 0))

        # --- progress
        progress = ttk.Frame(outer)
        progress.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        progress.columnconfigure(1, weight=1)
        ttk.Label(progress, text=t("ui.progress.file"), width=8).grid(row=0, column=0, sticky="w")
        self.file_bar = ttk.Progressbar(progress, orient="horizontal", mode="determinate", maximum=100.0)
        self.file_bar.grid(row=0, column=1, sticky="ew")
        ttk.Label(progress, textvariable=self.file_percent_var, width=6, anchor="e").grid(row=0, column=2, padx=(6, 0))
        ttk.Label(progress, text=t("ui.progress.total"), width=8).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.total_bar = ttk.Progressbar(progress, orient="horizontal", mode="determinate", maximum=100.0)
        self.total_bar.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        ttk.Label(progress, textvariable=self.total_percent_var, width=6, anchor="e").grid(
            row=1, column=2, padx=(6, 0), pady=(6, 0))

        # --- log
        log_frame = ttk.LabelFrame(outer, text=t("ui.log"), padding=6)
        log_frame.grid(row=5, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=6, wrap="word", state="disabled", font=("Consolas", 9),
                                relief="flat", borderwidth=0, padx=6, pady=4)
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

    # ------------------------------------------------------------------ language switch
    def _on_ui_language_chosen(self) -> None:
        chosen = next((code for code, name in UI_LANGUAGE_NAMES.items() if name == self.ui_language_var.get()),
                      self.ui_language)
        if chosen != self.ui_language:
            self._set_ui_language(chosen)

    def _set_ui_language(self, code: str) -> None:
        """Rebuilds the window in the new language, keeping every value the user entered."""
        old = {
            "language": language_labels().get(self.language_var.get(), "auto"),
            "mode": mode_labels().get(self.mode_var.get(), "transcribe"),
            "target": target_labels().get(self.target_var.get(), "en"),
            "device": device_labels().get(self.device_var.get(), "auto"),
        }
        log_content = self.log_text.get("1.0", "end-1c")
        file_percent = self.file_bar.cget("value")
        total_percent = self.total_bar.cget("value")

        if self.outer is not None:
            self.outer.destroy()
        self.ui_language = i18n.set_language(code)
        self.settings["ui_language"] = self.ui_language
        self.language_var.set(label_for(language_labels(), old["language"]))
        self.mode_var.set(label_for(mode_labels(), old["mode"]))
        self.target_var.set(label_for(target_labels(), old["target"]))
        self.device_var.set(label_for(device_labels(), old["device"]))
        self.ui_language_var.set(UI_LANGUAGE_NAMES[self.ui_language])
        self.track_var.set(t("ui.track.auto_label"))

        self._build_ui()
        self.root.title(app_title())
        self.log_text.configure(state="normal")
        self.log_text.insert("end", log_content)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        for iid in self.item_order:
            item = self.items[iid]
            self.tree.insert("", "end", iid=iid, values=(str(item.path), "", "", ""))
            self._render_item(item)
        self.file_bar.configure(value=file_percent)
        self.total_bar.configure(value=total_percent)
        self._apply_theme(self.theme_mode)
        self._set_controls_enabled(not self.busy)
        self.stop_button.configure(state="normal" if self.busy and self.worker_is_transcribing else "disabled")
        self.cancel_button.configure(state="normal" if self.busy and not self.cancel_event.is_set() else "disabled")
        self._on_selection_changed()
        self._render_status()
        self._render_model_status()

    worker_is_transcribing = False

    # ------------------------------------------------------------------ theme
    def _initial_theme(self) -> str:
        theme = self.settings["theme"]
        if theme in ("dark", "light"):
            return theme
        return "dark" if system_prefers_dark() else "light"

    def _apply_theme(self, mode: str) -> None:
        self.theme_mode = mode
        if sv_ttk is not None:
            try:
                sv_ttk.set_theme(mode, self.root)
            except TypeError:
                sv_ttk.set_theme(mode)
            except Exception:
                pass
        colors = THEME_COLORS[mode]
        self.log_text.configure(background=colors["log_bg"], foreground=colors["log_fg"],
                                insertbackground=colors["log_fg"])
        self.tree.tag_configure("done", foreground=colors["done"])
        self.tree.tag_configure("error", foreground=colors["error"])
        self.tree.tag_configure("skip", foreground=colors["skip"])
        self.tree.tag_configure("work", foreground=colors["work"])
        self.theme_button.configure(text=t("ui.theme_light") if mode == "dark" else t("ui.theme_dark"))
        set_titlebar_dark(self.root, mode == "dark")

    def _toggle_theme(self) -> None:
        self._apply_theme("light" if self.theme_mode == "dark" else "dark")
        self.settings["theme"] = self.theme_mode

    # ------------------------------------------------------------------ log and status
    def _configure_logging(self) -> None:
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(QueueLogHandler(self.messages))
        logging.getLogger("whisper_universal").setLevel(logging.INFO)
        # Capture standard output to show it in the window
        stream = QueueStream(self.messages)
        sys.stdout = stream  # type: ignore[assignment]
        sys.stderr = stream  # type: ignore[assignment]

    def _log(self, text: str) -> None:
        self.messages.put(("log", text))

    def _set_status(self, key: str, **kwargs) -> None:
        self.status_key, self.status_args, self.status_eta = key, kwargs, ""
        self._render_status()

    def _render_status(self) -> None:
        text = t(self.status_key, **self.status_args)
        if self.status_eta and self.busy:
            text = f"{text} · {self.status_eta}"
        self.status_var.set(text)

    # ------------------------------------------------------------------ file list
    def _choose_files(self) -> None:
        if self.busy:
            return
        patterns = " ".join(f"*{ext}" for ext in sorted(core.SUPPORTED_EXTENSIONS))
        chosen = filedialog.askopenfilenames(
            title=t("ui.dlg.choose_media"),
            initialdir=self.settings["input_dir"] or None,
            filetypes=[(t("ui.dlg.supported_media"), patterns), (t("ui.dlg.all_files"), "*.*")],
        )
        if chosen:
            self.settings["input_dir"] = str(Path(chosen[0]).parent)
            self._add_paths([Path(item) for item in chosen])

    def _choose_folder(self) -> None:
        if self.busy:
            return
        chosen = filedialog.askdirectory(title=t("ui.dlg.media_folder"),
                                         initialdir=self.settings["input_dir"] or None)
        if chosen:
            self.settings["input_dir"] = chosen
            self._add_paths([Path(chosen)])

    def _on_drop(self, event) -> None:
        if self.busy:
            return
        self._add_paths([Path(p) for p in self.root.tk.splitlist(event.data)])

    def _render_item(self, item: FileItem) -> None:
        if not self.tree.exists(item.iid):
            return
        duration = format_duration(item.duration) if item.probed else "…"
        self.tree.item(item.iid, values=(str(item.path), duration, self._track_text(item),
                                         t(item.status_key, **item.status_args)),
                       tags=(item.status_tag,) if item.status_tag else ())

    def _add_paths(self, paths: list[Path]) -> None:
        known = {item.path for item in self.items.values()}
        new_items: list[FileItem] = []
        for path in paths:
            candidates: list[Path]
            if path.is_dir():
                candidates = [p for p in sorted(path.iterdir(), key=lambda p: p.name.casefold())
                              if p.is_file() and p.suffix.lower() in core.SUPPORTED_EXTENSIONS]
                if not candidates:
                    self._log(t("ui.log.folder_empty", path=path))
                else:
                    self._log(t("ui.log.folder_added", name=path.name, count=len(candidates)))
            elif path.is_file():
                candidates = [path]
            else:
                continue
            for candidate in candidates:
                if candidate in known:
                    continue
                known.add(candidate)
                self.counter += 1
                iid = f"f{self.counter}"
                item = FileItem(path=candidate, iid=iid)
                self.items[iid] = item
                self.item_order.append(iid)
                self.tree.insert("", "end", iid=iid, values=(str(candidate), "…", "…", ""))
                self._render_item(item)
                new_items.append(item)
        if new_items:
            self._update_status_idle()
            threading.Thread(target=self._probe_worker, args=(new_items,), daemon=True).start()

    def _probe_worker(self, items: list[FileItem]) -> None:
        for item in items:
            try:
                duration, tracks = core.probe_audio_info(item.path)
                self.messages.put(("probed", item.iid, duration, tracks, ""))
            except Exception as exc:
                self.messages.put(("probed", item.iid, 0.0, [], str(exc)))

    def _remove_selected(self) -> None:
        if self.busy:
            return
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.items.pop(iid, None)
            if iid in self.item_order:
                self.item_order.remove(iid)
        self._on_selection_changed()
        self._update_status_idle()

    def _clear_files(self) -> None:
        if self.busy:
            return
        self.tree.delete(*self.tree.get_children())
        self.items.clear()
        self.item_order.clear()
        self._on_selection_changed()
        self._reset_progress()
        self._update_status_idle()

    def _update_status_idle(self) -> None:
        if self.busy:
            return
        count = len(self.items)
        if count:
            self._set_status("ui.stat.count", count=count)
        else:
            self._set_status("ui.stat.add_files")

    def _set_item(self, iid: str, key: str, tag: str = "", **kwargs) -> None:
        item = self.items.get(iid)
        if item is None:
            return
        item.status_key, item.status_args, item.status_tag = key, kwargs, tag
        self._render_item(item)

    def _track_text(self, item: FileItem) -> str:
        if not item.probed:
            return "…"
        if not item.tracks:
            return t("ui.track.none")
        if item.choice == "auto":
            return t("ui.track.auto_short")
        for index, label in item.tracks:
            if index == item.choice:
                return label
        return t("ui.track.auto_short")

    # ------------------------------------------------------------------ audio track choice
    def _selected_item(self) -> FileItem | None:
        selection = self.tree.selection()
        if len(selection) == 1:
            return self.items.get(selection[0])
        return None

    def _on_selection_changed(self) -> None:
        auto_label = t("ui.track.auto_label")
        item = self._selected_item()
        if item is None or not item.probed or len(item.tracks) < 1:
            self.track_box.configure(values=(auto_label,), state="disabled")
            self.track_var.set(auto_label)
            self.track_values = []
            return
        self.track_values = [("auto", auto_label)] + [(index, label) for index, label in item.tracks]
        self.track_box.configure(values=[label for _, label in self.track_values],
                                 state="readonly" if not self.busy else "disabled")
        current = next((label for value, label in self.track_values if value == item.choice), auto_label)
        self.track_var.set(current)

    def _on_track_chosen(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        label = self.track_var.get()
        item.choice = next((value for value, text in self.track_values if text == label), "auto")
        self.tree.set(item.iid, "track", self._track_text(item))

    # ------------------------------------------------------------------ parameters
    def _mode_code(self) -> str:
        return mode_labels().get(self.mode_var.get(), "transcribe")

    def _refresh_widget_states(self) -> None:
        """Enables the translation and splitting controls only when they apply."""
        idle = not self.busy
        mt_on = self._mode_code() == "mt" and idle
        self.target_box.configure(state="readonly" if mt_on else "disabled")
        for check in self.variant_checks:
            check.configure(state="normal" if mt_on else "disabled")
        spin_state = "normal" if self.split_var.get() and idle else "disabled"
        for spin in (self.max_chars_spin, self.max_lines_spin, self.max_duration_spin):
            spin.configure(state=spin_state)
        self._render_model_status()

    def _choose_output(self) -> None:
        chosen = filedialog.askdirectory(title=t("ui.dlg.output_folder"))
        if chosen:
            self.output_dir_var.set(chosen)

    def _choose_model_dir(self) -> None:
        chosen = filedialog.askdirectory(title=t("ui.dlg.model_folder"))
        if chosen:
            self.model_dir_var.set(chosen)

    def _model_dir(self) -> Path | None:
        text = self.model_dir_var.get().strip()
        return Path(text).expanduser() if text else None

    def _refresh_model_status(self) -> None:
        name = self.model_var.get()
        model_dir = self._model_dir()
        self.model_state = "checking"
        self.mt_state = "checking"
        self._render_model_status()

        def check() -> None:
            cached = core.find_cached_model(name, model_dir)
            self.messages.put(("modelstate", name, str(model_dir) if model_dir else "", cached is not None))
            translator_cached = mt.find_cached_translator(model_dir) is not None
            self.messages.put(("mtstate", str(model_dir) if model_dir else "", translator_cached))

        threading.Thread(target=check, daemon=True).start()

    def _render_model_status(self) -> None:
        self.model_status_var.set(t(f"ui.model.{self.model_state}"))
        if self._mode_code() == "mt":
            self.mt_status_var.set(t(f"ui.mt.{self.mt_state}"))
        else:
            self.mt_status_var.set(t("ui.mt.hint"))

    def _selected_variants(self) -> list[str]:
        return [v for v in core.VARIANTS if self.variant_vars[v].get()]

    def _collect_settings(self) -> dict:
        data = dict(self.settings)
        data.update({
            "ui_language": self.ui_language,
            "model": self.model_var.get(),
            "language": language_labels().get(self.language_var.get(), "auto"),
            "mode": self._mode_code(),
            "mt_target": target_labels().get(self.target_var.get(), "en"),
            "mt_variants": self._selected_variants(),
            "device": device_labels().get(self.device_var.get(), "auto"),
            "model_dir": self.model_dir_var.get().strip(),
            "output_dir": self.output_dir_var.get().strip(),
            "overwrite": bool(self.overwrite_var.get()),
            "notify": bool(self.notify_var.get()),
            "formats": [fmt for fmt, var in self.format_vars.items() if var.get()],
            "split": bool(self.split_var.get()),
            "theme": self.theme_mode,
        })
        try:
            data["max_line_chars"] = int(self.max_chars_var.get())
            data["max_lines"] = int(self.max_lines_var.get())
            data["max_duration"] = float(self.max_duration_var.get())
        except (tk.TclError, ValueError):
            pass
        try:
            data["size"] = f"{self.root.winfo_width()}x{self.root.winfo_height()}"
        except tk.TclError:
            pass
        return data

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        readonly = "readonly" if enabled else "disabled"
        for widget in (self.choose_button, self.folder_button, self.remove_button, self.clear_button,
                       self.start_button, self.output_button, self.output_entry, self.model_dir_entry,
                       self.model_dir_button, self.download_button, self.overwrite_check, self.split_check,
                       self.notify_check):
            widget.configure(state=state)
        for widget in (self.model_box, self.language_box, self.mode_box, self.device_box):
            widget.configure(state=readonly)
        for check in self.format_checks:
            check.configure(state=state)
        self._refresh_widget_states()
        self._on_selection_changed()

    def _reset_progress(self) -> None:
        self.file_bar.stop()
        self.file_bar.configure(mode="determinate", value=0.0)
        self.total_bar.configure(value=0.0)
        self.file_percent_var.set("0%")
        self.total_percent_var.set("0%")

    # ------------------------------------------------------------------ run
    def _validate_run_options(self) -> dict | None:
        title = app_title()
        if not self.items:
            messagebox.showwarning(title, t("ui.msg.add_first"))
            return None
        missing = [i.path for i in self.items.values() if not i.path.is_file()]
        if missing:
            messagebox.showerror(title, t("ui.msg.file_missing") + "\n" + "\n".join(map(str, missing[:5])))
            return None

        formats = [fmt for fmt, var in self.format_vars.items() if var.get()]
        if not formats:
            messagebox.showwarning(title, t("ui.msg.pick_format"))
            return None

        mode = self._mode_code()
        variants = ["original"]
        target = ""
        if mode == "mt":
            variants = self._selected_variants()
            if not variants:
                messagebox.showwarning(title, t("ui.msg.pick_variant"))
                return None
            target = target_labels().get(self.target_var.get(), "en")

        max_chars = max_lines = 0
        max_duration = 0.0
        if self.split_var.get():
            try:
                max_chars = int(self.max_chars_var.get())
                max_lines = int(self.max_lines_var.get())
                max_duration = float(self.max_duration_var.get())
                if not (10 <= max_chars <= 80 and 1 <= max_lines <= 3 and 1 <= max_duration <= 30):
                    raise ValueError
            except (tk.TclError, ValueError):
                messagebox.showerror(title, t("ui.msg.bad_split"))
                return None

        output_text = self.output_dir_var.get().strip()
        output_dir = Path(output_text).expanduser().resolve() if output_text else None
        if output_dir is not None:
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(title, t("ui.msg.output_dir_failed", error=exc))
                return None

        model_dir = self._model_dir()
        if model_dir is not None:
            try:
                model_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(title, t("ui.msg.model_dir_failed", error=exc))
                return None

        return {
            "files": [(self.items[iid].iid, self.items[iid].path, self.items[iid].choice,
                       self.items[iid].duration) for iid in self.item_order],
            "model_name": self.model_var.get().strip(),
            "language": language_labels().get(self.language_var.get(), "auto"),
            "task": "translate" if mode == "translate" else "transcribe",
            "translate_to": target,
            "variants": variants,
            "device_choice": device_labels().get(self.device_var.get(), "auto"),
            "output_dir": output_dir,
            "model_dir": model_dir,
            "overwrite": bool(self.overwrite_var.get()),
            "notify": bool(self.notify_var.get()),
            "formats": formats,
            "max_line_chars": max_chars,
            "max_lines": max_lines or 2,
            "max_duration": max_duration,
        }

    def _begin_work(self, target, options: dict, key: str, can_stop_after: bool = True, **status_args) -> None:
        self.stop_after_current.clear()
        self.cancel_event.clear()
        self.busy = True
        self.worker_is_transcribing = can_stop_after
        self._set_controls_enabled(False)
        self.stop_button.configure(state="normal" if can_stop_after else "disabled")
        self.cancel_button.configure(state="normal" if can_stop_after else "disabled")
        self._set_status(key, **status_args)
        self._reset_progress()
        self.worker = threading.Thread(target=target, kwargs={"options": options}, daemon=True)
        self.worker.start()

    def _start(self) -> None:
        if self.busy:
            return
        options = self._validate_run_options()
        if options is None:
            return
        save_settings(self._collect_settings())
        for iid in self.item_order:
            self._set_item(iid, "ui.st.queued")
        self._begin_work(self._worker_main, options, "ui.stat.preparing")

    def _download_model(self) -> None:
        if self.busy:
            return
        options = {"model_name": self.model_var.get().strip(), "model_dir": self._model_dir()}
        if options["model_dir"] is not None:
            try:
                options["model_dir"].mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(app_title(), t("ui.msg.model_dir_failed", error=exc))
                return
        self._begin_work(self._download_main, options, "ui.stat.downloading",
                         can_stop_after=False, name=options["model_name"])

    def _download_main(self, options: dict) -> None:
        name = options["model_name"]
        try:
            core.download_model(name, options["model_dir"],
                                lambda done, total: self.messages.put(("download", name, done, total)))
            self.messages.put(("status", "ui.stat.downloaded", {"name": name}))
        except Exception as exc:
            self.messages.put(("log", t("ui.log.download_error", error=exc)))
            self.messages.put(("log", traceback.format_exc()))
            self.messages.put(("status", "ui.stat.download_failed", {}))
        finally:
            self.messages.put(("finished", None))

    def _worker_main(self, options: dict) -> None:
        files = options["files"]
        model_name = options["model_name"]
        translate_to = options["translate_to"]
        wants_mt = bool(translate_to) and bool(set(options["variants"]) & {"translated", "bilingual"})
        transcribe_share = 1.0 - MT_FRACTION if wants_mt else 1.0
        successes = skipped = 0
        failures: list[tuple[Path, str]] = []
        cancelled = False
        put = self.messages.put
        try:
            put(("status", "ui.stat.checking_model", {"name": model_name}))
            core.download_model(model_name, options["model_dir"],
                                lambda done, total: put(("download", model_name, done, total)))
            if self.cancel_event.is_set():
                raise Cancelled()

            device = core.resolve_device(options["device_choice"])
            compute_type = core.get_compute_type(device)
            put(("status", "ui.stat.loading_model", {"name": model_name}))
            put(("log", t("ui.log.device", device=device, compute=compute_type)))
            model = core.create_model(model_name, device, compute_type, options["model_dir"])
            put(("log", t("ui.log.model_ready", name=model_name)))
            put(("modeldone", model_name))

            provider = None
            if wants_mt:
                put(("log", t("log.mt_license")))
                provider = core.TranslatorProvider(
                    device, options["model_dir"], lambda done, total: put(("download", "NLLB-200", done, total)))

            weights = [max(duration, 0.0) for _, _, _, duration in files]
            if not all(w > 0 for w in weights):
                weights = [1.0] * len(files)
            total_weight = sum(weights) or 1.0
            finished_weight = 0.0

            total_files = len(files)
            for number, (iid, source, choice, _duration) in enumerate(files, start=1):
                weight = weights[number - 1]
                if self.stop_after_current.is_set() or self.cancel_event.is_set():
                    put(("item", iid, "ui.st.not_processed", "skip", {}))
                    continue

                outputs = core.output_paths_for(source, options["output_dir"], None, options["formats"],
                                                options["variants"], translate_to)
                put(("fileprogress", 0.0, ""))
                put(("status", "ui.stat.processing", {"number": number, "total": total_files, "name": source.name}))
                put(("log", f"[{number}/{total_files}] {source}"))

                if not options["overwrite"] and all(p.exists() for p in outputs.values()):
                    put(("log", t("ui.log.skip_existing")))
                    put(("item", iid, "ui.st.skipped", "skip", {}))
                    skipped += 1
                    finished_weight += weight
                    put(("total", finished_weight / total_weight * 100.0))
                    continue

                args = SimpleNamespace(
                    audio_stream=choice, temp_dir=None, language=options["language"], task=options["task"],
                    beam_size=5, vad_filter=True, quiet_progress=True, device=options["device_choice"],
                    model_dir=options["model_dir"], max_line_chars=options["max_line_chars"],
                    max_lines=options["max_lines"], max_duration=options["max_duration"],
                    translate_to=translate_to, cancel_event=self.cancel_event,
                )
                started = time.monotonic()
                last = {"time": 0.0, "percent": -1.0}

                def on_progress(current: float, total: float, iid=iid, weight=weight, started=started,
                                base=finished_weight, last=last) -> None:
                    now = time.monotonic()
                    percent = max(0.0, min(100.0, (current / total) * 100.0 if total > 0 else 0.0))
                    if now - last["time"] < 0.25 and abs(percent - last["percent"]) < 0.5:
                        return
                    last["time"], last["percent"] = now, percent
                    eta = ""
                    if percent >= 3.0:
                        eta = t("ui.eta.left", eta=format_eta((now - started) * (100.0 - percent) / percent))
                    shown = percent * transcribe_share
                    put(("item", iid, "ui.st.transcribing", "work", {"percent": percent}))
                    put(("fileprogress", shown, eta))
                    put(("total", (base + weight * shown / 100.0) / total_weight * 100.0))

                def on_translate(done: int, count: int, iid=iid, weight=weight, base=finished_weight) -> None:
                    fraction = done / count if count else 1.0
                    shown = transcribe_share * 100.0 + MT_FRACTION * 100.0 * fraction
                    put(("item", iid, "ui.st.translating", "work", {"percent": fraction * 100.0}))
                    put(("fileprogress", shown, ""))
                    put(("total", (base + weight * shown / 100.0) / total_weight * 100.0))

                put(("item", iid, "ui.st.transcribing", "work", {"percent": 0.0}))
                try:
                    model, device = core.transcribe_one(
                        source, outputs, model, model_name, device, args, progress_callback=on_progress,
                        translator_provider=provider, translate_progress=on_translate)
                    successes += 1
                    put(("item", iid, "ui.st.done", "done", {}))
                    put(("fileprogress", 100.0, ""))
                except Cancelled:
                    cancelled = True
                    put(("item", iid, "ui.st.cancelled", "skip", {}))
                    put(("log", t("ui.log.cancelled_file", name=source.name)))
                    finished_weight += weight
                    continue
                except Exception as exc:
                    failures.append((source, str(exc)))
                    put(("item", iid, "ui.st.error", "error", {}))
                    put(("log", t("ui.log.file_error", name=source.name, error=exc)))
                    put(("log", traceback.format_exc()))
                finished_weight += weight
                put(("total", finished_weight / total_weight * 100.0))

            cancelled = cancelled or self.cancel_event.is_set()
            put(("log", "=" * 56))
            put(("log", t("ui.log.summary", ok=successes, skipped=skipped, failed=len(failures))))
            if failures:
                put(("log", t("log.failed_header")))
                for source, error in failures:
                    put(("log", f"  {source.name}: {error}"))
            if cancelled:
                put(("status", "ui.stat.cancelled", {}))
            elif self.stop_after_current.is_set():
                put(("status", "ui.stat.stopped", {}))
            elif failures:
                put(("status", "ui.stat.done_errors", {"count": len(failures)}))
            else:
                put(("status", "ui.stat.done", {"ok": successes, "skipped": skipped}))
            if options["notify"] and not cancelled:
                put(("notify", successes, skipped, len(failures)))
        except Cancelled:
            put(("log", t("ui.log.cancelled")))
            put(("status", "ui.stat.cancelled", {}))
        except Exception as exc:
            put(("log", t("ui.log.fatal", error=exc)))
            put(("log", traceback.format_exc()))
            put(("status", "ui.stat.fatal", {}))
        finally:
            put(("finished", None))

    def _request_stop(self) -> None:
        if self.busy:
            self.stop_after_current.set()
            self.stop_button.configure(state="disabled")
            self._set_status("ui.stat.stopping")
            self._log(t("ui.log.stop_requested"))

    def _request_cancel(self) -> None:
        if self.busy:
            self.cancel_event.set()
            self.stop_after_current.set()
            self.stop_button.configure(state="disabled")
            self.cancel_button.configure(state="disabled")
            self._set_status("ui.stat.cancelling")
            self._log(t("ui.log.cancel_requested"))

    def _open_folder(self) -> None:
        target: Path | None = None
        output_text = self.output_dir_var.get().strip()
        if output_text:
            target = Path(output_text).expanduser()
        else:
            item = self._selected_item() or (self.items[self.item_order[0]] if self.item_order else None)
            if item is not None:
                target = item.path.parent
        if target is None or not target.is_dir():
            messagebox.showinfo(app_title(), t("ui.msg.no_folder"))
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as exc:
            messagebox.showerror(app_title(), t("ui.msg.open_failed", error=exc))

    # ------------------------------------------------------------------ message queue
    def _poll_queue(self) -> None:
        try:
            while True:
                message = self.messages.get_nowait()
                self._handle_message(message)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _handle_message(self, message: tuple) -> None:
        kind = message[0]
        if kind == "log":
            self.log_text.configure(state="normal")
            self.log_text.insert("end", str(message[1]) + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        elif kind == "status":
            _, key, args = message
            self._set_status(key, **args)
        elif kind == "item":
            _, iid, key, tag, args = message
            self._set_item(iid, key, tag, **args)
        elif kind == "probed":
            _, iid, duration, tracks, error = message
            item = self.items.get(iid)
            if item is None or not self.tree.exists(iid):
                return
            item.probed = True
            item.duration = duration
            item.tracks = tracks
            if error:
                self._set_item(iid, "ui.st.unreadable", "error")
                self._log(t("ui.log.read_failed", name=item.path.name, error=error))
            elif not tracks:
                self._set_item(iid, "ui.st.no_audio", "error")
            else:
                self._set_item(iid, "ui.st.ready")
            if self._selected_item() is item:
                self._on_selection_changed()
        elif kind == "fileprogress":
            _, percent, eta = message
            if str(self.file_bar.cget("mode")) != "determinate":
                self.file_bar.stop()
                self.file_bar.configure(mode="determinate")
            self.file_bar.configure(value=percent)
            self.file_percent_var.set(f"{percent:.0f}%")
            if self.busy and eta != self.status_eta and (eta or not self.status_eta):
                self.status_eta = eta
                self._render_status()
        elif kind == "total":
            percent = float(message[1])
            self.total_bar.configure(value=percent)
            self.total_percent_var.set(f"{percent:.0f}%")
        elif kind == "download":
            _, name, done, total = message
            if total > 0:
                percent = min(100.0, done * 100.0 / total)
                if str(self.file_bar.cget("mode")) != "determinate":
                    self.file_bar.stop()
                    self.file_bar.configure(mode="determinate")
                self.file_bar.configure(value=percent)
                self.file_percent_var.set(f"{percent:.0f}%")
                self._set_status("ui.stat.dl_progress", name=name, done=done / 1048576, total=total / 1048576)
            else:
                self._set_status("ui.stat.dl_unknown", name=name, done=done / 1048576)
        elif kind == "modelstate":
            _, name, model_dir, cached = message
            current_dir = str(self._model_dir()) if self._model_dir() else ""
            if name == self.model_var.get() and model_dir == current_dir:
                self.model_state = "cached" if cached else "missing"
                self._render_model_status()
        elif kind == "mtstate":
            _, model_dir, cached = message
            current_dir = str(self._model_dir()) if self._model_dir() else ""
            if model_dir == current_dir:
                self.mt_state = "cached" if cached else "missing"
                self._render_model_status()
        elif kind == "modeldone":
            if message[1] == self.model_var.get():
                self.model_state = "cached"
                self._render_model_status()
        elif kind == "notify":
            _, ok, skipped, failed = message
            key = "ui.notify.done_errors" if failed else "ui.notify.done"
            notify_completion(self.root, app_title(), t(key, ok=ok, skipped=skipped, failed=failed))
        elif kind == "finished":
            self.busy = False
            self.worker = None
            self.worker_is_transcribing = False
            self._set_controls_enabled(True)
            self.stop_button.configure(state="disabled")
            self.cancel_button.configure(state="disabled")
            self.file_bar.configure(mode="determinate")
            self._refresh_model_status()

    def _on_close(self) -> None:
        if self.busy:
            close_now = messagebox.askyesno(app_title(), t("ui.msg.confirm_exit"))
            if not close_now:
                return
            self.cancel_event.set()
        save_settings(self._collect_settings())
        self.root.destroy()


def create_root() -> tuple[tk.Tk, bool]:
    if TkinterDnD is not None:
        try:
            return TkinterDnD.Tk(), True
        except Exception:
            pass
    return tk.Tk(), False


def run_selftest() -> int:
    """Checks the built application without user interaction. The result is written to a log in the temp folder."""
    log_path = Path(tempfile.gettempdir()) / "whispersrt_selftest.log"
    lines: list[str] = []
    ok = True

    def check(name: str, func) -> None:
        nonlocal ok
        try:
            lines.append(f"OK    {name}: {func()}")
        except Exception:
            ok = False
            lines.append(f"FAIL  {name}:\n{traceback.format_exc()}")

    def check_import(module: str):
        def run():
            imported = __import__(module)
            return getattr(imported, "__version__", "")
        return run

    def check_ffmpeg():
        found = []
        for tool in ("ffmpeg", "ffprobe"):
            path = shutil.which(tool)
            if not path:
                raise RuntimeError(f"{tool} not found in PATH")
            result = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                raise RuntimeError(f"{tool} returned code {result.returncode}")
            found.append(path)
        return ", ".join(found)

    def check_vad_asset():
        import faster_whisper
        assets = list((Path(faster_whisper.__file__).parent / "assets").glob("*.onnx"))
        if not assets:
            raise RuntimeError("VAD file is missing (assets/*.onnx)")
        return assets[0].name

    def check_icon():
        missing = [name for name in ("assets/icon.ico", "assets/icon.png") if not resource_path(name).is_file()]
        if missing:
            raise RuntimeError("missing: " + ", ".join(missing))
        return "ok"

    def check_translations():
        problems = i18n.check_parity()
        if problems:
            raise RuntimeError("; ".join(problems[:5]))
        return f"{len(i18n.RU)} strings"

    def check_translator_stack():
        import ctranslate2
        import sentencepiece
        processor = sentencepiece.SentencePieceProcessor()
        return f"ctranslate2 {ctranslate2.__version__}, sentencepiece {sentencepiece.__version__}, class {mt.SubtitleTranslator.__name__}"

    def check_ui():
        os.environ["WHISPERSRT_SETTINGS"] = str(Path(tempfile.gettempdir()) / "whispersrt_selftest_settings.json")
        root, dnd = create_root()
        try:
            root.withdraw()
            app = WhisperSRTApp(root, dnd=dnd, configure_logging=False)
            root.update()
            app._apply_theme("light")
            app._apply_theme("dark")
            for code in ("ru", "en"):
                app._set_ui_language(code)
                root.update()
            save_settings(app._collect_settings())
            if load_settings()["model"] != app.model_var.get():
                raise RuntimeError("settings are not saved")
            return f"theme={'sv_ttk' if sv_ttk else 'default'}, dnd={'yes' if app.dnd else 'no'}"
        finally:
            root.destroy()

    for module in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "huggingface_hub", "ffmpeg", "sentencepiece"):
        check(f"import {module}", check_import(module))
    check("FFmpeg", check_ffmpeg)
    check("VAD file", check_vad_asset)
    check("translator stack", check_translator_stack)
    check("icon", check_icon)
    check("translations", check_translations)
    check("app window", check_ui)

    lines.append("RESULT: " + ("all good" if ok else "there are errors"))
    try:
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
    if sys.stdout is not None:
        print("\n".join(lines))
    return 0 if ok else 1


def main() -> None:
    set_app_user_model_id()
    root, dnd = create_root()
    WhisperSRTApp(root, dnd=dnd)
    root.mainloop()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(run_selftest())
    main()
