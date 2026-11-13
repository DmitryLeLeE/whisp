# -*- coding: utf-8 -*-
"""Whisper SRT: графический интерфейс для создания субтитров на faster-whisper."""
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

import whisper_universal as core  # noqa: E402  (лёгкий импорт: faster-whisper подгружается позже)

try:
    import sv_ttk
except Exception:  # тема не обязательна
    sv_ttk = None

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # перетаскивание файлов не обязательно
    DND_FILES = None
    TkinterDnD = None

APP_TITLE = "Whisper SRT — субтитры"
LANGUAGES = {
    "Автоопределение": "auto",
    "Русский": "ru",
    "English": "en",
    "Deutsch": "de",
    "Українська": "uk",
    "Français": "fr",
    "Español": "es",
    "Italiano": "it",
    "Polski": "pl",
    "日本語": "ja",
    "中文": "zh",
}
MODES = {
    "Субтитры на языке речи": "transcribe",
    "Перевод на английский": "translate",
}
DEVICES = {"Автоматически": "auto", "CPU": "cpu"}
AUTO_TRACK_LABEL = "Авто (как задано в файле)"

DEFAULT_SETTINGS = {
    "model": "small",
    "language": "ru",
    "mode": "transcribe",
    "device": "auto",
    "model_dir": "",
    "output_dir": "",
    "overwrite": False,
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


# --------------------------------------------------------------------------------------
# Настройки
# --------------------------------------------------------------------------------------
def settings_path() -> Path:
    override = os.environ.get("WHISPERSRT_SETTINGS")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or os.path.join(str(Path.home()), ".config")
    return Path(base) / "WhisperSRT" / "settings.json"


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
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
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE в разных версиях Windows 10/11
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
        return f"{seconds} с"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} мин {secs:02} с"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} ч {minutes:02} мин"


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
    tracks: list = field(default_factory=list)  # [(индекс потока, подпись)]
    choice: object = "auto"  # "auto" или индекс потока FFmpeg
    probed: bool = False


