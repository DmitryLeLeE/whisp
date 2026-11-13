#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Universal batch transcription to subtitles using faster-whisper and FFmpeg."""
from __future__ import annotations

import argparse
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

import hub
import i18n
from hub import Cancelled
from i18n import t

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

    from translator import SubtitleTranslator

__version__ = "1.2.0"

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
VARIANTS = ("original", "translated", "bilingual")

# Fallback table in case faster-whisper changes its internal model dictionary.
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
MODEL_REQUIRED = ["model.bin", "config.json"]

SENTENCE_END = (".", "!", "?", "…", "。", "！", "？")
CUDA_ERROR_MARKERS = ("cublas", "cudnn", "cufft", "curand", "nvrtc", "cuda")


# --------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------
def parse_formats(value: str | list[str] | tuple[str, ...]) -> list[str]:
    items = value.split(",") if isinstance(value, str) else list(value)
    result: list[str] = []
    for item in items:
        fmt = item.strip().lower().lstrip(".")
        if not fmt:
            continue
        if fmt not in OUTPUT_FORMATS:
            raise ValueError(t("err.unknown_format", fmt=fmt, available=", ".join(OUTPUT_FORMATS)))
        if fmt not in result:
            result.append(fmt)
    if not result:
        raise ValueError(t("err.no_format"))
    return result


def parse_variants(value: str | list[str] | tuple[str, ...]) -> list[str]:
    items = value.split(",") if isinstance(value, str) else list(value)
    result: list[str] = []
    for item in items:
        name = item.strip().lower()
        if not name:
            continue
        if name not in VARIANTS:
            raise ValueError(t("err.unknown_variant", name=name, available=", ".join(VARIANTS)))
        if name not in result:
            result.append(name)
    if not result:
        raise ValueError(t("err.no_variant"))
    return result


def _preparse_language(argv: list[str]) -> str:
    """Language of messages: --lang is read before the main parser so that --help is translated too."""
    for position, item in enumerate(argv):
        if item.startswith("--lang="):
            return item.split("=", 1)[1]
        if item == "--lang" and position + 1 < len(argv):
            return argv[position + 1]
    return "auto"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    argv = list(sys.argv[1:] if argv is None else argv)
    i18n.set_language(_preparse_language(argv))

    from translator import LANGUAGE_CODES

    parser = argparse.ArgumentParser(description=t("help.description"))
    parser.add_argument("input", type=Path, nargs="?", help=t("help.input"))
    parser.add_argument("-o", "--output-dir", type=Path, default=None, help=t("help.output_dir"))
    parser.add_argument("-r", "--recursive", action="store_true", help=t("help.recursive"))
    parser.add_argument("-m", "--model", choices=MODEL_CHOICES, default="small", help=t("help.model"))
    parser.add_argument("--model-dir", type=Path, default=None, help=t("help.model_dir"))
    parser.add_argument("-l", "--language", default="auto", help=t("help.language"))
    parser.add_argument("--task", choices=("transcribe", "translate"), default="transcribe", help=t("help.task"))
    parser.add_argument("--translate-to", default="", metavar="LANG", help=t("help.translate_to", langs=", ".join(LANGUAGE_CODES)))
    parser.add_argument("--variants", default="original,translated", help=t("help.variants"))
    parser.add_argument("-f", "--formats", default="srt", help=t("help.formats"))
    parser.add_argument("--max-line-chars", type=int, default=0, help=t("help.max_line_chars"))
    parser.add_argument("--max-lines", type=int, default=2, help=t("help.max_lines"))
    parser.add_argument("--max-duration", type=float, default=0.0, help=t("help.max_duration"))
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto", help=t("help.device"))
    parser.add_argument("--audio-stream", default="auto", help=t("help.audio_stream"))
    parser.add_argument("--temp-dir", type=Path, default=None, help=t("help.temp_dir"))
    parser.add_argument("--overwrite", action="store_true", help=t("help.overwrite"))
    parser.add_argument("--beam-size", type=int, default=5, help=t("help.beam_size"))
    parser.add_argument("--vad-filter", action="store_true", default=True, help=t("help.vad"))
    parser.add_argument("--no-vad", action="store_false", dest="vad_filter", help=t("help.no_vad"))
    parser.add_argument("--quiet-progress", action="store_true", help=t("help.quiet"))
    parser.add_argument("--list-streams", action="store_true", help=t("help.list_streams"))
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO",
                        help=t("help.log_level"))
    parser.add_argument("--lang", choices=("auto", "ru", "en"), default="auto", help=t("help.lang"))
    parser.add_argument("--version", action="version", version=f"WhisperSRT {__version__}")
    args = parser.parse_args(argv)

    if args.input is None:
        parser.error(t("err.no_input"))

    try:
        args.formats = parse_formats(args.formats)
        args.variants = parse_variants(args.variants)
    except ValueError as exc:
        parser.error(str(exc))
    if args.max_line_chars < 0 or args.max_lines < 1 or args.max_duration < 0:
        parser.error(t("err.bad_limits"))

    args.translate_to = args.translate_to.strip().lower()
    if args.translate_to:
        if args.translate_to not in LANGUAGE_CODES:
            parser.error(t("err.bad_translate_to", lang=args.translate_to, langs=", ".join(LANGUAGE_CODES)))
        if args.task == "translate":
            parser.error(t("err.task_and_mt"))
    else:
        args.variants = ["original"]

    if args.audio_stream != "auto":
        try:
            args.audio_stream = int(args.audio_stream)
            if args.audio_stream < 0:
                parser.error(t("err.bad_stream"))
        except ValueError:
            parser.error(t("err.bad_stream_int"))

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
# FFmpeg: streams and audio extraction
# --------------------------------------------------------------------------------------
def probe_media(path: Path) -> dict[str, Any]:
    try:
        return ffmpeg.probe(str(path))
    except ffmpeg.Error as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
        raise RuntimeError(t("err.ffmpeg_read", detail=stderr.strip())) from exc


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
        parts.append(t("stream.channels", n=channels))
    label = " · ".join(parts)
    if disposition.get("default") == 1:
        label += t("stream.default")
    return label


