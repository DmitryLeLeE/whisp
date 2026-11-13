# -*- coding: utf-8 -*-
"""Interface strings (Russian / English) and the current-language switch."""
from __future__ import annotations

import locale
import os
import sys

LANGUAGES = ("ru", "en")
_current = "en"


def detect_system_language() -> str:
    """'ru' if the system UI language is Russian, otherwise 'en'."""
    try:
        if sys.platform == "win32":
            import ctypes
            return "ru" if (ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF) == 0x19 else "en"
    except Exception:
        pass
    candidates = [os.environ.get(name, "") for name in ("LC_ALL", "LC_MESSAGES", "LANG")]
    try:
        candidates.append(locale.getlocale()[0] or "")
    except Exception:
        pass
    return "ru" if any(item.lower().startswith("ru") for item in candidates) else "en"


def set_language(code: str) -> str:
    """Sets the language ('ru', 'en' or 'auto') and returns the one that is in effect."""
    global _current
    code = (code or "auto").strip().lower()
    _current = detect_system_language() if code not in LANGUAGES else code
    return _current


def get_language() -> str:
    return _current


def t(key: str, **kwargs) -> str:
    table = RU if _current == "ru" else EN
    text = table.get(key)
    if text is None:
        text = EN.get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


RU: dict[str, str] = {}
EN: dict[str, str] = {}

