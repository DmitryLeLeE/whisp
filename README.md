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
- Обрабатывает очередь файлов: у каждого видны длительность, дорожка и состояние, общий прогресс и оставшееся время.
- Сохраняет SRT, VTT, TXT, JSON и ASS, можно несколько форматов сразу.
- Разбивает длинные реплики по числу символов в строке и длительности.
- Переводит речь на английский.
- Скачивает модели с индикатором загрузки, папку для моделей можно выбрать.
- Тёмная и светлая темы, настройки запоминаются.
- Сам подбирает тип вычислений для CPU или CUDA.

## Скачать готовую программу

1. Откройте раздел [Releases](https://github.com/DmitryLeLeE/whisp/releases/latest) и скачайте `WhisperSRT-Windows.zip`.
2. Распакуйте архив в любую папку.
3. Запустите `WhisperSRT\WhisperSRT.exe`. Python и FFmpeg устанавливать не нужно.

При первом запуске выбранная модель скачивается с Hugging Face и сохраняется в кэш. Дальше программа работает без интернета.

## Как пользоваться окном программы

1. Добавьте файлы кнопками «Добавить файлы…» и «Добавить папку…» или перетащите их в список.
2. Если в видео несколько звуковых дорожек, выберите файл в списке и укажите нужную дорожку под списком. По умолчанию берётся дорожка, отмеченная в самом файле.
3. Выберите модель и язык речи. Для скорости подойдут `small` и `turbo`, для точности `medium` и `large-v3`. Рядом с моделью видно, скачана ли она. Кнопка «Скачать» загружает модель заранее.
4. Выберите результат: субтитры на языке речи или перевод на английский.
5. Отметьте нужные форматы. Если реплики получаются слишком длинными, включите «Разбивать на короткие реплики» и задайте число символов в строке, число строк и длительность реплики.
6. При необходимости укажите папку для результатов и нажмите «Создать субтитры».

Готовые файлы называются `имя_файла.whisper.srt`, `имя_файла.whisper.vtt` и так далее, по умолчанию лежат рядом с исходниками. Если все файлы результата уже есть, исходник пропускается, пока не включена опция «Перезаписывать существующие файлы». Кнопка «Остановить» завершает текущий файл и не берёт следующие.

Настройки сохраняются в `%APPDATA%\WhisperSRT\settings.json`. Модели по умолчанию лежат в кэше Hugging Face (`%USERPROFILE%\.cache\huggingface\hub`).

## Консольная утилита

```bash
# Один файл
python whisper_universal.py "video.mp4" --model turbo --language ru

# Вся папка, включая вложенные, результаты в отдельную папку
python whisper_universal.py "D:\Videos" --recursive --output-dir "D:\Subs"

# Несколько форматов и короткие реплики (до 2 строк по 42 символа)
python whisper_universal.py "video.mp4" -f srt,vtt,txt --max-line-chars 42

# Показать аудиодорожки файла, затем выбрать нужную
python whisper_universal.py "movie.mkv" --list-streams
python whisper_universal.py "movie.mkv" --audio-stream 2
```

| Параметр | Что делает |
|---|---|
| `-m`, `--model` | `tiny`, `base`, `small` (по умолчанию), `medium`, `large-v3`, `turbo` |
| `-l`, `--language` | Код языка (`ru`, `en`, `de`…) или `auto` для автоопределения |
| `--task` | `transcribe` — текст на языке оригинала, `translate` — перевод на английский |
| `-f`, `--formats` | Форматы через запятую: `srt`, `vtt`, `txt`, `json`, `ass` (по умолчанию `srt`) |
| `--max-line-chars` | Максимум символов в строке, `0` — не разбивать реплики |
| `--max-lines` | Максимум строк в реплике при разбиении (по умолчанию 2) |
| `--max-duration` | Максимальная длительность реплики в секундах, `0` — без ограничения |
| `--model-dir` | Папка для скачанных моделей |
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

Для работы на GPU нужны драйвер NVIDIA, CUDA 12 (cuBLAS) и cuDNN 9. В готовый архив они не входят. Если в режиме «Автоматически» этих библиотек не оказалось, программа напишет об этом в журнале, переключится на CPU и повторит распознавание. Явно выбранный в консоли `--device cuda` на CPU не переключается и покажет ошибку.

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

Workflow [`release.yml`](.github/workflows/release.yml) скачает FFmpeg, соберёт приложение, проверит его запуском `WhisperSRT.exe --selftest`, упакует `WhisperSRT-Windows.zip` и прикрепит его к релизу. Если релиз с таким тегом уже создан вручную на GitHub, архив добавляется к нему. Запустить сборку без тега можно вручную на вкладке Actions: архив появится в артефактах запуска.

## Лицензия

[MIT](LICENSE). FFmpeg и модели Whisper распространяются под собственными лицензиями.
