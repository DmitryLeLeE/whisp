#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Universal batch transcription to SRT using OpenAI Whisper and FFmpeg.

Examples:
  python whisper_universal.py "D:/Videos/episode.ts"
  python whisper_universal.py "D:/Videos" --recursive --language ru --model small
  python whisper_universal.py "D:/Videos/episode.ts" --audio-stream 2
  python whisper_universal.py "D:/Videos/episode.ts" --list-streams
  python whisper_universal.py "D:/Videos" --output-dir "D:/Subtitles" --device cpu
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import ffmpeg
import torch
import whisper


LOG = logging.getLogger("whisper_universal")

SUPPORTED_EXTENSIONS = {
    # Video containers
    ".3g2", ".3gp", ".asf", ".avi", ".flv", ".m2ts", ".m4v", ".mkv",
    ".mov", ".mp4", ".mpeg", ".mpg", ".mts", ".ogv", ".ts", ".vob",
    ".webm", ".wmv",
    # Audio containers/formats
    ".aac", ".aiff", ".alac", ".amr", ".flac", ".m4a", ".m4b", ".mp3",
    ".ogg", ".opus", ".wav", ".wma",
}

MODEL_CHOICES = (
    "tiny", "base", "small", "medium", "large", "large-v2", "large-v3", "turbo"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Распознаёт речь в аудио/видео и сохраняет субтитры SRT."
    )
    parser.add_argument(
        "input", type=Path,
        help="Путь к медиафайлу или папке с файлами.",
    )
    parser.add_argument(
        "-o", "--output-dir", type=Path, default=None,
        help="Папка для SRT. Если не указана, субтитры сохраняются рядом с исходниками.",
    )
    parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="Искать медиафайлы в подпапках (для входной папки).",
    )
    parser.add_argument(
        "-m", "--model", choices=MODEL_CHOICES, default="small",
        help="Модель Whisper (по умолчанию: small).",
    )
    parser.add_argument(
        "-l", "--language", default="auto",
        help="Язык речи: ru, en, de и т. п.; auto включает автоопределение (по умолчанию).",
    )
    parser.add_argument(
        "--task", choices=("transcribe", "translate"), default="transcribe",
        help="transcribe = текст на исходном языке; translate = перевод на английский.",
    )
    parser.add_argument(
        "--device", choices=("auto", "cpu", "cuda"), default="auto",
        help="Вычислительное устройство. auto использует CUDA, если она доступна.",
    )
    parser.add_argument(
        "--audio-stream", default="auto",
        help="Глобальный индекс аудиопотока FFmpeg (например, 2) или auto (по умолчанию).",
    )
    parser.add_argument(
        "--temp-dir", type=Path, default=None,
        help="Папка для временных WAV-файлов. Полезно, если системный диск мал.",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Перезаписывать уже существующие SRT-файлы.",
    )
    parser.add_argument(
        "--quiet-progress", action="store_true",
        help="Не выводить подробный прогресс распознавания Whisper.",
    )
    parser.add_argument(
        "--list-streams", action="store_true",
        help="Показать потоки одного медиафайла и завершить работу.",
    )
    parser.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO",
        help="Уровень сообщений журнала (по умолчанию: INFO).",
    )
    args = parser.parse_args()

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
    return args


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


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


def print_streams(path: Path) -> bool:
    try:
        probe, audio_streams = get_audio_streams(path)
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
        LOG.info(
            "Аудиодорожка %d: индекс FFmpeg=%s, язык=%s, кодек=%s, каналов=%s, Hz=%s%s%s",
            position, index, language, codec, channels, sample_rate, title_text, default,
        )
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

    # Prefer the stream marked as default by the container; otherwise use the first audio stream.
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
                },
            )
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
        raise RuntimeError(f"Ошибка извлечения аудио через FFmpeg: {stderr.strip()}") from exc