# ======================================================================================
# Engine and command line
# ======================================================================================
RU.update({
    "err.unknown_format": "Неизвестный формат '{fmt}'. Доступны: {available}.",
    "err.no_format": "Не выбран ни один формат вывода.",
    "err.unknown_variant": "Неизвестный вариант '{name}'. Доступны: {available}.",
    "err.no_variant": "Не выбран ни один вариант результата.",
    "err.no_input": "не указан входной файл или папка.",
    "err.bad_limits": "--max-line-chars и --max-duration не могут быть отрицательными, --max-lines должен быть не меньше 1.",
    "err.bad_translate_to": "Язык перевода '{lang}' не поддерживается. Доступны: {langs}.",
    "err.task_and_mt": "--task translate и --translate-to нельзя использовать вместе: выберите что-то одно.",
    "err.bad_stream": "--audio-stream должен быть 'auto' или неотрицательным индексом.",
    "err.bad_stream_int": "--audio-stream должен быть 'auto' или целым индексом, например 2.",
    "err.ffmpeg_read": "FFmpeg не смог прочитать файл: {detail}",
    "err.ffmpeg_extract": "Ошибка извлечения аудио через FFmpeg: {detail}",
    "err.no_audio": "В файле не найдено ни одной аудиодорожки.",
    "err.stream_not_found": "Аудиопоток с глобальным индексом {requested} не найден. Доступные индексы аудиопотоков: {available}. Используйте --list-streams.",
    "err.unknown_model": "Неизвестная модель: {name}",
    "err.path_missing": "Путь не существует: {path}",
    "err.bad_extension": "Расширение {ext} не входит в список поддерживаемых.",
    "err.no_extension": "(без расширения)",
    "err.not_file_or_dir": "Это не файл и не папка: {path}",
    "err.list_streams_single": "--list-streams работает только с одним медиафайлом.",
    "err.no_files": "В указанном месте не найдено поддерживаемых медиафайлов.",
    "err.model_load": "Не удалось загрузить модель: {error}",
    "err.file_failed": "Не удалось обработать '{path}': {error}",
    "err.mt_incomplete": "Модель перевода скачана не полностью ({repo}): нет файла словаря.",
    "err.mt_not_configured": "Для вариантов 'translated' и 'bilingual' нужен язык перевода (--translate-to).",
    "err.mt_unsupported_source": "Язык речи '{lang}' не поддерживается переводчиком.",
    "err.mt_unsupported_target": "Язык перевода '{lang}' не поддерживается переводчиком.",

    "stream.channels": "{n} кан.",
    "stream.default": " (по умолчанию)",
    "stream.unspecified": "не указан",
    "stream.unknown": "неизвестно",

    "log.file": "Файл: {path}",
    "log.no_audio_streams": "Аудиопотоки не найдены.",
    "log.stream_title": ", название: {title}",
    "log.stream_line": "Аудиодорожка {position}: индекс FFmpeg={index}, язык={language}, кодек={codec}, каналов={channels}, Hz={rate}{title}{default}",
    "log.saved": "Сохранено ({fmt}): {path}",
    "log.compute_supported": "Поддерживаемые compute_type на CUDA: {supported}",
    "log.compute_chosen": "Выбран compute_type: {name}",
    "log.compute_none": "Ни один из предпочтительных типов не найден, использую float32.",
    "log.compute_error": "Не удалось получить список поддерживаемых compute_type ({error}). Использую int8.",
    "log.size_unknown": "Не удалось узнать размер модели ({error}). Прогресс будет приблизительным.",
    "log.downloading": "Скачиваю модель '{name}' ({repo})…",
    "log.downloaded": "Модель '{name}' скачана.",
    "log.duration": "Длительность аудио: {seconds:.1f} сек (определён язык: {language})",
    "log.source": "Источник: {name} | аудиопоток {index} | язык дорожки: {language} | кодек: {codec}",
    "log.transcribing": "Начинаю распознавание: {name}",
    "log.cuda_fallback": "Ошибка CUDA ({error}). Переключаюсь на CPU и повторяю распознавание.",
    "log.segments": "Распознано сегментов: {count}",
    "log.cues": "Реплик субтитров: {count}",
    "log.found_files": "Найдено файлов: {count}",
    "log.download_progress": "Загрузка модели: {percent}% ({done:.0f} из {total:.0f} МБ)",
    "log.download_progress_mt": "Загрузка модели перевода: {percent}% ({done:.0f} из {total:.0f} МБ)",
    "log.loading_model": "Загружаю faster-whisper модель '{name}' на устройстве {device} (compute_type={compute})...",
    "log.model_loaded": "Модель загружена.",
    "log.skip_existing": "Пропускаю, результаты уже существуют (добавьте --overwrite для перезаписи): {paths}",
    "log.interrupted": "Прервано пользователем.",
    "log.summary": "Готово. Успешно: {ok} | пропущено: {skipped} | ошибок: {failed}",
    "log.failed_header": "Файлы с ошибками:",
    "log.mt_license": "Машинный перевод: модель NLLB-200 распространяется по лицензии CC-BY-NC-4.0 (только некоммерческое использование).",
    "log.mt_loading": "Загружаю модель перевода NLLB-200…",
    "log.mt_ready": "Модель перевода готова.",
    "log.mt_start": "Перевод субтитров: {source} → {target}, реплик: {count}",
    "log.mt_done": "Перевод завершён.",
    "log.mt_same_language": "Язык речи совпадает с языком перевода ({lang}): перевод не нужен, использую исходный текст.",
    "log.mt_cuda_fallback": "Ошибка CUDA в переводчике ({error}). Перевод продолжится на CPU.",

    "help.description": "Распознаёт речь в аудио/видео, сохраняет субтитры (SRT, VTT, TXT, JSON, ASS) и умеет переводить их машинным переводом.",
    "help.input": "Путь к медиафайлу или папке с файлами.",
    "help.output_dir": "Папка для результатов. Если не указана, файлы сохраняются рядом с исходниками.",
    "help.recursive": "Искать медиафайлы в подпапках (для входной папки).",
    "help.model": "Модель Whisper (по умолчанию: small).",
    "help.model_dir": "Папка, куда скачиваются модели и где они ищутся. По умолчанию кэш Hugging Face.",
    "help.language": "Язык речи: ru, en, de и т. п.; auto включает автоопределение.",
    "help.task": "transcribe = текст на исходном языке; translate = перевод на английский средствами Whisper.",
    "help.translate_to": "Машинный перевод субтитров (NLLB-200) на указанный язык. Доступны: {langs}.",
    "help.variants": "Что сохранять при переводе: original, translated, bilingual через запятую (по умолчанию: original,translated).",
    "help.formats": "Форматы вывода через запятую: srt, vtt, txt, json, ass (по умолчанию: srt).",
    "help.max_line_chars": "Максимум символов в строке субтитров. 0 = не разбивать (как выдаёт модель).",
    "help.max_lines": "Максимум строк в одной реплике при разбиении (по умолчанию 2).",
    "help.max_duration": "Максимальная длительность реплики в секундах. 0 = без ограничения.",
    "help.device": "Вычислительное устройство. auto использует CUDA, если она доступна.",
    "help.audio_stream": "Глобальный индекс аудиопотока FFmpeg (например, 2) или auto.",
    "help.temp_dir": "Папка для временных WAV-файлов.",
    "help.overwrite": "Перезаписывать уже существующие файлы результатов.",
    "help.beam_size": "Ширина beam search (по умолчанию 5). Для turbo автоматически используется 1.",
    "help.vad": "Включить VAD-фильтр (пропуск тишины). Включён по умолчанию.",
    "help.no_vad": "Отключить VAD-фильтр.",
    "help.quiet": "Не выводить подробный прогресс.",
    "help.list_streams": "Показать потоки одного медиафайла и завершить работу.",
    "help.log_level": "Уровень сообщений журнала.",
    "help.lang": "Язык сообщений и справки: auto (по системе), ru или en.",
})
EN.update({
    "err.unknown_format": "Unknown format '{fmt}'. Available: {available}.",
    "err.no_format": "No output format selected.",
    "err.unknown_variant": "Unknown variant '{name}'. Available: {available}.",
    "err.no_variant": "No result variant selected.",
    "err.no_input": "no input file or folder given.",
    "err.bad_limits": "--max-line-chars and --max-duration cannot be negative, --max-lines must be at least 1.",
    "err.bad_translate_to": "Translation language '{lang}' is not supported. Available: {langs}.",
    "err.task_and_mt": "--task translate and --translate-to cannot be used together: pick one.",
    "err.bad_stream": "--audio-stream must be 'auto' or a non-negative index.",
    "err.bad_stream_int": "--audio-stream must be 'auto' or an integer index, for example 2.",
    "err.ffmpeg_read": "FFmpeg could not read the file: {detail}",
    "err.ffmpeg_extract": "Audio extraction with FFmpeg failed: {detail}",
    "err.no_audio": "The file has no audio tracks.",
    "err.stream_not_found": "Audio stream with global index {requested} was not found. Available audio stream indexes: {available}. Use --list-streams.",
    "err.unknown_model": "Unknown model: {name}",
    "err.path_missing": "Path does not exist: {path}",
    "err.bad_extension": "The extension {ext} is not in the list of supported ones.",
    "err.no_extension": "(no extension)",
    "err.not_file_or_dir": "Not a file or a folder: {path}",
    "err.list_streams_single": "--list-streams works with a single media file only.",
    "err.no_files": "No supported media files found at the given location.",
    "err.model_load": "Could not load the model: {error}",
    "err.file_failed": "Could not process '{path}': {error}",
    "err.mt_incomplete": "The translation model is incomplete ({repo}): vocabulary file is missing.",
    "err.mt_not_configured": "The 'translated' and 'bilingual' variants need a translation language (--translate-to).",
    "err.mt_unsupported_source": "The speech language '{lang}' is not supported by the translator.",
    "err.mt_unsupported_target": "The translation language '{lang}' is not supported by the translator.",

    "stream.channels": "{n} ch.",
    "stream.default": " (default)",
    "stream.unspecified": "not set",
    "stream.unknown": "unknown",

    "log.file": "File: {path}",
    "log.no_audio_streams": "No audio streams found.",
    "log.stream_title": ", title: {title}",
    "log.stream_line": "Audio track {position}: FFmpeg index={index}, language={language}, codec={codec}, channels={channels}, Hz={rate}{title}{default}",
    "log.saved": "Saved ({fmt}): {path}",
    "log.compute_supported": "Supported compute types on CUDA: {supported}",
    "log.compute_chosen": "Selected compute_type: {name}",
    "log.compute_none": "None of the preferred types found, using float32.",
    "log.compute_error": "Could not get the list of supported compute types ({error}). Using int8.",
    "log.size_unknown": "Could not get the model size ({error}). Progress will be approximate.",
    "log.downloading": "Downloading model '{name}' ({repo})…",
    "log.downloaded": "Model '{name}' downloaded.",
    "log.duration": "Audio duration: {seconds:.1f} s (detected language: {language})",
    "log.source": "Source: {name} | audio stream {index} | track language: {language} | codec: {codec}",
    "log.transcribing": "Starting transcription: {name}",
    "log.cuda_fallback": "CUDA error ({error}). Switching to CPU and retrying the transcription.",
    "log.segments": "Segments recognized: {count}",
    "log.cues": "Subtitle cues: {count}",
    "log.found_files": "Files found: {count}",
    "log.download_progress": "Downloading model: {percent}% ({done:.0f} of {total:.0f} MB)",
    "log.download_progress_mt": "Downloading translation model: {percent}% ({done:.0f} of {total:.0f} MB)",
    "log.loading_model": "Loading faster-whisper model '{name}' on device {device} (compute_type={compute})...",
    "log.model_loaded": "Model loaded.",
    "log.skip_existing": "Skipping, results already exist (add --overwrite to replace them): {paths}",
    "log.interrupted": "Interrupted by the user.",
    "log.summary": "Done. Succeeded: {ok} | skipped: {skipped} | failed: {failed}",
    "log.failed_header": "Files with errors:",
    "log.mt_license": "Machine translation: the NLLB-200 model is distributed under CC-BY-NC-4.0 (non-commercial use only).",
    "log.mt_loading": "Loading the NLLB-200 translation model…",
    "log.mt_ready": "Translation model is ready.",
    "log.mt_start": "Translating subtitles: {source} → {target}, cues: {count}",
    "log.mt_done": "Translation finished.",
    "log.mt_same_language": "The speech language equals the target language ({lang}): no translation needed, using the original text.",
    "log.mt_cuda_fallback": "CUDA error in the translator ({error}). Translation will continue on CPU.",

    "help.description": "Transcribes speech from audio/video, saves subtitles (SRT, VTT, TXT, JSON, ASS) and can machine-translate them.",
    "help.input": "Path to a media file or a folder with files.",
    "help.output_dir": "Output folder. If omitted, files are saved next to the sources.",
    "help.recursive": "Look for media files in subfolders (for an input folder).",
    "help.model": "Whisper model (default: small).",
    "help.model_dir": "Folder where models are downloaded and looked up. Defaults to the Hugging Face cache.",
    "help.language": "Speech language: ru, en, de, etc.; auto enables detection.",
    "help.task": "transcribe = text in the original language; translate = translation to English done by Whisper.",
    "help.translate_to": "Machine-translate the subtitles (NLLB-200) into this language. Available: {langs}.",
    "help.variants": "What to save when translating: original, translated, bilingual, comma-separated (default: original,translated).",
    "help.formats": "Output formats, comma-separated: srt, vtt, txt, json, ass (default: srt).",
    "help.max_line_chars": "Maximum characters per subtitle line. 0 = do not split (as the model returns).",
    "help.max_lines": "Maximum lines per cue when splitting (default 2).",
    "help.max_duration": "Maximum cue duration in seconds. 0 = unlimited.",
    "help.device": "Compute device. auto uses CUDA if available.",
    "help.audio_stream": "Global FFmpeg audio stream index (for example 2) or auto.",
    "help.temp_dir": "Folder for temporary WAV files.",
    "help.overwrite": "Overwrite existing result files.",
    "help.beam_size": "Beam search width (default 5). turbo automatically uses 1.",
    "help.vad": "Enable the VAD filter (skips silence). On by default.",
    "help.no_vad": "Disable the VAD filter.",
    "help.quiet": "Do not print detailed progress.",
    "help.list_streams": "Show the streams of one media file and exit.",
    "help.log_level": "Log verbosity.",
    "help.lang": "Language of messages and help: auto (follow the system), ru or en.",
})