def probe_audio_info(path: Path) -> tuple[float, list[tuple[int, str]]]:
    """Returns the file duration in seconds and a list of (stream index, label) for its audio tracks."""
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

    LOG.info(t("log.file", path=path))
    if not audio_streams:
        LOG.warning(t("log.no_audio_streams"))
        return False

    for position, stream in enumerate(audio_streams, start=1):
        index = stream.get("index", "?")
        tags = stream.get("tags") or {}
        disposition = stream.get("disposition") or {}
        language = tags.get("language", t("stream.unspecified"))
        title = tags.get("title", "")
        codec = stream.get("codec_name", t("stream.unknown"))
        channels = stream.get("channels", "?")
        sample_rate = stream.get("sample_rate", "?")
        default = " [DEFAULT]" if disposition.get("default") == 1 else ""
        title_text = t("log.stream_title", title=title) if title else ""
        LOG.info(t("log.stream_line", position=position, index=index, language=language, codec=codec,
                   channels=channels, rate=sample_rate, title=title_text, default=default))
    return True


def choose_audio_stream(audio_streams: list[dict[str, Any]], requested: str | int) -> dict[str, Any]:
    if not audio_streams:
        raise RuntimeError(t("err.no_audio"))

    if requested != "auto":
        for stream in audio_streams:
            if stream.get("index") == requested:
                return stream
        available = ", ".join(str(s.get("index")) for s in audio_streams)
        raise RuntimeError(t("err.stream_not_found", requested=requested, available=available))

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
        raise RuntimeError(t("err.ffmpeg_extract", detail=stderr.strip())) from exc



# --------------------------------------------------------------------------------------
# Subtitle cues and output formats
# --------------------------------------------------------------------------------------
@dataclass
class Cue:
    start: float
    end: float
    text: str  # lines are separated by \n


def _clean_text(text: str) -> str:
    lines = (line.strip() for line in str(text).replace("\r", "\n").split("\n"))
    return "\n".join(line for line in lines if line)


