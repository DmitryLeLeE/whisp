# -*- coding: utf-8 -*-
"""A simple Windows GUI for creating SRT subtitles with faster-whisper."""
from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
import traceback
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


class WhisperSRTApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("920x760")
        self.root.minsize(760, 620)

        self.messages: queue.Queue = queue.Queue()
        self.selected_files: list[Path] = []
        self.worker: threading.Thread | None = None
        self.stop_after_current = threading.Event()
        self.busy = False

        self.model_var = tk.StringVar(value="small")
        self.language_var = tk.StringVar(value="Русский")
        self.stream_var = tk.StringVar(value="auto")
        self.device_var = tk.StringVar(value="Автоматически")
        self.output_dir_var = tk.StringVar(value="")
        self.overwrite_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Выберите один или несколько аудио-/видеофайлов.")
        self.progress_percent_var = tk.StringVar(value="0%")

        self._build_ui()
        self._configure_logging()
        self.root.after(100, self._poll_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Whisper SRT", font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Создание субтитров SRT из медиафайлов через faster-whisper. Первая загрузка модели сохраняется в кэш.",
            wraplength=880,
        ).pack(anchor="w", pady=(2, 12))

        files_frame = ttk.LabelFrame(outer, text="1. Исходные файлы", padding=10)
        files_frame.pack(fill="x", pady=(0, 10))
        file_buttons = ttk.Frame(files_frame)
        file_buttons.pack(fill="x")
        self.choose_button = ttk.Button(file_buttons, text="Выбрать файл(ы)…", command=self._choose_files)
        self.choose_button.pack(side="left")
        self.clear_button = ttk.Button(file_buttons, text="Очистить список", command=self._clear_files)
        self.clear_button.pack(side="left", padx=(8, 0))
        self.files_label = ttk.Label(files_frame, text="Файлы не выбраны", wraplength=850)
        self.files_label.pack(anchor="w", pady=(8, 0))

        settings_frame = ttk.LabelFrame(outer, text="2. Параметры распознавания", padding=10)
        settings_frame.pack(fill="x", pady=(0, 10))
        settings_frame.columnconfigure(1, weight=1)
        settings_frame.columnconfigure(3, weight=1)

        ttk.Label(settings_frame, text="Модель:").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=5)
        self.model_box = ttk.Combobox(
            settings_frame,
            textvariable=self.model_var,
            values=("tiny", "base", "small", "medium", "large-v3", "turbo"),
            state="readonly",
            width=15,
        )
        self.model_box.grid(row=0, column=1, sticky="ew", padx=(0, 18), pady=5)

        ttk.Label(settings_frame, text="Язык:").grid(row=0, column=2, sticky="w", padx=(0, 6), pady=5)
        self.language_box = ttk.Combobox(
            settings_frame,
            textvariable=self.language_var,
            values=tuple(LANGUAGES.keys()),
            state="readonly",
            width=20,
        )
        self.language_box.grid(row=0, column=3, sticky="ew", pady=5)

        ttk.Label(settings_frame, text="Аудиопоток:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=5)
        self.stream_entry = ttk.Entry(settings_frame, textvariable=self.stream_var, width=18)
        self.stream_entry.grid(row=1, column=1, sticky="ew", padx=(0, 18), pady=5)
        ttk.Label(settings_frame, text="auto или индекс потока (например, 1)").grid(
            row=1, column=2, columnspan=2, sticky="w", pady=5
        )

        ttk.Label(settings_frame, text="Устройство:").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=5)
        self.device_box = ttk.Combobox(
            settings_frame,
            textvariable=self.device_var,
            values=("Автоматически", "CPU"),
            state="readonly",
            width=18,
        )
        self.device_box.grid(row=2, column=1, sticky="ew", padx=(0, 18), pady=5)
        ttk.Label(settings_frame, text="Авто выбирает CUDA при наличии видеокарты NVIDIA.").grid(
            row=2, column=2, columnspan=2, sticky="w", pady=5
        )

        output_frame = ttk.LabelFrame(outer, text="3. Сохранение результатов", padding=10)
        output_frame.pack(fill="x", pady=(0, 10))
        output_row = ttk.Frame(output_frame)
        output_row.pack(fill="x")
        self.output_entry = ttk.Entry(output_row, textvariable=self.output_dir_var)
        self.output_entry.pack(side="left", fill="x", expand=True)
        self.output_button = ttk.Button(output_row, text="Выбрать папку…", command=self._choose_output)
        self.output_button.pack(side="left", padx=(8, 0))
        ttk.Label(
            output_frame,
            text="Если папка не указана, субтитры сохраняются рядом с исходными файлами.",
            wraplength=850,
        ).pack(anchor="w", pady=(5, 0))
        self.overwrite_check = ttk.Checkbutton(
            output_frame,
            text="Перезаписывать существующие SRT",
            variable=self.overwrite_var,
        )
        self.overwrite_check.pack(anchor="w", pady=(5, 0))

        action_row = ttk.Frame(outer)
        action_row.pack(fill="x", pady=(0, 8))
        self.start_button = ttk.Button(action_row, text="Создать субтитры", command=self._start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(
            action_row,
            text="Остановить после текущего файла",
            command=self._request_stop,
            state="disabled",
        )
        self.stop_button.pack(side="left", padx=(8, 0))
        ttk.Label(action_row, textvariable=self.status_var).pack(side="left", padx=(12, 0), fill="x", expand=True)

        progress_row = ttk.Frame(outer)
        progress_row.pack(fill="x", pady=(0, 10))
        ttk.Label(progress_row, text="Прогресс:").pack(side="left", padx=(0, 6))
        self.progress_bar = ttk.Progressbar(
            progress_row, orient="horizontal", mode="determinate", maximum=100.0
        )
        self.progress_bar.pack(side="left", fill="x", expand=True)
        ttk.Label(
            progress_row, textvariable=self.progress_percent_var, width=6, anchor="e"
        ).pack(side="left", padx=(6, 0))

        log_frame = ttk.LabelFrame(outer, text="Журнал работы", padding=6)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, height=12, wrap="word", state="disabled", font=("Consolas", 9))
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

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

    def _choose_files(self) -> None:
        chosen = filedialog.askopenfilenames(
            title="Выберите медиафайлы",
            filetypes=[
                ("Поддерживаемые медиафайлы", "*.ts *.mkv *.mp4 *.avi *.mov *.m2ts *.mts *.webm *.mpg *.mpeg *.wmv *.mp3 *.wav *.flac *.m4a *.aac *.ogg *.opus *.wma *.aiff *.alac *.amr *.3gp *.3g2 *.asf *.flv *.m4v *.ogv *.vob *.m4b"),
                ("Все файлы", "*.*"),
            ],
        )
        if chosen:
            self.selected_files = [Path(item) for item in chosen]
            self._refresh_file_label()

    def _clear_files(self) -> None:
        if self.busy:
            return
        self.selected_files.clear()
        self._refresh_file_label()

    def _refresh_file_label(self) -> None:
        if not self.selected_files:
            self.files_label.configure(text="Файлы не выбраны")
            return
        names = [str(path) for path in self.selected_files[:4]]
        if len(self.selected_files) > 4:
            names.append(f"… и ещё {len(self.selected_files) - 4}")
        self.files_label.configure(text=f"Выбрано файлов: {len(self.selected_files)}\n" + "\n".join(names))

    def _choose_output(self) -> None:
        chosen = filedialog.askdirectory(title="Папка для готовых SRT")
        if chosen:
            self.output_dir_var.set(chosen)

    def _reset_progress(self) -> None:
        self.progress_bar.configure(value=0.0)
        self.progress_percent_var.set("0%")

    def _start(self) -> None:
        if self.busy:
            return
        if not self.selected_files:
            messagebox.showwarning(APP_TITLE, "Сначала выберите хотя бы один аудио- или видеофайл.")
            return

        missing = [p for p in self.selected_files if not p.is_file()]
        if missing:
            messagebox.showerror(APP_TITLE, "Не удалось найти файл:\n" + "\n".join(map(str, missing[:5])))
            return

        stream_text = self.stream_var.get().strip().lower()
        if stream_text == "auto":
            audio_stream: str | int = "auto"
        else:
            try:
                audio_stream = int(stream_text)
                if audio_stream < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror(APP_TITLE, "Аудиопоток должен быть auto или целым индексом FFmpeg.")
                return

        output_text = self.output_dir_var.get().strip()
        output_dir = Path(output_text).expanduser().resolve() if output_text else None
        if output_dir is not None:
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(APP_TITLE, f"Не удалось создать папку для результатов:\n{exc}")
                return

        self.stop_after_current.clear()
        self.busy = True
        self._set_controls_enabled(False)
        self.stop_button.configure(state="normal")
        self.status_var.set("Подготовка…")
        self._reset_progress()

        options = {
            "files": list(self.selected_files),
            "model_name": self.model_var.get().strip(),
            "language": LANGUAGES.get(self.language_var.get(), "auto"),
            "audio_stream": audio_stream,
            "device_choice": "cpu" if self.device_var.get() == "CPU" else "auto",
            "output_dir": output_dir,
            "overwrite": self.overwrite_var.get(),
        }
        self.worker = threading.Thread(target=self._worker_main, kwargs=options, daemon=True)
        self.worker.start()

    def _worker_main(
        self,
        files: list[Path],
        model_name: str,
        language: str,
        audio_stream: str | int,
        device_choice: str,
        output_dir: Path | None,
        overwrite: bool,
    ) -> None:
        successes = 0
        skipped = 0
        failures: list[tuple[Path, str]] = []
        model = None
        device = "cpu"
        try:
            import whisper_universal as core
            from faster_whisper import WhisperModel

            self.messages.put(("status", f"Загрузка модели {model_name}…"))
            device = core.resolve_device(device_choice)
            compute_type = core.get_compute_type(device)
            # Ограничиваем потоки до 8 для предотвращения деградации OpenMP
            cpu_threads = min(8, os.cpu_count() or 4)

            self.messages.put(("log", f"Устройство: {device}, compute_type: {compute_type}, потоков CPU: {cpu_threads}."))
            self.messages.put(("log", f"Загружаю модель '{model_name}'…"))
            model = WhisperModel(model_name, device=device, compute_type=compute_type, cpu_threads=cpu_threads)
            self.messages.put(("log", f"Модель '{model_name}' готова к работе."))

            args = SimpleNamespace(
                audio_stream=audio_stream,
                temp_dir=None,
                language=language,
                task="transcribe",
                beam_size=5,
                vad_filter=True,
                quiet_progress=True,
                device=device_choice,
            )

            _last_update_time = [0.0]
            _last_percent = [-1.0]

            def _on_progress(current: float, total: float) -> None:
                now = time.monotonic()
                percent = (current / total) * 100.0 if total > 0 else 0.0
                percent = max(0.0, min(100.0, percent))
                if now - _last_update_time[0] < 0.25 and abs(percent - _last_percent[0]) < 0.5:
                    return
                _last_update_time[0] = now
                _last_percent[0] = percent
                self.messages.put(("progress", percent))

            total_files = len(files)
            for number, source in enumerate(files, start=1):
                if self.stop_after_current.is_set():
                    break

                if output_dir is None:
                    destination = source.with_name(f"{source.stem}.whisper.srt")
                else:
                    destination = output_dir / f"{source.stem}.whisper.srt"

                _last_percent[0] = -1.0
                _last_update_time[0] = 0.0
                self.messages.put(("progress", 0.0))
                self.messages.put(("status", f"Обработка {number}/{total_files}: {source.name}"))
                self.messages.put(("log", f"[{number}/{total_files}] {source}"))

                if destination.exists() and not overwrite:
                    self.messages.put(("log", f"Пропуск: файл уже существует: {destination}"))
                    skipped += 1
                    continue

                try:
                    model, device = core.transcribe_one(
                        source, destination, model, model_name, device, args,
                        progress_callback=_on_progress,
                    )
                    successes += 1
                    self.messages.put(("progress", 100.0))
                except Exception as exc:
                    failures.append((source, str(exc)))
                    self.messages.put(("log", f"ОШИБКА: {source.name}: {exc}"))
                    self.messages.put(("log", traceback.format_exc()))

            self.messages.put(("log", "=" * 56))
            self.messages.put(("log", f"Готово. Успешно: {successes}; пропущено: {skipped}; ошибок: {len(failures)}."))
            if failures:
                self.messages.put(("log", "Файлы с ошибками:"))
                for source, error in failures:
                    self.messages.put(("log", f"  {source.name}: {error}"))
            if self.stop_after_current.is_set():
                self.messages.put(("status", "Остановлено пользователем."))
            elif failures:
                self.messages.put(("status", "Завершено с ошибками. См. журнал."))
            else:
                self.messages.put(("status", "Готово."))
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
            self.messages.put(("log", "Запрошена остановка. Текущий файл будет завершён."))

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.choose_button.configure(state=state)
        self.clear_button.configure(state=state)
        self.start_button.configure(state=state)
        self.output_button.configure(state=state)
        self.output_entry.configure(state=state)
        self.stream_entry.configure(state=state)
        self.language_box.configure(state="readonly" if enabled else "disabled")
        self.model_box.configure(state="readonly" if enabled else "disabled")
        self.device_box.configure(state="readonly" if enabled else "disabled")
        self.overwrite_check.configure(state=state)

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == "log":
                    self.log_text.configure(state="normal")
                    self.log_text.insert("end", str(value) + "\n")
                    self.log_text.see("end")
                    self.log_text.configure(state="disabled")
                elif kind == "status":
                    self.status_var.set(str(value))
                elif kind == "progress":
                    percent = float(value)
                    self.progress_bar.configure(value=percent)
                    self.progress_percent_var.set(f"{percent:.0f}%")
                elif kind == "finished":
                    self.busy = False
                    self.worker = None
                    self._set_controls_enabled(True)
                    self.stop_button.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _on_close(self) -> None:
        if self.busy:
            close_now = messagebox.askyesno(
                APP_TITLE,
                "Распознавание ещё выполняется. Прервать обработку и выйти?",
            )
            if not close_now:
                return
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = WhisperSRTApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()