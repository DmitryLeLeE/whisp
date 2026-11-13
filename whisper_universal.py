#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Universal batch transcription to subtitles using faster-whisper and FFmpeg."""
from __future__ import annotations

import argparse
import fnmatch
import json
import logging
import os
import sys
import tempfile
import textwrap
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import ffmpeg

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

__version__ = "1.1.0"

LOG = logging.getLogger("whisper_universal")

SUPPORTED_EXTENSIONS = {
    ".3g2", ".3gp", ".asf", ".avi", ".flv", ".m2ts", ".m4v", ".mkv",
    ".mov", ".mp4", ".mpeg", ".mpg", ".mts", ".ogv", ".ts", ".vob",
    ".webm", ".wmv",
    ".aac", ".aiff", ".alac", ".amr", ".flac", ".m4a", ".m4b", ".mp3",
    ".ogg", ".opus", ".wav", ".wma",
}

MODEL_CHOICES = ("tiny", "base", "small", "medium", "large-v3", "turbo")
OUTPUT_FORMATS = ("srt", "vtt", "txt", "json", "ass")

# Запасная таблица на случай, если в faster-whisper изменится внутренний словарь моделей.
FALLBACK_MODEL_REPOS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}
MODEL_ALLOW_PATTERNS = [
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
]

SENTENCE_END = (".", "!", "?", "…", "。", "！", "？")
CUDA_ERROR_MARKERS = ("cublas", "cudnn", "cufft", "curand", "nvrtc", "cuda")


# --------------------------------------------------------------------------------------
# Аргументы командной строки
# --------------------------------------------------------------------------------------
def parse_formats(value: str | list[str] | tuple[str, ...]) -> list[str]:
    items = value.split(",") if isinstance(value, str) else list(value)
    result: list[str] = []
    for item in items:
        fmt = item.strip().lower().lstrip(".")
        if not fmt:
            continue
        if fmt not in OUTPUT_FORMATS:
            raise ValueError(f"Неизвестный формат '{fmt}'. Доступны: {', '.join(OUTPUT_FORMATS)}.")
        if fmt not in result:
            result.append(fmt)
    if not result:
        raise ValueError("Не выбран ни один формат вывода.")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Распознаёт речь в аудио/видео и сохраняет субтитры (SRT, VTT, TXT, JSON, ASS)."
    )
    parser.add_argument("input", type=Path, nargs="?", help="Путь к медиафайлу или папке с файлами.")
    parser.add_argument("-o", "--output-dir", type=Path, default=None,
                        help="Папка для результатов. Если не указана, файлы сохраняются рядом с исходниками.")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="Искать медиафайлы в подпапках (для входной папки).")
    parser.add_argument("-m", "--model", choices=MODEL_CHOICES, default="small",
                        help="Модель Whisper (по умолчанию: small).")
    parser.add_argument("--model-dir", type=Path, default=None,
                        help="Папка, куда скачиваются модели и где они ищутся. По умолчанию кэш Hugging Face.")
    parser.add_argument("-l", "--language", default="auto",
                        help="Язык речи: ru, en, de и т. п.; auto включает автоопределение.")
    parser.add_argument("--task", choices=("transcribe", "translate"), default="transcribe",
                        help="transcribe = текст на исходном языке; translate = перевод на английский.")
    parser.add_argument("-f", "--formats", default="srt",
                        help="Форматы вывода через запятую: srt, vtt, txt, json, ass (по умолчанию: srt).")
    parser.add_argument("--max-line-chars", type=int, default=0,
                        help="Максимум символов в строке субтитров. 0 = не разбивать (как выдаёт модель).")
    parser.add_argument("--max-lines", type=int, default=2,
                        help="Максимум строк в одной реплике при разбиении (по умолчанию 2).")
    parser.add_argument("--max-duration", type=float, default=0.0,
                        help="Максимальная длительность реплики в секундах. 0 = без ограничения.")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto",
                        help="Вычислительное устройство. auto использует CUDA, если она доступна.")
    parser.add_argument("--audio-stream", default="auto",
                        help="Глобальный индекс аудиопотока FFmpeg (например, 2) или auto.")
    parser.add_argument("--temp-dir", type=Path, default=None,
                        help="Папка для временных WAV-файлов.")
    parser.add_argument("--overwrite", action="store_true",
                        help="Перезаписывать уже существующие файлы результатов.")
    parser.add_argument("--beam-size", type=int, default=5,
                        help="Ширина beam search (по умолчанию 5). Для turbo автоматически используется 1.")
    parser.add_argument("--vad-filter", action="store_true", default=True,
                        help="Включить VAD-фильтр (пропуск тишины). Включён по умолчанию.")
    parser.add_argument("--no-vad", action="store_false", dest="vad_filter",
                        help="Отключить VAD-фильтр.")
    parser.add_argument("--quiet-progress", action="store_true",
                        help="Не выводить подробный прогресс.")
    parser.add_argument("--list-streams", action="store_true",
                        help="Показать потоки одного медиафайла и завершить работу.")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"),
                        default="INFO", help="Уровень сообщений журнала.")
    parser.add_argument("--version", action="version", version=f"WhisperSRT {__version__}")
    args = parser.parse_args()

    if args.input is None:
        parser.error("не указан входной файл или папка.")

    try:
        args.formats = parse_formats(args.formats)
    except ValueError as exc:
        parser.error(str(exc))
    if args.max_line_chars < 0 or args.max_lines < 1 or args.max_duration < 0:
        parser.error("--max-line-chars и --max-duration не могут быть отрицательными, --max-lines должен быть не меньше 1.")

    if args.audio_stream != "auto":
        try:
            args.audio_stream = int(args.audio_stream)
            if args.audio_stream < 0:
                parser.error("--audio-stream должен быть 'auto' или неотрицательным индексом.")
        except ValueError:
            parser.error("--audio-stream должен быть 'auto' или целым индексом, например 2.")

    args.input = args.input.expanduser().resolve()
    if args.output_dir is not None:
        args.output_dir = args.output_dir.expanduser().resolve()
    if args.temp_dir is not None:
        args.temp_dir = args.temp_dir.expanduser().resolve()
    if args.model_dir is not None:
        args.model_dir = args.model_dir.expanduser().resolve()
    return args


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