def _segment_words(segment: Any) -> list[tuple[float, float, str]]:
    """Words of a segment with timing. Without word timestamps the time is split in proportion to word length."""
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
    """Turns model segments into cues. Without limits a cue equals a model segment."""
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
                task: str = "transcribe", translated_to: str | None = None, **_: Any) -> str:
    payload = {
        "language": language,
        "task": task,
        "translated_to": translated_to,
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

# format -> (renderer, encoding)
FORMAT_WRITERS: dict[str, tuple[Callable[..., str], str]] = {
    "srt": (render_srt, "utf-8-sig"),
    "vtt": (render_vtt, "utf-8"),
    "txt": (render_txt, "utf-8-sig"),
    "json": (render_json, "utf-8"),
    "ass": (render_ass, "utf-8-sig"),
}


def make_bilingual(original: list[Cue], translated: list[Cue]) -> list[Cue]:
    """Original line(s) first, the translation below them."""
    return [Cue(o.start, o.end, o.text + "\n" + tr.text) for o, tr in zip(original, translated)]


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


def write_outputs(cue_sets: dict[str, list[Cue]], outputs: dict[tuple[str, str], Path], language: str | None,
                  duration: float, task: str, translated_to: str | None = None) -> None:
    """Writes every (variant, format) pair from `outputs` using the cues of that variant."""
    for (variant, fmt), path in outputs.items():
        render, encoding = FORMAT_WRITERS[fmt]
        content = render(cue_sets[variant], language=language, duration=duration, task=task,
                         translated_to=None if variant == "original" else translated_to)
        write_text_atomic(path, content, encoding)
        LOG.info(t("log.saved", fmt=fmt.upper(), path=path))


# --------------------------------------------------------------------------------------
# Device and models
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
        LOG.info(t("log.compute_supported", supported=supported))
        for candidate in ("float16", "int8_float16", "bfloat16", "float32"):
            if candidate in supported:
                LOG.info(t("log.compute_chosen", name=candidate))
                return candidate
        LOG.warning(t("log.compute_none"))
        return "float32"
    except Exception as exc:
        LOG.warning(t("log.compute_error", error=exc))
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
    """Folder of a downloaded model, or None if the model is not on disk yet."""
    repo = model_repo_id(name)
    if repo is None:
        return None
    return hub.find_cached_repo(repo, MODEL_ALLOW_PATTERNS, MODEL_REQUIRED, cache_dir)


def download_model(
    name: str,
    cache_dir: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Downloads the model if missing; reports progress as (bytes done, bytes total)."""
    repo = model_repo_id(name)
    if repo is None:
        raise ValueError(t("err.unknown_model", name=name))
    return hub.download_repo(repo, MODEL_ALLOW_PATTERNS, MODEL_REQUIRED, cache_dir, progress, label=name)


def create_model(
    model_name: str,
    device: str,
    compute_type: str,
    cache_dir: Path | None = None,
) -> WhisperModel:
    from faster_whisper import WhisperModel  # heavy import: only when the model is really needed

    cpu_threads = min(8, os.cpu_count() or 4)
    cached = find_cached_model(model_name, cache_dir)
    return WhisperModel(
        str(cached) if cached else model_name,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
        download_root=str(cache_dir) if cache_dir else None,
    )


class TranslatorProvider:
    """Downloads (if needed) and loads the NLLB translator on first use, then keeps it."""

    def __init__(self, device: str, cache_dir: Path | None = None,
                 download_progress: Callable[[int, int], None] | None = None) -> None:
        self.device = device
        self.cache_dir = cache_dir
        self.download_progress = download_progress
        self._translator: SubtitleTranslator | None = None

    def get(self) -> SubtitleTranslator:
        if self._translator is None:
            import translator as mt
            path = mt.download_translator(self.cache_dir, self.download_progress)
            LOG.info(t("log.mt_loading"))
            self._translator = mt.SubtitleTranslator(path, self.device)
            LOG.info(t("log.mt_ready"))
        return self._translator


# --------------------------------------------------------------------------------------
# Transcription
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
    cancel: threading.Event | None = getattr(args, "cancel_event", None)
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
    LOG.info(t("log.duration", seconds=total_duration, language=info.language))

    segments: list[Any] = []
    last_percent = -1.0
    for segment in segments_generator:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        segments.append(segment)
        if progress_callback is not None and total_duration > 0:
            percent = (segment.end / total_duration) * 100.0
            percent = max(0.0, min(100.0, percent))
            if abs(percent - last_percent) >= 0.5:
                progress_callback(segment.end, total_duration)
                last_percent = percent
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    return segments, total_duration, info.language


def _wrap_if_needed(text: str, args: argparse.Namespace) -> str:
    width = getattr(args, "max_line_chars", 0)
    if width > 0:
        return wrap_cue_text(text, width, max(1, getattr(args, "max_lines", 2)))
    return text


def build_cue_sets(
    cues: list[Cue],
    wanted: set[str],
    source_lang: str | None,
    args: argparse.Namespace,
    translator_provider: TranslatorProvider | None,
    translate_progress: Callable[[int, int], None] | None = None,
) -> dict[str, list[Cue]]:
    """Cues for each requested variant; translates with NLLB when 'translated' or 'bilingual' is requested."""
    cue_sets: dict[str, list[Cue]] = {"original": cues}
    if not (wanted & {"translated", "bilingual"}):
        return cue_sets

    target = getattr(args, "translate_to", "")
    if not target or translator_provider is None:
        raise RuntimeError(t("err.mt_not_configured"))
    source = (source_lang or "").lower()

    if source == target:
        LOG.warning(t("log.mt_same_language", lang=target))
        translated = [Cue(c.start, c.end, c.text) for c in cues]
    elif not cues:
        translated = []
    else:
        translator = translator_provider.get()
        LOG.info(t("log.mt_start", source=source, target=target, count=len(cues)))
        texts = translator.translate([c.text for c in cues], source, target,
                                     cancel=getattr(args, "cancel_event", None), progress=translate_progress)
        translated = [Cue(c.start, c.end, _wrap_if_needed(text, args)) for c, text in zip(cues, texts)]
        LOG.info(t("log.mt_done"))

    cue_sets["translated"] = translated
    cue_sets["bilingual"] = make_bilingual(cues, translated)
    return cue_sets


def transcribe_one(
    source: Path,
    outputs: dict[tuple[str, str], Path],
    model: WhisperModel,
    model_name: str,
    device: str,
    args: argparse.Namespace,
    progress_callback: Callable[[float, float], None] | None = None,
    translator_provider: TranslatorProvider | None = None,
    translate_progress: Callable[[int, int], None] | None = None,
) -> tuple[WhisperModel, str]:
    _, audio_streams = get_audio_streams(source)
    selected_stream = choose_audio_stream(audio_streams, args.audio_stream)
    stream_index = int(selected_stream["index"])
    tags = selected_stream.get("tags") or {}
    LOG.info(t("log.source", name=source.name, index=stream_index,
               language=tags.get("language", t("stream.unspecified")),
               codec=selected_stream.get("codec_name", t("stream.unknown"))))

    if args.temp_dir:
        args.temp_dir.mkdir(parents=True, exist_ok=True)
        temporary_parent = str(args.temp_dir)
    else:
        temporary_parent = None

    language = None if args.language.strip().lower() == "auto" else args.language.strip().lower()

    with tempfile.TemporaryDirectory(prefix="whisper_transcribe_", dir=temporary_parent) as temp_name:
        audio_path = Path(temp_name) / "audio.wav"
        extract_audio_track(source, audio_path, stream_index)
        LOG.info(t("log.transcribing", name=source.name))

        # For the turbo model beam=1 gives almost the same quality twice as fast
        effective_beam = 1 if "turbo" in model_name.lower() else getattr(args, "beam_size", 5)

        try:
            segments, total_duration, detected = _run_transcription(
                model, audio_path, language, effective_beam, args, progress_callback)
        except Cancelled:
            raise
        except Exception as exc:
            # A GPU exists but the CUDA libraries (cuBLAS/cuDNN) are missing: fall back to CPU.
            # If the user explicitly chose cuda, the error is not hidden.
            if device != "cuda" or getattr(args, "device", "auto") == "cuda" or not _is_cuda_error(exc):
                raise
            LOG.warning(t("log.cuda_fallback", error=exc))
            model = create_model(model_name, "cpu", "int8", getattr(args, "model_dir", None))
            device = "cpu"
            segments, total_duration, detected = _run_transcription(
                model, audio_path, language, effective_beam, args, progress_callback)

        LOG.info(t("log.segments", count=len(segments)))

    if progress_callback is not None:
        progress_callback(total_duration, total_duration)

    cues = segments_to_cues(
        segments,
        max_line_chars=getattr(args, "max_line_chars", 0),
        max_lines=getattr(args, "max_lines", 2),
        max_duration=getattr(args, "max_duration", 0.0),
    )
    LOG.info(t("log.cues", count=len(cues)))
    wanted = {variant for variant, _ in outputs}
    cue_sets = build_cue_sets(cues, wanted, detected or language, args, translator_provider, translate_progress)
    write_outputs(cue_sets, outputs, detected, total_duration, args.task,
                  translated_to=getattr(args, "translate_to", "") or None)
    return model, device


# --------------------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------------------
def find_input_files(input_path: Path, recursive: bool) -> tuple[list[Path], Path | None]:
    if not input_path.exists():
        raise FileNotFoundError(t("err.path_missing", path=input_path))
    if input_path.is_file():
        if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(t("err.bad_extension", ext=input_path.suffix or t("err.no_extension")))
        return [input_path], None
    if not input_path.is_dir():
        raise ValueError(t("err.not_file_or_dir", path=input_path))

    candidates = input_path.rglob("*") if recursive else input_path.iterdir()
    files = sorted(
        (p for p in candidates if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS),
        key=lambda p: str(p).casefold(),
    )
    return files, input_path


def output_path_for(source: Path, output_dir: Path | None, input_root: Path | None, ext: str = "srt",
                    variant: str = "original", target: str = "") -> Path:
    """original: name.whisper.srt | translated: name.whisper.en.srt | bilingual: name.whisper.en.bilingual.srt"""
    if variant == "translated":
        suffix = f".{target}"
    elif variant == "bilingual":
        suffix = f".{target}.bilingual"
    else:
        suffix = ""
    filename = f"{source.stem}.whisper{suffix}.{ext}"
    if output_dir is None:
        return source.with_name(filename)
    if input_root is not None:
        relative_parent = source.parent.relative_to(input_root)
        return output_dir / relative_parent / filename
    return output_dir / filename


def output_paths_for(source: Path, output_dir: Path | None, input_root: Path | None,
                     formats: list[str], variants: list[str] | tuple[str, ...] = ("original",),
                     target: str = "") -> dict[tuple[str, str], Path]:
    return {(variant, fmt): output_path_for(source, output_dir, input_root, fmt, variant, target)
            for variant in variants for fmt in formats}


def _percent_logger(key: str) -> Callable[[int, int], None]:
    last = [-10]

    def log_progress(done: int, total: int) -> None:
        if total <= 0:
            return
        percent = int(done * 100 / total)
        if percent >= last[0] + 10:
            last[0] = percent - percent % 10
            LOG.info(t(key, percent=percent, done=done / 1048576, total=total / 1048576))

    return log_progress


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.log_level)

    if args.list_streams:
        if not args.input.is_file():
            LOG.error(t("err.list_streams_single"))
            return 2
        return 0 if print_streams(args.input) else 1

    try:
        files, input_root = find_input_files(args.input, args.recursive)
    except (OSError, ValueError) as exc:
        LOG.error("%s", exc)
        return 2

    if not files:
        LOG.error(t("err.no_files"))
        return 1

    LOG.info(t("log.found_files", count=len(files)))
    provider: TranslatorProvider | None = None
    try:
        device = resolve_device(args.device)
        compute_type = get_compute_type(device)

        download_model(args.model, args.model_dir, _percent_logger("log.download_progress"))
        LOG.info(t("log.loading_model", name=args.model, device=device, compute=compute_type))
        model = create_model(args.model, device, compute_type, args.model_dir)
        LOG.info(t("log.model_loaded"))
        if args.translate_to:
            LOG.info(t("log.mt_license"))
            provider = TranslatorProvider(device, args.model_dir, _percent_logger("log.download_progress_mt"))
    except Exception as exc:
        LOG.error(t("err.model_load", error=exc), exc_info=args.log_level == "DEBUG")
        return 1

    success_count = 0
    skipped_count = 0
    failed: list[tuple[Path, str]] = []

    for number, source in enumerate(files, start=1):
        outputs = output_paths_for(source, args.output_dir, input_root, args.formats,
                                   args.variants, args.translate_to)
        LOG.info("[%d/%d] %s", number, len(files), source)

        if not args.overwrite and all(path.exists() for path in outputs.values()):
            LOG.info(t("log.skip_existing", paths=", ".join(str(p) for p in outputs.values())))
            skipped_count += 1
            continue

        try:
            model, device = transcribe_one(source, outputs, model, args.model, device, args,
                                           translator_provider=provider)
            success_count += 1
        except KeyboardInterrupt:
            LOG.warning(t("log.interrupted"))
            return 130
        except Exception as exc:
            LOG.error(t("err.file_failed", path=source, error=exc), exc_info=args.log_level == "DEBUG")
            failed.append((source, str(exc)))

    LOG.info(t("log.summary", ok=success_count, skipped=skipped_count, failed=len(failed)))
    if failed:
        LOG.error(t("log.failed_header"))
        for path, error in failed:
            LOG.error("  %s: %s", path, error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