def format_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamps without wrapping after 24 hours."""
    total_ms = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"


def write_srt(result: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        with temporary_output.open("w", encoding="utf-8-sig", newline="\n") as srt_file:
            for number, segment in enumerate(result.get("segments", []), start=1):
                start_time = format_srt_time(segment.get("start", 0))
                end_time = format_srt_time(segment.get("end", 0))
                text = str(segment.get("text", "")).strip().replace("\r", " ")
                srt_file.write(f"{number}\n{start_time} --> {end_time}\n{text}\n\n")
        temporary_output.replace(output_path)
    finally:
        if temporary_output.exists():
            temporary_output.unlink(missing_ok=True)


def resolve_device(requested: str) -> str:
    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("Выбран --device cuda, но PyTorch не обнаружил доступную CUDA-видеокарту.")
    return requested


def is_cuda_oom(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "out of memory" in message or "cuda error: memory allocation" in message


def transcribe_one(
    source: Path,
    output_path: Path,
    model: Any,
    model_name: str,
    device: str,
    args: argparse.Namespace,
) -> tuple[Any, str]:
    _, audio_streams = get_audio_streams(source)
    selected_stream = choose_audio_stream(audio_streams, args.audio_stream)
    stream_index = int(selected_stream["index"])
    tags = selected_stream.get("tags") or {}
    LOG.info(
        "Источник: %s | аудиопоток %s | язык дорожки: %s | кодек: %s",
        source.name, stream_index, tags.get("language", "не указан"),
        selected_stream.get("codec_name", "неизвестно"),
    )

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

        try:
            result = model.transcribe(
                str(audio_path),
                language=language,
                task=args.task,
                verbose=not args.quiet_progress,
                fp16=(device == "cuda"),
            )
        except Exception as exc:
            if args.device != "auto" or device != "cuda" or not is_cuda_oom(exc):
                raise
            LOG.warning(
                "Не хватило видеопамяти для модели %s. Переключаюсь на CPU и повторяю этот файл.",
                model_name,
            )
            del model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            model = whisper.load_model(model_name, device="cpu")
            device = "cpu"
            result = model.transcribe(
                str(audio_path),
                language=language,
                task=args.task,
                verbose=not args.quiet_progress,
                fp16=False,
            )

    write_srt(result, output_path)
    LOG.info("SRT сохранён: %s", output_path)
    return model, device


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


def output_path_for(source: Path, output_dir: Path | None, input_root: Path | None) -> Path:
    filename = f"{source.stem}.whisper.srt"
    if output_dir is None:
        return source.with_name(filename)
    if input_root is not None:
        relative_parent = source.parent.relative_to(input_root)
        return output_dir / relative_parent / filename
    return output_dir / filename


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
        LOG.info("Загружаю модель Whisper '%s' на устройстве %s...", args.model, device)
        try:
            model = whisper.load_model(args.model, device=device)
        except Exception as exc:
            if args.device == "auto" and device == "cuda":
                LOG.warning("Не удалось загрузить модель на CUDA (%s). Пробую CPU.", exc)
                device = "cpu"
                model = whisper.load_model(args.model, device=device)
            else:
                raise
        LOG.info("Модель загружена.")
    except Exception as exc:
        LOG.error("Не удалось загрузить модель: %s", exc, exc_info=args.log_level == "DEBUG")
        return 1

    success_count = 0
    skipped_count = 0
    failed: list[tuple[Path, str]] = []

    for number, source in enumerate(files, start=1):
        destination = output_path_for(source, args.output_dir, input_root)
        LOG.info("[%d/%d] %s", number, len(files), source)

        if destination.exists() and not args.overwrite:
            LOG.info("Пропускаю, SRT уже существует (добавьте --overwrite для перезаписи): %s", destination)
            skipped_count += 1
            continue

        try:
            model, device = transcribe_one(source, destination, model, args.model, device, args)
            success_count += 1
        except KeyboardInterrupt:
            LOG.warning("Прервано пользователем.")
            return 130
        except Exception as exc:
            LOG.error("Не удалось обработать '%s': %s", source, exc, exc_info=args.log_level == "DEBUG")
            failed.append((source, str(exc)))

    LOG.info(
        "Готово. Успешно: %d | пропущено: %d | ошибок: %d",
        success_count, skipped_count, len(failed),
    )
    if failed:
        LOG.error("Файлы с ошибками:")
        for path, error in failed:
            LOG.error("  %s: %s", path, error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