# ======================================================================================
# Graphical interface
# ======================================================================================
_NATIVE = {
    "ru": "Русский", "en": "English", "de": "Deutsch", "uk": "Українська", "fr": "Français", "es": "Español",
    "it": "Italiano", "pl": "Polski", "pt": "Português", "tr": "Türkçe", "nl": "Nederlands", "cs": "Čeština",
    "ja": "日本語", "zh": "中文", "ko": "한국어", "ar": "العربية", "hi": "हिन्दी", "vi": "Tiếng Việt",
}
_NAMES_RU = {
    "ru": "Русский", "en": "Английский", "de": "Немецкий", "uk": "Украинский", "fr": "Французский",
    "es": "Испанский", "it": "Итальянский", "pl": "Польский", "pt": "Португальский", "tr": "Турецкий",
    "nl": "Нидерландский", "cs": "Чешский", "ja": "Японский", "zh": "Китайский", "ko": "Корейский",
    "ar": "Арабский", "hi": "Хинди", "vi": "Вьетнамский",
}
_NAMES_EN = {
    "ru": "Russian", "en": "English", "de": "German", "uk": "Ukrainian", "fr": "French", "es": "Spanish",
    "it": "Italian", "pl": "Polish", "pt": "Portuguese", "tr": "Turkish", "nl": "Dutch", "cs": "Czech",
    "ja": "Japanese", "zh": "Chinese", "ko": "Korean", "ar": "Arabic", "hi": "Hindi", "vi": "Vietnamese",
}
for _code, _native in _NATIVE.items():
    RU[f"lang.{_code}"] = _NAMES_RU[_code] if _NAMES_RU[_code] == _native else f"{_NAMES_RU[_code]} · {_native}"
    EN[f"lang.{_code}"] = _NAMES_EN[_code] if _NAMES_EN[_code] == _native else f"{_NAMES_EN[_code]} · {_native}"

