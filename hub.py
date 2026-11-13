# -*- coding: utf-8 -*-
"""Загрузка моделей с Hugging Face: поиск в кэше и скачивание с прогрессом."""
from __future__ import annotations

import fnmatch
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Sequence

from i18n import t

LOG = logging.getLogger("whisper_universal")


def hub_cache_root(cache_dir: Path | None) -> Path:
    if cache_dir:
        return Path(cache_dir)
    try:
        from huggingface_hub import constants
        return Path(constants.HF_HUB_CACHE)
    except Exception:
        return Path.home() / ".cache" / "huggingface" / "hub"


def directory_size(path: Path) -> int:
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


def find_cached_repo(repo: str, patterns: Sequence[str], required: Sequence[str],
                     cache_dir: Path | None = None) -> Path | None:
    """Папка репозитория в кэше, если все файлы из `required` уже скачаны."""
    try:
        from huggingface_hub import snapshot_download
        kwargs: dict[str, Any] = {"allow_patterns": list(patterns), "local_files_only": True}
        if cache_dir:
            kwargs["cache_dir"] = str(cache_dir)
        path = Path(snapshot_download(repo, **kwargs))
    except Exception:
        return None
    return path if all((path / name).is_file() for name in required) else None


def download_repo(
    repo: str,
    patterns: Sequence[str],
    required: Sequence[str],
    cache_dir: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    label: str = "",
) -> Path:
    """Скачивает файлы репозитория (если их нет) и сообщает прогресс как (скачано байт, всего байт)."""
    cached = find_cached_repo(repo, patterns, required, cache_dir)
    if cached is not None:
        if progress:
            progress(1, 1)
        return cached

    from huggingface_hub import HfApi, snapshot_download

    total = 0
    try:
        info = HfApi().model_info(repo, files_metadata=True)
        for sibling in info.siblings or []:
            if any(fnmatch.fnmatch(sibling.rfilename, pattern) for pattern in patterns):
                total += int(sibling.size or 0)
    except Exception as exc:
        LOG.warning(t("log.size_unknown", error=exc))

    blobs_dir = hub_cache_root(cache_dir) / f"models--{repo.replace('/', '--')}" / "blobs"
    stop = threading.Event()

    def watch() -> None:
        last = -1
        while not stop.wait(0.4):
            done = directory_size(blobs_dir)
            if done != last and progress:
                progress(min(done, total) if total else done, total)
                last = done

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    LOG.info(t("log.downloading", name=label or repo, repo=repo))
    try:
        kwargs: dict[str, Any] = {"allow_patterns": list(patterns)}
        if cache_dir:
            kwargs["cache_dir"] = str(cache_dir)
        path = Path(snapshot_download(repo, **kwargs))
    finally:
        stop.set()
        watcher.join(timeout=2)
    if progress:
        progress(total or 1, total or 1)
    LOG.info(t("log.downloaded", name=label or repo))
    return path


class Cancelled(Exception):
    """Пользователь отменил обработку."""