# --------------------------------------------------------------------------------------
# FFmpeg: потоки и извлечение звука
# --------------------------------------------------------------------------------------
def probe_media(path: Path) -> dict[str, Any]:
    try:
        return ffmpeg.probe(str(path))
    except ffmpeg.Error as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
        raise RuntimeError(f"FFmpeg не смог прочитать файл: {stderr.strip()}") from exc


def get_audio_streams(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    probe = probe_media(path)
    streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
    return probe, streams


def describe_audio_stream(stream: dict[str, Any]) -> str:
    tags = stream.get("tags") or {}
    disposition = stream.get("disposition") or {}
    parts = [f"#{stream.get('index', '?')}"]
    language = tags.get("language")
    if language and language != "und":
        parts.append(str(language))
    title = tags.get("title")
    if title:
        parts.append(str(title))
    parts.append(str(stream.get("codec_name", "?")))
    channels = stream.get("channels")
    if channels:
        parts.append(f"{channels} кан.")
    label = " · ".join(parts)
    if disposition.get("default") == 1:
        label += " (по умолчанию)"
    return label


def probe_audio_info(path: Path) -> tuple[float, list[tuple[int, str]]]:
    """Возвращает длительность файла в секундах и список (индекс потока, подпись) его аудиодорожек."""
    probe, streams = get_audio_streams(path)
    try:
        duration = float((probe.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    return duration, [(int(s["index"]), describe_audio_stream(s)) for s in streams]


def print_streams(path: Path) -> bool:
    try:
        _, audio_streams = get_audio_streams(path)
    except Exception as exc:
        LOG.error("%s", exc)
        return False

    LOG.info("Файл: %s", path)
    if not audio_streams:
        LOG.warning("Аудиопотоки не найдены.")
        return False

    for position, stream in enumerate(audio_streams, start=1):
        index = stream.get("index", "?")
        tags = stream.get("tags") or {}
        disposition = stream.get("disposition") or {}
        language = tags.get("language", "не указан")
        title = tags.get("title", "")
        codec = stream.get("codec_name", "неизвестно")
        channels = stream.get("channels", "?")
        sample_rate = stream.get("sample_rate", "?")
        default = " [DEFAULT]" if disposition.get("default") == 1 else ""
        title_text = f", название: {title}" if title else ""
        LOG.info("Аудиодорожка %d: индекс FFmpeg=%s, язык=%s, кодек=%s, каналов=%s, Hz=%s%s%s",
                 position, index, language, codec, channels, sample_rate, title_text, default)
    return True


def choose_audio_stream(audio_streams: list[dict[str, Any]], requested: str | int) -> dict[str, Any]:
    if not audio_streams:
        raise RuntimeError("В файле не найдено ни одной аудиодорожки.")

    if requested != "auto":
        for stream in audio_streams:
            if stream.get("index") == requested:
                return stream
        available = ", ".join(str(s.get("index")) for s in audio_streams)
        raise RuntimeError(
            f"Аудиопоток с глобальным индексом {requested} не найден. "
            f"Доступные индексы аудиопотоков: {available}. Используйте --list-streams."
        )

    defaults = [s for s in audio_streams if (s.get("disposition") or {}).get("default") == 1]
    return defaults[0] if defaults else audio_streams[0]


def extract_audio_track(video_path: Path, output_audio_path: Path, stream_index: int) -> None:
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        (
            ffmpeg
            .input(str(video_path))
            .output(
                str(output_audio_path),
                **{
                    "map": f"0:{stream_index}",
                    "ac": 1,
                    "ar": 16000,
                    "acodec": "pcm_s16le",
                    "f": "wav",
                    "loglevel": "error",
                    "threads": "0",
                },
            )
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
        raise RuntimeError(f"Ошибка извлечения аудио через FFmpeg: {stderr.strip()}") from exc


# --------------------------------------------------------------------------------------
# Реплики субтитров и форматы вывода
# --------------------------------------------------------------------------------------
@dataclass
class Cue:
    start: float
    end: float
    text: str  # строки разделены символом \n


def _clean_text(text: str) -> str:
    lines = (line.strip() for line in str(text).replace("\r", "\n").split("\n"))
    return "\n".join(line for line in lines if line)


def _segment_words(segment: Any) -> list[tuple[float, float, str]]:
    """Слова сегмента с временем. Если модель не дала пословных меток, время делится пропорционально длине слов."""
    words = getattr(segment, "words", None)
    result: list[tuple[float, float, str]] = []
    if words:
        for word in words:
            text = str(word.word).strip()
            if text:
                result.append((float(word.start), float(word.end), text))
        if result:
            return result

    tokens = str(segment.text).split()
    if not tokens:
        return []
    total_chars = sum(len(t) for t in tokens) or 1
    start, end = float(segment.start), float(segment.end)
    span = max(0.0, end - start)
    position = start
    for token in tokens:
        duration = span * len(token) / total_chars
        result.append((position, position + duration, token))
        position += duration
    return result


def wrap_cue_text(text: str, line_width: int, max_lines: int) -> str:
    lines = textwrap.wrap(text, width=line_width, break_long_words=False, break_on_hyphens=False) or [text]
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [" ".join(lines[max_lines - 1:])]
    return "\n".join(lines)


def segments_to_cues(
    segments: list[Any],
    max_line_chars: int = 0,
    max_lines: int = 2,
    max_duration: float = 0.0,
) -> list[Cue]:
    """Превращает сегменты модели в реплики. Без ограничений реплика = сегмент модели."""
    if max_line_chars <= 0 and max_duration <= 0:
        cues = []
        for segment in segments:
            text = _clean_text(segment.text)
            if text:
                cues.append(Cue(float(segment.start), float(segment.end), text))
        return cues

    chars_limit = max_line_chars * max(1, max_lines) if max_line_chars > 0 else None
    cues = []
    for segment in segments:
        current: list[tuple[float, float, str]] = []
        current_len = 0

        def flush() -> None:
            nonlocal current, current_len
            if not current:
                return
            text = " ".join(word[2] for word in current)
            if max_line_chars > 0:
                text = wrap_cue_text(text, max_line_chars, max(1, max_lines))
            start = current[0][0]
            end = max(current[-1][1], start)
            cues.append(Cue(start, end, text))
            current, current_len = [], 0

        for word in _segment_words(segment):
            if current:
                too_long = chars_limit is not None and current_len + 1 + len(word[2]) > chars_limit
                too_slow = max_duration > 0 and (word[1] - current[0][0]) > max_duration
                if too_long or too_slow:
                    flush()
            current_len += (1 if current else 0) + len(word[2])
            current.append(word)
            if chars_limit is not None and word[2].endswith(SENTENCE_END) and current_len >= 0.4 * chars_limit:
                flush()
        flush()

    for first, second in zip(cues, cues[1:]):
        if first.end > second.start >= first.start:
            first.end = second.start
    return cues


def format_srt_time(seconds: float) -> str:
    total_ms = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"


def format_vtt_time(seconds: float) -> str:
    return format_srt_time(seconds).replace(",", ".")


def format_ass_time(seconds: float) -> str:
    total_cs = max(0, round(float(seconds) * 100))
    hours, remainder = divmod(total_cs, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    whole_seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{whole_seconds:02}.{centiseconds:02}"


def render_srt(cues: list[Cue], **_: Any) -> str:
    blocks = [
        f"{number}\n{format_srt_time(cue.start)} --> {format_srt_time(cue.end)}\n{cue.text}\n"
        for number, cue in enumerate(cues, start=1)
    ]
    return "\n".join(blocks)


def render_vtt(cues: list[Cue], **_: Any) -> str:
    blocks = [
        f"{format_vtt_time(cue.start)} --> {format_vtt_time(cue.end)}\n{cue.text}\n"
        for cue in cues
    ]
    return "WEBVTT\n\n" + "\n".join(blocks)


def render_txt(cues: list[Cue], **_: Any) -> str:
    return "\n".join(cue.text.replace("\n", " ") for cue in cues) + ("\n" if cues else "")


def render_json(cues: list[Cue], language: str | None = None, duration: float = 0.0,
                task: str = "transcribe", **_: Any) -> str:
    payload = {
        "language": language,
        "task": task,
        "duration": round(float(duration), 3),
        "segments": [
            {"id": number, "start": round(cue.start, 3), "end": round(cue.end, 3),
             "text": cue.text.replace("\n", " ")}
            for number, cue in enumerate(cues)
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,64,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def render_ass(cues: list[Cue], **_: Any) -> str:
    lines = []
    for cue in cues:
        text = cue.text.replace("{", "(").replace("}", ")").replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{format_ass_time(cue.start)},{format_ass_time(cue.end)},Default,,0,0,0,,{text}")
    return ASS_HEADER + "\n".join(lines) + "\n"


# формат -> (функция, кодировка)
FORMAT_WRITERS: dict[str, tuple[Callable[..., str], str]] = {
    "srt": (render_srt, "utf-8-sig"),
    "vtt": (render_vtt, "utf-8"),
    "txt": (render_txt, "utf-8-sig"),
    "json": (render_json, "utf-8"),
    "ass": (render_ass, "utf-8-sig"),
}


def write_text_atomic(path: Path, content: str, encoding: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding=encoding, newline="\n") as handle:
            handle.write(content)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def write_outputs(cues: list[Cue], outputs: dict[str, Path], language: str | None,
                  duration: float, task: str) -> None:
    for fmt, path in outputs.items():
        render, encoding = FORMAT_WRITERS[fmt]
        write_text_atomic(path, render(cues, language=language, duration=duration, task=task), encoding)
        LOG.info("Сохранено (%s): %s", fmt.upper(), path)


# --------------------------------------------------------------------------------------
# Устройство и модель
# --------------------------------------------------------------------------------------
def resolve_device(requested: str) -> str:
    if requested == "auto":
        try:
            import ctranslate2
            return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            return "cpu"
    return requested


def get_compute_type(device: str) -> str:
    if device == "cpu":
        return "int8"

    try:
        import ctranslate2
        supported = ctranslate2.get_supported_compute_types("cuda")
        LOG.info("Поддерживаемые compute_type на CUDA: %s", supported)
        for candidate in ("float16", "int8_float16", "bfloat16", "float32"):
            if candidate in supported:
                LOG.info("Выбран compute_type: %s", candidate)
                return candidate
        LOG.warning("Ни один из предпочтительных типов не найден, использую float32.")
        return "float32"
    except Exception as exc:
        LOG.warning("Не удалось получить список поддерживаемых compute_type (%s). Использую int8.", exc)
        return "int8"


def model_repo_id(name: str) -> str | None:
    try:
        from faster_whisper.utils import _MODELS  # type: ignore[attr-defined]
        if name in _MODELS:
            return _MODELS[name]
    except Exception:
        pass
    return FALLBACK_MODEL_REPOS.get(name)


def find_cached_model(name: str, cache_dir: Path | None = None) -> Path | None:
    """Папка скачанной модели или None, если модели ещё нет на диске."""
    repo = model_repo_id(name)
    if repo is None:
        return None
    try:
        from huggingface_hub import snapshot_download
        kwargs: dict[str, Any] = {"allow_patterns": MODEL_ALLOW_PATTERNS, "local_files_only": True}
        if cache_dir:
            kwargs["cache_dir"] = str(cache_dir)
        path = Path(snapshot_download(repo, **kwargs))
    except Exception:
        return None
    return path if (path / "model.bin").is_file() and (path / "config.json").is_file() else None


def _hub_cache_root(cache_dir: Path | None) -> Path:
    if cache_dir:
        return Path(cache_dir)
    try:
        from huggingface_hub import constants
        return Path(constants.HF_HUB_CACHE)
    except Exception:
        return Path.home() / ".cache" / "huggingface" / "hub"


def _directory_size(path: Path) -> int:
    total = 0
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    if entry.is_file():
                        total += entry.stat().st_size
                except OSError:
                    continue
    except OSError:
        return 0
    return total


def download_model(
    name: str,
    cache_dir: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Скачивает модель (если её нет) и сообщает прогресс как (скачано байт, всего байт)."""
    cached = find_cached_model(name, cache_dir)
    if cached is not None:
        if progress:
            progress(1, 1)
        return cached

    repo = model_repo_id(name)
    if repo is None:
        raise ValueError(f"Неизвестная модель: {name}")

    from huggingface_hub import HfApi, snapshot_download

    total = 0
    try:
        info = HfApi().model_info(repo, files_metadata=True)
        for sibling in info.siblings or []:
            if any(fnmatch.fnmatch(sibling.rfilename, pattern) for pattern in MODEL_ALLOW_PATTERNS):
                total += int(sibling.size or 0)
    except Exception as exc:
        LOG.warning("Не удалось узнать размер модели (%s). Прогресс будет приблизительным.", exc)

    blobs_dir = _hub_cache_root(cache_dir) / f"models--{repo.replace('/', '--')}" / "blobs"
    stop = threading.Event()

    def watch() -> None:
        last = -1
        while not stop.wait(0.4):
            done = _directory_size(blobs_dir)
            if done != last and progress:
                progress(min(done, total) if total else done, total)
                last = done

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    LOG.info("Скачиваю модель '%s' (%s)…", name, repo)
    try:
        kwargs: dict[str, Any] = {"allow_patterns": MODEL_ALLOW_PATTERNS}
        if cache_dir:
            kwargs["cache_dir"] = str(cache_dir)
        path = Path(snapshot_download(repo, **kwargs))
    finally:
        stop.set()
        watcher.join(timeout=2)
    if progress:
        progress(total or 1, total or 1)
    LOG.info("Модель '%s' скачана.", name)
    return path


def create_model(
    model_name: str,
    device: str,
    compute_type: str,
    cache_dir: Path | None = None,
) -> WhisperModel:
    from faster_whisper import WhisperModel  # тяжёлый импорт: только когда модель действительно нужна

    cpu_threads = min(8, os.cpu_count() or 4)
    cached = find_cached_model(model_name, cache_dir)
    return WhisperModel(
        str(cached) if cached else model_name,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
        download_root=str(cache_dir) if cache_dir else None,
    )


# --------------------------------------------------------------------------------------
# Распознавание
# --------------------------------------------------------------------------------------
def _is_cuda_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in CUDA_ERROR_MARKERS)


def _run_transcription(
    model: WhisperModel,
    audio_path: Path,
    language: str | None,
    beam_size: int,
    args: argparse.Namespace,
    progress_callback: Callable[[float, float], None] | None,
) -> tuple[list[Any], float, str | None]:
    word_level = getattr(args, "max_line_chars", 0) > 0 or getattr(args, "max_duration", 0) > 0
    segments_generator, info = model.transcribe(
        str(audio_path),
        language=language,
        task=args.task,
        beam_size=beam_size,
        vad_filter=args.vad_filter,
        vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=200) if args.vad_filter else None,
        condition_on_previous_text=False,
        temperature=[0.0, 0.2, 0.4],
        word_timestamps=word_level,
    )

    total_duration = float(getattr(info, "duration", 0.0) or 0.0)
    LOG.info("Длительность аудио: %.1f сек (определён язык: %s)", total_duration, info.language)

    segments: list[Any] = []
    last_percent = -1.0
    for segment in segments_generator:
        segments.append(segment)
        if progress_callback is not None and total_duration > 0:
            percent = (segment.end / total_duration) * 100.0
            percent = max(0.0, min(100.0, percent))
            if abs(percent - last_percent) >= 0.5:
                progress_callback(segment.end, total_duration)
                last_percent = percent
    return segments, total_duration, info.language


def transcribe_one(
    source: Path,
    outputs: dict[str, Path],
    model: WhisperModel,
    model_name: str,
    device: str,
    args: argparse.Namespace,
    progress_callback: Callable[[float, float], None] | None = None,
) -> tuple[WhisperModel, str]:
    _, audio_streams = get_audio_streams(source)
    selected_stream = choose_audio_stream(audio_streams, args.audio_stream)
    stream_index = int(selected_stream["index"])
    tags = selected_stream.get("tags") or {}
    LOG.info("Источник: %s | аудиопоток %s | язык дорожки: %s | кодек: %s",
             source.name, stream_index, tags.get("language", "не указан"),
             selected_stream.get("codec_name", "неизвестно"))

    if args.temp_dir:
        args.temp_dir.mkdir(parents=True, exist_ok=True)
        temporary_parent = str(args.temp_dir)
    else:
        temporary_parent = None

    language = None if args.language.strip().lower() == "auto" else args.language.strip().lower()

    with tempfile.TemporaryDirectory(prefix="whisper_transcribe_", dir=temporary_parent) as temp_name:
        audio_path = Path(temp_name) / "audio.wav"
        extract_audio_track(source, audio_path, stream_index)
        LOG.info("Начинаю распознавание: %s", source.name)

        # Для turbo модели beam=1 дает практически то же качество, но работает в 2x быстрее
        effective_beam = 1 if "turbo" in model_name.lower() else getattr(args, "beam_size", 5)

        try:
            segments, total_duration, detected = _run_transcription(
                model, audio_path, language, effective_beam, args, progress_callback)
        except Exception as exc:
            # Видеокарта есть, но не хватает библиотек CUDA (cuBLAS/cuDNN): переходим на CPU.
            # Если пользователь явно выбрал cuda, ошибку не скрываем.
            if device != "cuda" or getattr(args, "device", "auto") == "cuda" or not _is_cuda_error(exc):
                raise
            LOG.warning("Ошибка CUDA (%s). Переключаюсь на CPU и повторяю распознавание.", exc)
            model = create_model(model_name, "cpu", "int8", getattr(args, "model_dir", None))
            device = "cpu"
            segments, total_duration, detected = _run_transcription(
                model, audio_path, language, effective_beam, args, progress_callback)

        LOG.info("Распознано сегментов: %d", len(segments))

    if progress_callback is not None:
        progress_callback(total_duration, total_duration)

    cues = segments_to_cues(
        segments,
        max_line_chars=getattr(args, "max_line_chars", 0),
        max_lines=getattr(args, "max_lines", 2),
        max_duration=getattr(args, "max_duration", 0.0),
    )
    LOG.info("Реплик субтитров: %d", len(cues))
    write_outputs(cues, outputs, detected, total_duration, args.task)
    return model, device


# --------------------------------------------------------------------------------------
# Файлы
# --------------------------------------------------------------------------------------
def find_input_files(input_path: Path, recursive: bool) -> tuple[list[Path], Path | None]:
    if not input_path.exists():
        raise FileNotFoundError(f"Путь не существует: {input_path}")
    if input_path.is_file():
        if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Расширение {input_path.suffix or '(без расширения)'} не входит в список поддерживаемых.")
        return [input_path], None
    if not input_path.is_dir():
        raise ValueError(f"Это не файл и не папка: {input_path}")

    candidates = input_path.rglob("*") if recursive else input_path.iterdir()
    files = sorted(
        (p for p in candidates if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS),
        key=lambda p: str(p).casefold(),
    )
    return files, input_path


def output_path_for(source: Path, output_dir: Path | None, input_root: Path | None, ext: str = "srt") -> Path:
    filename = f"{source.stem}.whisper.{ext}"
    if output_dir is None:
        return source.with_name(filename)
    if input_root is not None:
        relative_parent = source.parent.relative_to(input_root)
        return output_dir / relative_parent / filename
    return output_dir / filename


def output_paths_for(source: Path, output_dir: Path | None, input_root: Path | None,
                     formats: list[str]) -> dict[str, Path]:
    return {fmt: output_path_for(source, output_dir, input_root, fmt) for fmt in formats}


def main() -> int:
    args = parse_args()
    setup_logging(args.log_level)

    if args.list_streams:
        if not args.input.is_file():
            LOG.error("--list-streams работает только с одним медиафайлом.")
            return 2
        return 0 if print_streams(args.input) else 1

    try:
        files, input_root = find_input_files(args.input, args.recursive)
    except (OSError, ValueError) as exc:
        LOG.error("%s", exc)
        return 2

    if not files:
        LOG.error("В указанном месте не найдено поддерживаемых медиафайлов.")
        return 1

    LOG.info("Найдено файлов: %d", len(files))
    try:
        device = resolve_device(args.device)
        compute_type = get_compute_type(device)

        last_logged = [-10]

        def log_download(done: int, total: int) -> None:
            if total <= 0:
                return
            percent = int(done * 100 / total)
            if percent >= last_logged[0] + 10:
                last_logged[0] = percent - percent % 10
                LOG.info("Загрузка модели: %d%% (%.0f из %.0f МБ)", percent, done / 1048576, total / 1048576)

        download_model(args.model, args.model_dir, log_download)
        LOG.info("Загружаю faster-whisper модель '%s' на устройстве %s (compute_type=%s)...",
                 args.model, device, compute_type)
        model = create_model(args.model, device, compute_type, args.model_dir)
        LOG.info("Модель загружена.")
    except Exception as exc:
        LOG.error("Не удалось загрузить модель: %s", exc, exc_info=args.log_level == "DEBUG")
        return 1

    success_count = 0
    skipped_count = 0
    failed: list[tuple[Path, str]] = []

    for number, source in enumerate(files, start=1):
        outputs = output_paths_for(source, args.output_dir, input_root, args.formats)
        LOG.info("[%d/%d] %s", number, len(files), source)

        if not args.overwrite and all(path.exists() for path in outputs.values()):
            LOG.info("Пропускаю, результаты уже существуют (добавьте --overwrite для перезаписи): %s",
                     ", ".join(str(p) for p in outputs.values()))
            skipped_count += 1
            continue

        try:
            model, device = transcribe_one(source, outputs, model, args.model, device, args)
            success_count += 1
        except KeyboardInterrupt:
            LOG.warning("Прервано пользователем.")
            return 130
        except Exception as exc:
            LOG.error("Не удалось обработать '%s': %s", source, exc, exc_info=args.log_level == "DEBUG")
            failed.append((source, str(exc)))

    LOG.info("Готово. Успешно: %d | пропущено: %d | ошибок: %d",
             success_count, skipped_count, len(failed))
    if failed:
        LOG.error("Файлы с ошибками:")
        for path, error in failed:
            LOG.error("  %s: %s", path, error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