RU.update({
    "lang.auto": "Автоопределение",
    "ui.title": "Whisper SRT — субтитры",
    "ui.subtitle": "v{version} · локальное распознавание речи на faster-whisper",
    "ui.theme": "Тема",
    "ui.theme_light": "Светлая тема",
    "ui.theme_dark": "Тёмная тема",
    "ui.files": "Файлы",
    "ui.add_files": "Добавить файлы…",
    "ui.add_folder": "Добавить папку…",
    "ui.remove_selected": "Убрать выбранные",
    "ui.clear_list": "Очистить список",
    "ui.drop_hint": "Файлы можно перетащить в список.",
    "ui.col.file": "Файл",
    "ui.col.duration": "Длительность",
    "ui.col.track": "Аудиодорожка",
    "ui.col.status": "Состояние",
    "ui.track.of_selected": "Аудиодорожка выбранного файла:",
    "ui.track.auto_label": "Авто (как задано в файле)",
    "ui.track.auto_short": "Авто",
    "ui.track.none": "нет звука",
    "ui.recognition": "Распознавание",
    "ui.model": "Модель:",
    "ui.download": "Скачать",
    "ui.model.checking": "Проверяю наличие модели…",
    "ui.model.cached": "Скачана, интернет не нужен.",
    "ui.model.missing": "Не скачана: загрузится при запуске.",
    "ui.speech_language": "Язык речи:",
    "ui.result": "Результат:",
    "ui.mode.transcribe": "Субтитры на языке речи",
    "ui.mode.translate": "Перевод на английский (Whisper)",
    "ui.mode.mt": "Машинный перевод субтитров",
    "ui.translate_to": "Перевести на:",
    "ui.mt.hint": "Машинный перевод — режим «Результат» выше.",
    "ui.mt.checking": "Проверяю модель перевода…",
    "ui.mt.cached": "Модель перевода NLLB-200 скачана. Лицензия весов: CC-BY-NC (только некоммерческое использование).",
    "ui.mt.missing": "Модель NLLB-200 (~620 МБ) скачается при первом запуске. Лицензия весов: CC-BY-NC (только некоммерческое использование).",
    "ui.device": "Устройство:",
    "ui.device.auto": "Автоматически",
    "ui.device.cpu": "CPU",
    "ui.model_dir": "Папка моделей:",
    "ui.model_dir_hint": "Пусто: стандартный кэш Hugging Face.",
    "ui.subtitles_and_saving": "Субтитры и сохранение",
    "ui.formats": "Форматы:",
    "ui.variants": "Сохранять:",
    "ui.variant.original": "Оригинал",
    "ui.variant.translated": "Перевод",
    "ui.variant.bilingual": "Двуязычные",
    "ui.split": "Разбивать на короткие реплики",
    "ui.chars_per_line": "Символов в строке",
    "ui.lines": "Строк",
    "ui.cue_seconds": "Длительность, с",
    "ui.split_hint": "При разбиении модель размечает время по словам, это немного медленнее.",
    "ui.output_dir": "Папка для результатов:",
    "ui.choose": "Выбрать…",
    "ui.output_dir_hint": "Пусто: рядом с исходными файлами.",
    "ui.overwrite": "Перезаписывать существующие файлы",
    "ui.notify": "Уведомить о завершении",
    "ui.start": "Создать субтитры",
    "ui.stop_after": "Остановить после текущего файла",
    "ui.cancel_now": "Отменить сейчас",
    "ui.open_folder": "Открыть папку",
    "ui.progress.file": "Файл:",
    "ui.progress.total": "Всего:",
    "ui.log": "Журнал работы",

    "ui.eta.sec": "{s} с",
    "ui.eta.min": "{m} мин {s:02} с",
    "ui.eta.hour": "{h} ч {m:02} мин",
    "ui.eta.left": "осталось ~{eta}",

    "ui.st.queued": "В очереди",
    "ui.st.reading": "Чтение файла…",
    "ui.st.ready": "Готов к работе",
    "ui.st.unreadable": "Не читается",
    "ui.st.no_audio": "Нет звука",
    "ui.st.transcribing": "Распознавание {percent:.0f}%",
    "ui.st.translating": "Перевод {percent:.0f}%",
    "ui.st.done": "Готово",
    "ui.st.error": "Ошибка",
    "ui.st.skipped": "Пропущен (уже есть)",
    "ui.st.not_processed": "Не обработан",
    "ui.st.cancelled": "Отменён",

    "ui.stat.add_files": "Добавьте аудио- или видеофайлы.",
    "ui.stat.count": "Файлов в списке: {count}.",
    "ui.stat.preparing": "Подготовка…",
    "ui.stat.checking_model": "Проверяю модель {name}…",
    "ui.stat.loading_model": "Загрузка модели {name} в память…",
    "ui.stat.processing": "Обработка {number}/{total}: {name}",
    "ui.stat.stopping": "Остановка после текущего файла…",
    "ui.stat.cancelling": "Отмена…",
    "ui.stat.stopped": "Остановлено пользователем.",
    "ui.stat.cancelled": "Отменено.",
    "ui.stat.done": "Готово: создано {ok}, пропущено {skipped}.",
    "ui.stat.done_errors": "Завершено с ошибками ({count}). См. журнал.",
    "ui.stat.fatal": "Ошибка при выполнении. См. журнал.",
    "ui.stat.downloading": "Скачивание модели {name}…",
    "ui.stat.downloaded": "Модель {name} скачана.",
    "ui.stat.download_failed": "Не удалось скачать модель. Проверьте интернет и см. журнал.",
    "ui.stat.dl_progress": "Скачивание {name}: {done:.0f} из {total:.0f} МБ",
    "ui.stat.dl_unknown": "Скачивание {name}: {done:.0f} МБ",

    "ui.notify.done": "Готово: создано {ok}, пропущено {skipped}.",
    "ui.notify.done_errors": "Завершено с ошибками: {failed}. Создано {ok}, пропущено {skipped}.",

    "ui.dlg.choose_media": "Выберите медиафайлы",
    "ui.dlg.supported_media": "Поддерживаемые медиафайлы",
    "ui.dlg.all_files": "Все файлы",
    "ui.dlg.media_folder": "Папка с медиафайлами",
    "ui.dlg.output_folder": "Папка для готовых субтитров",
    "ui.dlg.model_folder": "Папка для моделей",

    "ui.msg.add_first": "Сначала добавьте хотя бы один аудио- или видеофайл.",
    "ui.msg.file_missing": "Не удалось найти файл:",
    "ui.msg.pick_format": "Выберите хотя бы один формат субтитров.",
    "ui.msg.pick_variant": "Отметьте, что сохранять: оригинал, перевод или двуязычные субтитры.",
    "ui.msg.bad_split": "Проверьте параметры разбиения: символов в строке от 10 до 80, строк от 1 до 3, длительность реплики от 1 до 30 секунд.",
    "ui.msg.output_dir_failed": "Не удалось создать папку для результатов:\n{error}",
    "ui.msg.model_dir_failed": "Не удалось создать папку для моделей:\n{error}",
    "ui.msg.no_folder": "Папка пока не определена: добавьте файлы или выберите папку для результатов.",
    "ui.msg.open_failed": "Не удалось открыть папку:\n{error}",
    "ui.msg.confirm_exit": "Обработка ещё выполняется. Прервать её и выйти?",

    "ui.log.folder_empty": "В папке нет поддерживаемых файлов: {path}",
    "ui.log.folder_added": "Из папки {name} добавлено файлов: {count} (без вложенных папок).",
    "ui.log.read_failed": "Не удалось прочитать {name}: {error}",
    "ui.log.device": "Устройство: {device}, compute_type: {compute}.",
    "ui.log.model_ready": "Модель '{name}' готова к работе.",
    "ui.log.skip_existing": "Пропуск: все файлы результатов уже существуют.",
    "ui.log.file_error": "ОШИБКА: {name}: {error}",
    "ui.log.download_error": "ОШИБКА загрузки модели: {error}",
    "ui.log.fatal": "КРИТИЧЕСКАЯ ОШИБКА: {error}",
    "ui.log.summary": "Готово. Успешно: {ok}; пропущено: {skipped}; ошибок: {failed}.",
    "ui.log.stop_requested": "Запрошена остановка. Текущий файл будет завершён.",
    "ui.log.cancel_requested": "Запрошена отмена. Текущий файл прерывается, частичный результат не сохраняется.",
    "ui.log.cancelled_file": "Отменено: {name}. Файлы результатов для него не созданы.",
    "ui.log.cancelled": "Работа отменена.",
})
EN.update({
    "lang.auto": "Auto-detect",
    "ui.title": "Whisper SRT — subtitles",
    "ui.subtitle": "v{version} · local speech recognition on faster-whisper",
    "ui.theme": "Theme",
    "ui.theme_light": "Light theme",
    "ui.theme_dark": "Dark theme",
    "ui.files": "Files",
    "ui.add_files": "Add files…",
    "ui.add_folder": "Add folder…",
    "ui.remove_selected": "Remove selected",
    "ui.clear_list": "Clear list",
    "ui.drop_hint": "You can drag files into the list.",
    "ui.col.file": "File",
    "ui.col.duration": "Duration",
    "ui.col.track": "Audio track",
    "ui.col.status": "Status",
    "ui.track.of_selected": "Audio track of the selected file:",
    "ui.track.auto_label": "Auto (as set in the file)",
    "ui.track.auto_short": "Auto",
    "ui.track.none": "no audio",
    "ui.recognition": "Recognition",
    "ui.model": "Model:",
    "ui.download": "Download",
    "ui.model.checking": "Checking the model…",
    "ui.model.cached": "Downloaded, no internet needed.",
    "ui.model.missing": "Not downloaded: will be fetched on start.",
    "ui.speech_language": "Speech language:",
    "ui.result": "Result:",
    "ui.mode.transcribe": "Subtitles in the spoken language",
    "ui.mode.translate": "Translate to English (Whisper)",
    "ui.mode.mt": "Machine-translate subtitles",
    "ui.translate_to": "Translate to:",
    "ui.mt.hint": "Machine translation: pick it in “Result” above.",
    "ui.mt.checking": "Checking the translation model…",
    "ui.mt.cached": "NLLB-200 translation model is downloaded. Weights license: CC-BY-NC (non-commercial use only).",
    "ui.mt.missing": "The NLLB-200 model (~620 MB) will be downloaded on first run. Weights license: CC-BY-NC (non-commercial use only).",
    "ui.device": "Device:",
    "ui.device.auto": "Automatic",
    "ui.device.cpu": "CPU",
    "ui.model_dir": "Models folder:",
    "ui.model_dir_hint": "Empty: the standard Hugging Face cache.",
    "ui.subtitles_and_saving": "Subtitles and saving",
    "ui.formats": "Formats:",
    "ui.variants": "Save:",
    "ui.variant.original": "Original",
    "ui.variant.translated": "Translation",
    "ui.variant.bilingual": "Bilingual",
    "ui.split": "Split into short cues",
    "ui.chars_per_line": "Characters per line",
    "ui.lines": "Lines",
    "ui.cue_seconds": "Duration, s",
    "ui.split_hint": "When splitting, the model also marks time per word, which is a little slower.",
    "ui.output_dir": "Output folder:",
    "ui.choose": "Browse…",
    "ui.output_dir_hint": "Empty: next to the source files.",
    "ui.overwrite": "Overwrite existing files",
    "ui.notify": "Notify when finished",
    "ui.start": "Create subtitles",
    "ui.stop_after": "Stop after the current file",
    "ui.cancel_now": "Cancel now",
    "ui.open_folder": "Open folder",
    "ui.progress.file": "File:",
    "ui.progress.total": "Total:",
    "ui.log": "Activity log",

    "ui.eta.sec": "{s} s",
    "ui.eta.min": "{m} min {s:02} s",
    "ui.eta.hour": "{h} h {m:02} min",
    "ui.eta.left": "~{eta} left",

    "ui.st.queued": "Queued",
    "ui.st.reading": "Reading file…",
    "ui.st.ready": "Ready",
    "ui.st.unreadable": "Cannot read",
    "ui.st.no_audio": "No audio",
    "ui.st.transcribing": "Transcribing {percent:.0f}%",
    "ui.st.translating": "Translating {percent:.0f}%",
    "ui.st.done": "Done",
    "ui.st.error": "Error",
    "ui.st.skipped": "Skipped (already exists)",
    "ui.st.not_processed": "Not processed",
    "ui.st.cancelled": "Cancelled",

    "ui.stat.add_files": "Add audio or video files.",
    "ui.stat.count": "Files in the list: {count}.",
    "ui.stat.preparing": "Preparing…",
    "ui.stat.checking_model": "Checking model {name}…",
    "ui.stat.loading_model": "Loading model {name} into memory…",
    "ui.stat.processing": "Processing {number}/{total}: {name}",
    "ui.stat.stopping": "Stopping after the current file…",
    "ui.stat.cancelling": "Cancelling…",
    "ui.stat.stopped": "Stopped by the user.",
    "ui.stat.cancelled": "Cancelled.",
    "ui.stat.done": "Done: created {ok}, skipped {skipped}.",
    "ui.stat.done_errors": "Finished with errors ({count}). See the log.",
    "ui.stat.fatal": "An error occurred. See the log.",
    "ui.stat.downloading": "Downloading model {name}…",
    "ui.stat.downloaded": "Model {name} downloaded.",
    "ui.stat.download_failed": "Could not download the model. Check your internet connection and the log.",
    "ui.stat.dl_progress": "Downloading {name}: {done:.0f} of {total:.0f} MB",
    "ui.stat.dl_unknown": "Downloading {name}: {done:.0f} MB",

    "ui.notify.done": "Done: created {ok}, skipped {skipped}.",
    "ui.notify.done_errors": "Finished with errors: {failed}. Created {ok}, skipped {skipped}.",

    "ui.dlg.choose_media": "Choose media files",
    "ui.dlg.supported_media": "Supported media files",
    "ui.dlg.all_files": "All files",
    "ui.dlg.media_folder": "Folder with media files",
    "ui.dlg.output_folder": "Folder for the finished subtitles",
    "ui.dlg.model_folder": "Folder for models",

    "ui.msg.add_first": "Add at least one audio or video file first.",
    "ui.msg.file_missing": "Could not find the file:",
    "ui.msg.pick_format": "Select at least one subtitle format.",
    "ui.msg.pick_variant": "Tick what to save: the original, the translation or bilingual subtitles.",
    "ui.msg.bad_split": "Check the splitting settings: 10 to 80 characters per line, 1 to 3 lines, cue duration 1 to 30 seconds.",
    "ui.msg.output_dir_failed": "Could not create the output folder:\n{error}",
    "ui.msg.model_dir_failed": "Could not create the models folder:\n{error}",
    "ui.msg.no_folder": "No folder yet: add files or choose an output folder.",
    "ui.msg.open_failed": "Could not open the folder:\n{error}",
    "ui.msg.confirm_exit": "Processing is still running. Cancel it and exit?",

    "ui.log.folder_empty": "No supported files in the folder: {path}",
    "ui.log.folder_added": "Files added from folder {name}: {count} (subfolders are not included).",
    "ui.log.read_failed": "Could not read {name}: {error}",
    "ui.log.device": "Device: {device}, compute_type: {compute}.",
    "ui.log.model_ready": "Model '{name}' is ready.",
    "ui.log.skip_existing": "Skipped: all result files already exist.",
    "ui.log.file_error": "ERROR: {name}: {error}",
    "ui.log.download_error": "MODEL DOWNLOAD ERROR: {error}",
    "ui.log.fatal": "CRITICAL ERROR: {error}",
    "ui.log.summary": "Done. Succeeded: {ok}; skipped: {skipped}; failed: {failed}.",
    "ui.log.stop_requested": "Stop requested. The current file will be finished.",
    "ui.log.cancel_requested": "Cancel requested. The current file is being interrupted; no partial result is saved.",
    "ui.log.cancelled_file": "Cancelled: {name}. No result files were created for it.",
    "ui.log.cancelled": "Work cancelled.",
})


def check_parity() -> list[str]:
    """Problems in the translation tables: keys present in one language only, or different placeholders."""
    import re
    problems: list[str] = []
    for key in sorted(set(RU) ^ set(EN)):
        problems.append(f"{key}: only in {'ru' if key in RU else 'en'}")
    placeholder = re.compile(r"\{(\w+)")
    for key in sorted(set(RU) & set(EN)):
        if set(placeholder.findall(RU[key])) != set(placeholder.findall(EN[key])):
            problems.append(f"{key}: placeholders differ")
    return problems