class WhisperSRTApp:
    def __init__(self, root: tk.Tk, dnd: bool = False, configure_logging: bool = True):
        self.root = root
        self.dnd = dnd and DND_FILES is not None
        self.settings = load_settings()
        self.root.title(APP_TITLE)
        self.root.minsize(900, 700)
        self.root.geometry(self.settings["size"] or "1020x860")

        self.messages: queue.Queue = queue.Queue()
        self.items: dict[str, FileItem] = {}
        self.item_order: list[str] = []
        self.counter = 0
        self.worker: threading.Thread | None = None
        self.stop_after_current = threading.Event()
        self.busy = False
        self.theme_mode = "dark"
        self.track_values: list[tuple[object, str]] = []

        s = self.settings
        language_label = next((k for k, v in LANGUAGES.items() if v == s["language"]), "Русский")
        mode_label = next((k for k, v in MODES.items() if v == s["mode"]), next(iter(MODES)))
        device_label = next((k for k, v in DEVICES.items() if v == s["device"]), "Автоматически")

        self.model_var = tk.StringVar(value=s["model"] if s["model"] in core.MODEL_CHOICES else "small")
        self.language_var = tk.StringVar(value=language_label)
        self.mode_var = tk.StringVar(value=mode_label)
        self.device_var = tk.StringVar(value=device_label)
        self.model_dir_var = tk.StringVar(value=s["model_dir"])
        self.output_dir_var = tk.StringVar(value=s["output_dir"])
        self.overwrite_var = tk.BooleanVar(value=s["overwrite"])
        self.format_vars = {fmt: tk.BooleanVar(value=fmt in s["formats"]) for fmt in core.OUTPUT_FORMATS}
        self.split_var = tk.BooleanVar(value=s["split"])
        self.max_chars_var = tk.IntVar(value=s["max_line_chars"])
        self.max_lines_var = tk.IntVar(value=s["max_lines"])
        self.max_duration_var = tk.DoubleVar(value=s["max_duration"])
        self.track_var = tk.StringVar(value=AUTO_TRACK_LABEL)
        self.status_var = tk.StringVar(value="Добавьте аудио- или видеофайлы.")
        self.model_status_var = tk.StringVar(value="")
        self.file_percent_var = tk.StringVar(value="0%")
        self.total_percent_var = tk.StringVar(value="0%")
        self.model_dir_hint_var = tk.StringVar(value="")

        self._build_ui()
        if configure_logging:
            self._configure_logging()
        self._apply_theme(self._initial_theme())
        self._on_split_toggle()
        self._on_selection_changed()
        self._refresh_model_status()
        self.model_var.trace_add("write", lambda *_: self._refresh_model_status())
        self.model_dir_var.trace_add("write", lambda *_: self._refresh_model_status())
        self.root.after(100, self._poll_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Control-o>", lambda _e: self._choose_files())
        self.root.bind("<Delete>", lambda _e: self._remove_selected())

    # ------------------------------------------------------------------ интерфейс
    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=(16, 12, 16, 12))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=3)
        outer.rowconfigure(5, weight=2)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Whisper SRT", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(header, text=f"v{core.__version__} · локальное распознавание речи на faster-whisper",
                  foreground="gray").grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.theme_button = ttk.Button(header, text="Тема", width=16, command=self._toggle_theme)
        self.theme_button.grid(row=0, column=2, sticky="e")

        # --- файлы
        files_frame = ttk.LabelFrame(outer, text="Файлы", padding=10)
        files_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        files_frame.columnconfigure(0, weight=1)
        files_frame.rowconfigure(1, weight=1)

        buttons = ttk.Frame(files_frame)
        buttons.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.choose_button = ttk.Button(buttons, text="Добавить файлы…", command=self._choose_files)
        self.choose_button.pack(side="left")
        self.folder_button = ttk.Button(buttons, text="Добавить папку…", command=self._choose_folder)
        self.folder_button.pack(side="left", padx=(8, 0))
        self.remove_button = ttk.Button(buttons, text="Убрать выбранные", command=self._remove_selected)
        self.remove_button.pack(side="left", padx=(8, 0))
        self.clear_button = ttk.Button(buttons, text="Очистить список", command=self._clear_files)
        self.clear_button.pack(side="left", padx=(8, 0))
        hint = "Файлы можно перетащить в список." if self.dnd else ""
        ttk.Label(buttons, text=hint, foreground="gray").pack(side="right")

        columns = ("name", "duration", "track", "status")
        self.tree = ttk.Treeview(files_frame, columns=columns, show="headings", selectmode="extended", height=7)
        self.tree.heading("name", text="Файл")
        self.tree.heading("duration", text="Длительность")
        self.tree.heading("track", text="Аудиодорожка")
        self.tree.heading("status", text="Состояние")
        self.tree.column("name", width=380, anchor="w", stretch=True)
        self.tree.column("duration", width=100, anchor="center", stretch=False)
        self.tree.column("track", width=240, anchor="w", stretch=False)
        self.tree.column("status", width=170, anchor="w", stretch=False)
        tree_scroll = ttk.Scrollbar(files_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        tree_scroll.grid(row=1, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_selection_changed())

        track_row = ttk.Frame(files_frame)
        track_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        track_row.columnconfigure(1, weight=1)
        ttk.Label(track_row, text="Аудиодорожка выбранного файла:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.track_box = ttk.Combobox(track_row, textvariable=self.track_var, state="readonly", values=(AUTO_TRACK_LABEL,))
        self.track_box.grid(row=0, column=1, sticky="ew")
        self.track_box.bind("<<ComboboxSelected>>", lambda _e: self._on_track_chosen())

        if self.dnd:
            for widget in (self.tree, files_frame):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)

        # --- настройки
        settings_row = ttk.Frame(outer)
        settings_row.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        settings_row.columnconfigure(0, weight=1, uniform="cols")
        settings_row.columnconfigure(1, weight=1, uniform="cols")

        recog = ttk.LabelFrame(settings_row, text="Распознавание", padding=10)
        recog.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        recog.columnconfigure(1, weight=1)

        ttk.Label(recog, text="Модель:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        model_cell = ttk.Frame(recog)
        model_cell.grid(row=0, column=1, sticky="ew", pady=4)
        model_cell.columnconfigure(0, weight=1)
        self.model_box = ttk.Combobox(model_cell, textvariable=self.model_var, values=core.MODEL_CHOICES,
                                      state="readonly", width=12)
        self.model_box.grid(row=0, column=0, sticky="ew")
        self.download_button = ttk.Button(model_cell, text="Скачать", command=self._download_model)
        self.download_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(recog, textvariable=self.model_status_var, foreground="gray", wraplength=330).grid(
            row=1, column=1, sticky="w")

        ttk.Label(recog, text="Язык речи:").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        self.language_box = ttk.Combobox(recog, textvariable=self.language_var, values=tuple(LANGUAGES),
                                         state="readonly")
        self.language_box.grid(row=2, column=1, sticky="ew", pady=4)

        ttk.Label(recog, text="Результат:").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        self.mode_box = ttk.Combobox(recog, textvariable=self.mode_var, values=tuple(MODES), state="readonly")
        self.mode_box.grid(row=3, column=1, sticky="ew", pady=4)

        ttk.Label(recog, text="Устройство:").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=4)
        self.device_box = ttk.Combobox(recog, textvariable=self.device_var, values=tuple(DEVICES), state="readonly")
        self.device_box.grid(row=4, column=1, sticky="ew", pady=4)

        ttk.Label(recog, text="Папка моделей:").grid(row=5, column=0, sticky="w", padx=(0, 8), pady=4)
        model_dir_cell = ttk.Frame(recog)
        model_dir_cell.grid(row=5, column=1, sticky="ew", pady=4)
        model_dir_cell.columnconfigure(0, weight=1)
        self.model_dir_entry = ttk.Entry(model_dir_cell, textvariable=self.model_dir_var)
        self.model_dir_entry.grid(row=0, column=0, sticky="ew")
        self.model_dir_button = ttk.Button(model_dir_cell, text="…", width=3, command=self._choose_model_dir)
        self.model_dir_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(recog, text="Пусто: стандартный кэш Hugging Face.", foreground="gray").grid(
            row=6, column=1, sticky="w")

        result = ttk.LabelFrame(settings_row, text="Субтитры и сохранение", padding=10)
        result.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        result.columnconfigure(0, weight=1)

        formats_row = ttk.Frame(result)
        formats_row.grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Label(formats_row, text="Форматы:").pack(side="left", padx=(0, 8))
        self.format_checks = []
        for fmt in core.OUTPUT_FORMATS:
            check = ttk.Checkbutton(formats_row, text=fmt.upper(), variable=self.format_vars[fmt])
            check.pack(side="left", padx=(0, 10))
            self.format_checks.append(check)

        self.split_check = ttk.Checkbutton(result, text="Разбивать на короткие реплики",
                                           variable=self.split_var, command=self._on_split_toggle)
        self.split_check.grid(row=1, column=0, sticky="w")

        limits = ttk.Frame(result)
        limits.grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Label(limits, text="Символов в строке").grid(row=0, column=0, sticky="w")
        ttk.Label(limits, text="Строк").grid(row=0, column=1, sticky="w", padx=(14, 0))
        ttk.Label(limits, text="Длительность, с").grid(row=0, column=2, sticky="w", padx=(14, 0))
        self.max_chars_spin = ttk.Spinbox(limits, from_=10, to=80, increment=1, width=6,
                                          textvariable=self.max_chars_var)
        self.max_chars_spin.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.max_lines_spin = ttk.Spinbox(limits, from_=1, to=3, increment=1, width=6,
                                          textvariable=self.max_lines_var)
        self.max_lines_spin.grid(row=1, column=1, sticky="w", padx=(14, 0), pady=(2, 0))
        self.max_duration_spin = ttk.Spinbox(limits, from_=1, to=30, increment=0.5, width=8,
                                             textvariable=self.max_duration_var)
        self.max_duration_spin.grid(row=1, column=2, sticky="w", padx=(14, 0), pady=(2, 0))
        ttk.Label(result, text="При разбиении модель размечает время по словам, это немного медленнее.",
                  foreground="gray", wraplength=400).grid(row=3, column=0, sticky="w", pady=(4, 8))

        ttk.Label(result, text="Папка для результатов:").grid(row=4, column=0, sticky="w")
        out_cell = ttk.Frame(result)
        out_cell.grid(row=5, column=0, sticky="ew", pady=(2, 0))
        out_cell.columnconfigure(0, weight=1)
        self.output_entry = ttk.Entry(out_cell, textvariable=self.output_dir_var)
        self.output_entry.grid(row=0, column=0, sticky="ew")
        self.output_button = ttk.Button(out_cell, text="Выбрать…", command=self._choose_output)
        self.output_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(result, text="Пусто: рядом с исходными файлами.", foreground="gray").grid(
            row=6, column=0, sticky="w")
        self.overwrite_check = ttk.Checkbutton(result, text="Перезаписывать существующие файлы",
                                               variable=self.overwrite_var)
        self.overwrite_check.grid(row=7, column=0, sticky="w", pady=(6, 0))

        # --- действия
        action_row = ttk.Frame(outer)
        action_row.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        action_row.columnconfigure(3, weight=1)
        self.start_button = ttk.Button(action_row, text="Создать субтитры", command=self._start, style="Accent.TButton")
        self.start_button.grid(row=0, column=0)
        self.stop_button = ttk.Button(action_row, text="Остановить после текущего файла",
                                      command=self._request_stop, state="disabled")
        self.stop_button.grid(row=0, column=1, padx=(8, 0))
        self.open_button = ttk.Button(action_row, text="Открыть папку", command=self._open_folder)
        self.open_button.grid(row=0, column=2, padx=(8, 0))
        ttk.Label(action_row, textvariable=self.status_var, anchor="w").grid(row=0, column=3, sticky="ew", padx=(14, 0))

        # --- прогресс
        progress = ttk.Frame(outer)
        progress.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        progress.columnconfigure(1, weight=1)
        ttk.Label(progress, text="Файл:", width=7).grid(row=0, column=0, sticky="w")
        self.file_bar = ttk.Progressbar(progress, orient="horizontal", mode="determinate", maximum=100.0)
        self.file_bar.grid(row=0, column=1, sticky="ew")
        ttk.Label(progress, textvariable=self.file_percent_var, width=6, anchor="e").grid(row=0, column=2, padx=(6, 0))
        ttk.Label(progress, text="Всего:", width=7).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.total_bar = ttk.Progressbar(progress, orient="horizontal", mode="determinate", maximum=100.0)
        self.total_bar.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        ttk.Label(progress, textvariable=self.total_percent_var, width=6, anchor="e").grid(
            row=1, column=2, padx=(6, 0), pady=(6, 0))

        # --- журнал
        log_frame = ttk.LabelFrame(outer, text="Журнал работы", padding=6)
        log_frame.grid(row=5, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=7, wrap="word", state="disabled", font=("Consolas", 9),
                                relief="flat", borderwidth=0, padx=6, pady=4)
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

    # ------------------------------------------------------------------ тема
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
        self.theme_button.configure(text="Светлая тема" if mode == "dark" else "Тёмная тема")
        set_titlebar_dark(self.root, mode == "dark")

    def _toggle_theme(self) -> None:
        self._apply_theme("light" if self.theme_mode == "dark" else "dark")
        self.settings["theme"] = self.theme_mode

    # ------------------------------------------------------------------ журнал
    def _configure_logging(self) -> None:
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(QueueLogHandler(self.messages))
        logging.getLogger("whisper_universal").setLevel(logging.INFO)
        # Перехватываем стандартный вывод для отображения в окне GUI
        stream = QueueStream(self.messages)
        sys.stdout = stream  # type: ignore[assignment]
        sys.stderr = stream  # type: ignore[assignment]

    def _log(self, text: str) -> None:
        self.messages.put(("log", text))

    # ------------------------------------------------------------------ список файлов
    def _choose_files(self) -> None:
        if self.busy:
            return
        patterns = " ".join(f"*{ext}" for ext in sorted(core.SUPPORTED_EXTENSIONS))
        chosen = filedialog.askopenfilenames(
            title="Выберите медиафайлы",
            initialdir=self.settings["input_dir"] or None,
            filetypes=[("Поддерживаемые медиафайлы", patterns), ("Все файлы", "*.*")],
        )
        if chosen:
            self.settings["input_dir"] = str(Path(chosen[0]).parent)
            self._add_paths([Path(item) for item in chosen])

    def _choose_folder(self) -> None:
        if self.busy:
            return
        chosen = filedialog.askdirectory(title="Папка с медиафайлами",
                                         initialdir=self.settings["input_dir"] or None)
        if chosen:
            self.settings["input_dir"] = chosen
            self._add_paths([Path(chosen)])

    def _on_drop(self, event) -> None:
        if self.busy:
            return
        self._add_paths([Path(p) for p in self.root.tk.splitlist(event.data)])

    def _add_paths(self, paths: list[Path]) -> None:
        known = {item.path for item in self.items.values()}
        new_items: list[FileItem] = []
        for path in paths:
            candidates: list[Path]
            if path.is_dir():
                candidates = [p for p in sorted(path.iterdir(), key=lambda p: p.name.casefold())
                              if p.is_file() and p.suffix.lower() in core.SUPPORTED_EXTENSIONS]
                if not candidates:
                    self._log(f"В папке нет поддерживаемых файлов: {path}")
                else:
                    self._log(f"Из папки {path.name} добавлено файлов: {len(candidates)} (без вложенных папок).")
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
                self.tree.insert("", "end", iid=iid, values=(str(candidate), "…", "…", "Чтение файла…"))
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
        self.status_var.set(f"Файлов в списке: {count}." if count else "Добавьте аудио- или видеофайлы.")

    def _set_item(self, iid: str, status: str, tag: str = "") -> None:
        if iid in self.items and self.tree.exists(iid):
            self.tree.set(iid, "status", status)
            self.tree.item(iid, tags=(tag,) if tag else ())

    def _track_text(self, item: FileItem) -> str:
        if not item.probed:
            return "…"
        if not item.tracks:
            return "нет звука"
        if item.choice == "auto":
            return "Авто"
        for index, label in item.tracks:
            if index == item.choice:
                return label
        return "Авто"

    # ------------------------------------------------------------------ выбор дорожки
    def _selected_item(self) -> FileItem | None:
        selection = self.tree.selection()
        if len(selection) == 1:
            return self.items.get(selection[0])
        return None

    def _on_selection_changed(self) -> None:
        item = self._selected_item()
        if item is None or not item.probed or len(item.tracks) < 1:
            self.track_box.configure(values=(AUTO_TRACK_LABEL,), state="disabled")
            self.track_var.set(AUTO_TRACK_LABEL)
            self.track_values = []
            return
        self.track_values = [("auto", AUTO_TRACK_LABEL)] + [(index, label) for index, label in item.tracks]
        self.track_box.configure(values=[label for _, label in self.track_values],
                                 state="readonly" if not self.busy else "disabled")
        current = next((label for value, label in self.track_values if value == item.choice), AUTO_TRACK_LABEL)
        self.track_var.set(current)

    def _on_track_chosen(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        label = self.track_var.get()
        item.choice = next((value for value, text in self.track_values if text == label), "auto")
        self.tree.set(item.iid, "track", self._track_text(item))

    # ------------------------------------------------------------------ параметры
    def _on_split_toggle(self) -> None:
        state = "normal" if self.split_var.get() and not self.busy else "disabled"
        for spin in (self.max_chars_spin, self.max_lines_spin, self.max_duration_spin):
            spin.configure(state=state)

    def _choose_output(self) -> None:
        chosen = filedialog.askdirectory(title="Папка для готовых субтитров")
        if chosen:
            self.output_dir_var.set(chosen)

    def _choose_model_dir(self) -> None:
        chosen = filedialog.askdirectory(title="Папка для моделей Whisper")
        if chosen:
            self.model_dir_var.set(chosen)

    def _model_dir(self) -> Path | None:
        text = self.model_dir_var.get().strip()
        return Path(text).expanduser() if text else None

    def _refresh_model_status(self) -> None:
        name = self.model_var.get()
        model_dir = self._model_dir()
        self.model_status_var.set("Проверяю наличие модели…")

        def check() -> None:
            cached = core.find_cached_model(name, model_dir)
            self.messages.put(("modelstate", name, str(model_dir) if model_dir else "", cached is not None))

        threading.Thread(target=check, daemon=True).start()

    def _collect_settings(self) -> dict:
        data = dict(self.settings)
        data.update({
            "model": self.model_var.get(),
            "language": LANGUAGES.get(self.language_var.get(), "auto"),
            "mode": MODES.get(self.mode_var.get(), "transcribe"),
            "device": DEVICES.get(self.device_var.get(), "auto"),
            "model_dir": self.model_dir_var.get().strip(),
            "output_dir": self.output_dir_var.get().strip(),
            "overwrite": bool(self.overwrite_var.get()),
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
                       self.model_dir_button, self.download_button, self.overwrite_check, self.split_check):
            widget.configure(state=state)
        for widget in (self.model_box, self.language_box, self.mode_box, self.device_box):
            widget.configure(state=readonly)
        for check in self.format_checks:
            check.configure(state=state)
        self._on_split_toggle()
        self._on_selection_changed()

    def _reset_progress(self) -> None:
        self.file_bar.stop()
        self.file_bar.configure(mode="determinate", value=0.0)
        self.total_bar.configure(value=0.0)
        self.file_percent_var.set("0%")
        self.total_percent_var.set("0%")

    # ------------------------------------------------------------------ запуск
    def _validate_run_options(self) -> dict | None:
        if not self.items:
            messagebox.showwarning(APP_TITLE, "Сначала добавьте хотя бы один аудио- или видеофайл.")
            return None
        missing = [i.path for i in self.items.values() if not i.path.is_file()]
        if missing:
            messagebox.showerror(APP_TITLE, "Не удалось найти файл:\n" + "\n".join(map(str, missing[:5])))
            return None

        formats = [fmt for fmt, var in self.format_vars.items() if var.get()]
        if not formats:
            messagebox.showwarning(APP_TITLE, "Выберите хотя бы один формат субтитров.")
            return None

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
                messagebox.showerror(
                    APP_TITLE,
                    "Проверьте параметры разбиения: символов в строке от 10 до 80, строк от 1 до 3, "
                    "длительность реплики от 1 до 30 секунд.")
                return None

        output_text = self.output_dir_var.get().strip()
        output_dir = Path(output_text).expanduser().resolve() if output_text else None
        if output_dir is not None:
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(APP_TITLE, f"Не удалось создать папку для результатов:\n{exc}")
                return None

        model_dir = self._model_dir()
        if model_dir is not None:
            try:
                model_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(APP_TITLE, f"Не удалось создать папку для моделей:\n{exc}")
                return None

        return {
            "files": [(self.items[iid].iid, self.items[iid].path, self.items[iid].choice,
                       self.items[iid].duration) for iid in self.item_order],
            "model_name": self.model_var.get().strip(),
            "language": LANGUAGES.get(self.language_var.get(), "auto"),
            "task": MODES.get(self.mode_var.get(), "transcribe"),
            "device_choice": DEVICES.get(self.device_var.get(), "auto"),
            "output_dir": output_dir,
            "model_dir": model_dir,
            "overwrite": bool(self.overwrite_var.get()),
            "formats": formats,
            "max_line_chars": max_chars,
            "max_lines": max_lines or 2,
            "max_duration": max_duration,
        }

    def _begin_work(self, target, options: dict, status: str) -> None:
        self.stop_after_current.clear()
        self.busy = True
        self._set_controls_enabled(False)
        self.stop_button.configure(state="normal")
        self.status_var.set(status)
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
            self._set_item(iid, "В очереди")
        self._begin_work(self._worker_main, options, "Подготовка…")

    def _download_model(self) -> None:
        if self.busy:
            return
        options = {"model_name": self.model_var.get().strip(), "model_dir": self._model_dir()}
        if options["model_dir"] is not None:
            try:
                options["model_dir"].mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(APP_TITLE, f"Не удалось создать папку для моделей:\n{exc}")
                return
        self._begin_work(self._download_main, options, f"Скачивание модели {options['model_name']}…")
        self.stop_button.configure(state="disabled")

    def _download_main(self, options: dict) -> None:
        name = options["model_name"]
        try:
            core.download_model(name, options["model_dir"], lambda done, total: self.messages.put(("download", name, done, total)))
            self.messages.put(("status", f"Модель {name} скачана."))
        except Exception as exc:
            self.messages.put(("log", f"ОШИБКА загрузки модели: {exc}"))
            self.messages.put(("log", traceback.format_exc()))
            self.messages.put(("status", "Не удалось скачать модель. Проверьте интернет и см. журнал."))
        finally:
            self.messages.put(("finished", None))

    def _worker_main(self, options: dict) -> None:
        files = options["files"]
        model_name = options["model_name"]
        successes = 0
        skipped = 0
        failures: list[tuple[Path, str]] = []
        try:
            self.messages.put(("status", f"Проверяю модель {model_name}…"))
            core.download_model(model_name, options["model_dir"],
                                lambda done, total: self.messages.put(("download", model_name, done, total)))

            device = core.resolve_device(options["device_choice"])
            compute_type = core.get_compute_type(device)
            self.messages.put(("status", f"Загрузка модели {model_name} в память…"))
            self.messages.put(("log", f"Устройство: {device}, compute_type: {compute_type}."))
            model = core.create_model(model_name, device, compute_type, options["model_dir"])
            self.messages.put(("log", f"Модель '{model_name}' готова к работе."))
            self.messages.put(("modeldone", model_name))

            weights = [max(duration, 0.0) for _, _, _, duration in files]
            if not all(w > 0 for w in weights):
                weights = [1.0] * len(files)
            total_weight = sum(weights) or 1.0
            finished_weight = 0.0

            total_files = len(files)
            for number, (iid, source, choice, _duration) in enumerate(files, start=1):
                weight = weights[number - 1]
                if self.stop_after_current.is_set():
                    self.messages.put(("item", iid, "Не обработан", "skip"))
                    continue

                outputs = core.output_paths_for(source, options["output_dir"], None, options["formats"])
                self.messages.put(("fileprogress", 0.0, ""))
                self.messages.put(("status", f"Обработка {number}/{total_files}: {source.name}"))
                self.messages.put(("log", f"[{number}/{total_files}] {source}"))

                if not options["overwrite"] and all(p.exists() for p in outputs.values()):
                    self.messages.put(("log", "Пропуск: все файлы результатов уже существуют."))
                    self.messages.put(("item", iid, "Пропущен (уже есть)", "skip"))
                    skipped += 1
                    finished_weight += weight
                    self.messages.put(("total", finished_weight / total_weight * 100.0))
                    continue

                args = SimpleNamespace(
                    audio_stream=choice, temp_dir=None, language=options["language"], task=options["task"],
                    beam_size=5, vad_filter=True, quiet_progress=True, device=options["device_choice"],
                    model_dir=options["model_dir"], max_line_chars=options["max_line_chars"],
                    max_lines=options["max_lines"], max_duration=options["max_duration"],
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
                        eta = f"осталось ~{format_eta((now - started) * (100.0 - percent) / percent)}"
                    self.messages.put(("item", iid, f"Распознавание {percent:.0f}%", "work"))
                    self.messages.put(("fileprogress", percent, eta))
                    self.messages.put(("total", (base + weight * percent / 100.0) / total_weight * 100.0))

                self.messages.put(("item", iid, "Распознавание 0%", "work"))
                try:
                    model, device = core.transcribe_one(source, outputs, model, model_name, device, args,
                                                        progress_callback=on_progress)
                    successes += 1
                    self.messages.put(("item", iid, "Готово", "done"))
                    self.messages.put(("fileprogress", 100.0, ""))
                except Exception as exc:
                    failures.append((source, str(exc)))
                    self.messages.put(("item", iid, "Ошибка", "error"))
                    self.messages.put(("log", f"ОШИБКА: {source.name}: {exc}"))
                    self.messages.put(("log", traceback.format_exc()))
                finished_weight += weight
                self.messages.put(("total", finished_weight / total_weight * 100.0))

            self.messages.put(("log", "=" * 56))
            self.messages.put(("log", f"Готово. Успешно: {successes}; пропущено: {skipped}; ошибок: {len(failures)}."))
            if failures:
                self.messages.put(("log", "Файлы с ошибками:"))
                for source, error in failures:
                    self.messages.put(("log", f"  {source.name}: {error}"))
            if self.stop_after_current.is_set():
                self.messages.put(("status", "Остановлено пользователем."))
            elif failures:
                self.messages.put(("status", f"Завершено с ошибками ({len(failures)}). См. журнал."))
            else:
                self.messages.put(("status", f"Готово: создано {successes}, пропущено {skipped}."))
        except Exception as exc:
            self.messages.put(("log", f"КРИТИЧЕСКАЯ ОШИБКА: {exc}"))
            self.messages.put(("log", traceback.format_exc()))
            self.messages.put(("status", "Ошибка при выполнении. См. журнал."))
        finally:
            self.messages.put(("finished", None))

    def _request_stop(self) -> None:
        if self.busy:
            self.stop_after_current.set()
            self.stop_button.configure(state="disabled")
            self.status_var.set("Остановка после текущего файла…")
            self._log("Запрошена остановка. Текущий файл будет завершён.")

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
            messagebox.showinfo(APP_TITLE, "Папка пока не определена: добавьте файлы или выберите папку для результатов.")
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Не удалось открыть папку:\n{exc}")

    # ------------------------------------------------------------------ очередь сообщений
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
            self.status_var.set(str(message[1]))
        elif kind == "item":
            _, iid, text, tag = message
            self._set_item(iid, text, tag)
        elif kind == "probed":
            _, iid, duration, tracks, error = message
            item = self.items.get(iid)
            if item is None or not self.tree.exists(iid):
                return
            item.probed = True
            item.duration = duration
            item.tracks = tracks
            self.tree.set(iid, "duration", format_duration(duration))
            self.tree.set(iid, "track", self._track_text(item))
            if error:
                self._set_item(iid, "Не читается", "error")
                self._log(f"Не удалось прочитать {item.path.name}: {error}")
            elif not tracks:
                self._set_item(iid, "Нет звука", "error")
            else:
                self._set_item(iid, "Готов к работе")
            if self._selected_item() is item:
                self._on_selection_changed()
        elif kind == "fileprogress":
            _, percent, eta = message
            if str(self.file_bar.cget("mode")) != "determinate":
                self.file_bar.stop()
                self.file_bar.configure(mode="determinate")
            self.file_bar.configure(value=percent)
            self.file_percent_var.set(f"{percent:.0f}%")
            if eta and self.busy:
                current = self.status_var.get().split(" · ")[0]
                self.status_var.set(f"{current} · {eta}")
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
                self.status_var.set(f"Скачивание модели {name}: {done / 1048576:.0f} из {total / 1048576:.0f} МБ")
            else:
                self.status_var.set(f"Скачивание модели {name}: {done / 1048576:.0f} МБ")
        elif kind == "modelstate":
            _, name, model_dir, cached = message
            current_dir = str(self._model_dir()) if self._model_dir() else ""
            if name == self.model_var.get() and model_dir == current_dir:
                self.model_status_var.set("Скачана, интернет не нужен." if cached
                                          else "Не скачана: загрузится при запуске.")
        elif kind == "modeldone":
            if message[1] == self.model_var.get():
                self.model_status_var.set("Скачана, интернет не нужен.")
        elif kind == "finished":
            self.busy = False
            self.worker = None
            self._set_controls_enabled(True)
            self.stop_button.configure(state="disabled")
            self.file_bar.configure(mode="determinate")
            self._refresh_model_status()

    def _on_close(self) -> None:
        if self.busy:
            close_now = messagebox.askyesno(
                APP_TITLE,
                "Распознавание ещё выполняется. Прервать обработку и выйти?",
            )
            if not close_now:
                return
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
    """Проверка собранного приложения без участия пользователя. Результат пишется в журнал во временной папке."""
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
                raise RuntimeError(f"{tool} не найден в PATH")
            result = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                raise RuntimeError(f"{tool} вернул код {result.returncode}")
            found.append(path)
        return ", ".join(found)

    def check_vad_asset():
        import faster_whisper
        assets = list((Path(faster_whisper.__file__).parent / "assets").glob("*.onnx"))
        if not assets:
            raise RuntimeError("нет файла VAD (assets/*.onnx)")
        return assets[0].name

    def check_ui():
        os.environ["WHISPERSRT_SETTINGS"] = str(Path(tempfile.gettempdir()) / "whispersrt_selftest_settings.json")
        root, dnd = create_root()
        try:
            root.withdraw()
            app = WhisperSRTApp(root, dnd=dnd, configure_logging=False)
            root.update()
            app._apply_theme("light")
            app._apply_theme("dark")
            root.update()
            save_settings(app._collect_settings())
            if load_settings()["model"] != app.model_var.get():
                raise RuntimeError("настройки не сохраняются")
            return f"тема={'sv_ttk' if sv_ttk else 'стандартная'}, перетаскивание={'да' if app.dnd else 'нет'}"
        finally:
            root.destroy()

    for module in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "huggingface_hub", "ffmpeg"):
        check(f"импорт {module}", check_import(module))
    check("FFmpeg", check_ffmpeg)
    check("файл VAD", check_vad_asset)
    check("окно программы", check_ui)

    lines.append("ИТОГ: " + ("всё в порядке" if ok else "есть ошибки"))
    try:
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
    if sys.stdout is not None:
        print("\n".join(lines))
    return 0 if ok else 1


def main() -> None:
    root, dnd = create_root()
    WhisperSRTApp(root, dnd=dnd)
    root.mainloop()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(run_selftest())
    main()
