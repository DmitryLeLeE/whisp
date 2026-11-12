# WhisperSRT — субтитры из аудио и видео

[![Release](https://img.shields.io/github/v/release/DmitryLeLeE/whisp?label=release)](https://github.com/DmitryLeLeE/whisp/releases/latest)
[![Build](https://github.com/DmitryLeLeE/whisp/actions/workflows/release.yml/badge.svg)](https://github.com/DmitryLeLeE/whisp/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6)

Программа для Windows, которая создаёт субтитры `.srt` из аудио- и видеофайлов. Распознавание идёт локально на движке [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2), файлы никуда не отправляются. Есть окно с настройками и консольная утилита.

## Возможности

- Работает до 4 раз быстрее оригинального OpenAI Whisper, на CPU и на видеокарте NVIDIA.
- Читает любые форматы, которые понимает FFmpeg: `.mp4`, `.mkv`, `.ts`, `.avi`, `.mov`, `.mp3`, `.wav`, `.flac`, `.m4a` и другие.
- Пропускает тишину и паузы через VAD-фильтр, поэтому в субтитрах меньше ложных фраз.
- Позволяет выбрать аудиодорожку, если в видео их несколько (например, оригинал и дубляж).
- Обрабатывает сразу несколько файлов и показывает прогресс.
- Сам подбирает тип вычислений для CPU или CUDA.

## Скачать готовую программу

1. Откройте раздел [Releases](https://github.com/DmitryLeLeE/whisp/releases/latest) и скачайте `WhisperSRT-Windows.zip`.
2. Распакуйте архив в любую папку.
3. Запустите `WhisperSRT\WhisperSRT.exe`. Python и FFmpeg устанавливать не нужно.

При первом запуске выбранная модель скачивается с Hugging Face и сохраняется в кэш. Дальше программа работает без интернета.

## Как пользоваться окном программы

1. Нажмите «Выбрать файл(ы)…» и укажите один или несколько файлов.
2. Выберите модель и язык речи. Для скорости подойдут `small` и `turbo`, для точности `medium` и `large-v3`.
3. При необходимости укажите индекс аудиопотока (по умолчанию `auto`) и папку для результатов.
4. Нажмите «Создать субтитры».

Готовые файлы называются `имя_файла.whisper.srt` и по умолчанию лежат рядом с исходниками. Если файл с таким именем уже есть, он пропускается, пока не включена опция «Перезаписывать существующие SRT».

## Консольная утилита

```bash
# Один файл
python whisper_universal.py "video.mp4" --model turbo --language ru

# Вся папка, включая вложенные, результаты в отдельную папку
python whisper_universal.py "D:\Videos" --recursive --output-dir "D:\Subs"

# Показать аудиодорожки файла, затем выбрать нужную
python whisper_universal.py "movie.mkv" --list-streams
python whisper_universal.py "movie.mkv" --audio-stream 2
```

| Параметр | Что делает |
|---|---|
| `-m`, `--model` | `tiny`, `base`, `small` (по умолчанию), `medium`, `large-v3`, `turbo` |
| `-l`, `--language` | Код языка (`ru`, `en`, `de`…) или `auto` для автоопределения |
| `--task` | `transcribe` — текст на языке оригинала, `translate` — перевод на английский |
| `--device` | `auto` (по умолчанию), `cpu`, `cuda` |
| `--audio-stream` | Глобальный индекс аудиопотока FFmpeg или `auto` |
| `-o`, `--output-dir` | Папка для SRT |
| `-r`, `--recursive` | Искать файлы во вложенных папках |
| `--overwrite` | Перезаписывать существующие SRT |
| `--no-vad` | Отключить VAD-фильтр |
| `--beam-size` | Ширина beam search (для `turbo` всегда 1) |
| `--list-streams` | Показать потоки файла и выйти |

Полный список: `python whisper_universal.py --help`.

## Видеокарта NVIDIA

Для работы на GPU нужны драйвер NVIDIA, CUDA 12 (cuBLAS) и cuDNN 9. В готовый архив они не входят. Если в режиме «Автоматически» появляется ошибка про `cublas64_12.dll` или `cudnn`, выберите в программе устройство «CPU» или установите нужные библиотеки.

## Запуск из исходного кода

Нужен Python 3.9–3.12.

```bash
git clone https://github.com/DmitryLeLeE/whisp.git
cd whisp

python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Скачайте сборку FFmpeg для Windows (например, с [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) или [BtbN](https://github.com/BtbN/FFmpeg-Builds/releases)) и положите `ffmpeg.exe` и `ffprobe.exe` в папку `ffmpeg_bin/` в корне проекта. Если FFmpeg уже есть в `PATH`, этот шаг можно пропустить.

```bash
# Окно программы
python WhisperSRT_GUI.py

# Консольная утилита
python whisper_universal.py "video.mp4" --model turbo --language ru
```

## Сборка своего `.exe`

```cmd
pip install -r requirements-build.txt
build.bat
```

Результат появится в папке `dist\WhisperSRT\`. Для переноса на другой компьютер скопируйте её целиком.

## Выпуск релиза

Релиз собирается автоматически в GitHub Actions по тегу:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Workflow [`release.yml`](.github/workflows/release.yml) скачает FFmpeg, соберёт приложение, упакует `WhisperSRT-Windows.zip` и прикрепит его к новому релизу. Запустить сборку без тега можно вручную на вкладке Actions: архив появится в артефактах запуска.

## Лицензия

[MIT](LICENSE). FFmpeg и модели Whisper распространяются под собственными лицензиями.
