# -*- coding: utf-8 -*-
"""Машинный перевод субтитров: NLLB-200 (distilled 600M) через CTranslate2.

Лицензия весов NLLB-200: CC-BY-NC-4.0 (только некоммерческое использование).
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Callable, Sequence

import hub
from i18n import t

LOG = logging.getLogger("whisper_universal")

NLLB_REPO = os.environ.get("WHISPERSRT_NLLB_REPO", "JustFrederik/nllb-200-distilled-600M-ct2-int8")
NLLB_PATTERNS = ["config.json", "model.bin", "sentencepiece.bpe.model", "shared_vocabulary.*"]
NLLB_REQUIRED = ["config.json", "model.bin", "sentencepiece.bpe.model"]

# Код языка Whisper -> код NLLB-200 (FLORES-200)
NLLB_CODES = {
    "ru": "rus_Cyrl", "en": "eng_Latn", "de": "deu_Latn", "uk": "ukr_Cyrl", "fr": "fra_Latn",
    "es": "spa_Latn", "it": "ita_Latn", "pl": "pol_Latn", "pt": "por_Latn", "tr": "tur_Latn",
    "nl": "nld_Latn", "cs": "ces_Latn", "ja": "jpn_Jpan", "zh": "zho_Hans", "ko": "kor_Hang",
    "ar": "arb_Arab", "hi": "hin_Deva", "vi": "vie_Latn",
}
LANGUAGE_CODES = tuple(NLLB_CODES)

CUDA_MARKERS = ("cublas", "cudnn", "cufft", "curand", "nvrtc", "cuda")
BATCH_SIZE = 16


def find_cached_translator(cache_dir: Path | None = None) -> Path | None:
    path = hub.find_cached_repo(NLLB_REPO, NLLB_PATTERNS, NLLB_REQUIRED, cache_dir)
    if path is None or not list(path.glob("shared_vocabulary.*")):
        return None
    return path


def download_translator(cache_dir: Path | None = None,
                        progress: Callable[[int, int], None] | None = None) -> Path:
    path = hub.download_repo(NLLB_REPO, NLLB_PATTERNS, NLLB_REQUIRED, cache_dir, progress, label="NLLB-200")
    if not list(path.glob("shared_vocabulary.*")):
        raise RuntimeError(t("err.mt_incomplete", repo=NLLB_REPO))
    return path


class SubtitleTranslator:
    def __init__(self, model_path: Path, device: str = "cpu") -> None:
        import ctranslate2
        import sentencepiece

        self._ctranslate2 = ctranslate2
        self.model_path = Path(model_path)
        self.device = device
        self.tokenizer = sentencepiece.SentencePieceProcessor(
            model_file=str(self.model_path / "sentencepiece.bpe.model"))
        self.translator = self._load(device)

    def _load(self, device: str):
        threads = min(8, os.cpu_count() or 4)
        try:
            return self._ctranslate2.Translator(
                str(self.model_path), device=device, compute_type="auto", intra_threads=threads)
        except Exception as exc:
            if device != "cuda":
                raise
            LOG.warning(t("log.mt_cuda_fallback", error=exc))
            self.device = "cpu"
            return self._ctranslate2.Translator(
                str(self.model_path), device="cpu", compute_type="auto", intra_threads=threads)

    def _translate_batch(self, sources: list[list[str]], prefixes: list[list[str]]):
        return self.translator.translate_batch(
            sources, target_prefix=prefixes, beam_size=4, max_decoding_length=256, max_batch_size=BATCH_SIZE)

    def translate(
        self,
        texts: Sequence[str],
        source_lang: str,
        target_lang: str,
        cancel: threading.Event | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> list[str]:
        """Переводит список реплик. Коды языков — как у Whisper (ru, en, ...)."""
        if source_lang not in NLLB_CODES:
            raise ValueError(t("err.mt_unsupported_source", lang=source_lang))
        if target_lang not in NLLB_CODES:
            raise ValueError(t("err.mt_unsupported_target", lang=target_lang))
        src, tgt = NLLB_CODES[source_lang], NLLB_CODES[target_lang]

        flat = [" ".join(str(text).split()) for text in texts]
        results = list(flat)
        todo = [index for index, text in enumerate(flat) if text]
        for offset in range(0, len(todo), BATCH_SIZE):
            if cancel is not None and cancel.is_set():
                raise hub.Cancelled()
            chunk = todo[offset:offset + BATCH_SIZE]
            sources = [[src] + self.tokenizer.encode(flat[i], out_type=str) + ["</s>"] for i in chunk]
            prefixes = [[tgt]] * len(chunk)
            try:
                outputs = self._translate_batch(sources, prefixes)
            except Exception as exc:
                if self.device != "cuda" or not any(m in str(exc).lower() for m in CUDA_MARKERS):
                    raise
                LOG.warning(t("log.mt_cuda_fallback", error=exc))
                self.device = "cpu"
                self.translator = self._load("cpu")
                outputs = self._translate_batch(sources, prefixes)
            for index, output in zip(chunk, outputs):
                tokens = output.hypotheses[0][1:]  # первый токен — код целевого языка
                results[index] = self.tokenizer.decode(tokens).strip() or flat[index]
            if progress is not None:
                progress(min(offset + len(chunk), len(todo)), len(todo))
        return results
