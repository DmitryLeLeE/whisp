# WhisperSRT — subtitles from audio and video

[![Release](https://img.shields.io/github/v/release/DmitryLeLeE/whisp?label=release)](https://github.com/DmitryLeLeE/whisp/releases/latest)
[![Build](https://github.com/DmitryLeLeE/whisp/actions/workflows/release.yml/badge.svg)](https://github.com/DmitryLeLeE/whisp/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6)

[Русский](README.ru.md) · **English**

A Windows program that creates subtitles from audio and video files and can translate them into another language. Recognition and translation run locally ([faster-whisper](https://github.com/SYSTRAN/faster-whisper) and NLLB-200 on CTranslate2), nothing is uploaded anywhere. It has a window with settings (English and Russian) and a command-line tool.

## Features

- Up to 4× faster than the original OpenAI Whisper, on CPU and on NVIDIA GPUs.
- Reads everything FFmpeg understands: `.mp4`, `.mkv`, `.ts`, `.avi`, `.mov`, `.mp3`, `.wav`, `.flac`, `.m4a` and more.
- Skips silence with a VAD filter, so there are fewer false phrases in the subtitles.
- Lets you pick the audio track when a video has several (for example the original and a dub).
- Processes a queue of files: each shows its duration, track and status, plus overall progress and the time left.
- Saves SRT, VTT, TXT, JSON and ASS, several formats at once.
- Splits long cues by characters per line and cue duration.
- Translates speech to English with Whisper.
- **Machine translation of subtitles** into 18 languages (NLLB-200): translation only, the original, or bilingual subtitles (two lines per cue).
- Instant cancel, as well as stop after the current file.
- Plays a sound, flashes the taskbar button and shows a Windows notification when it is done.
- English and Russian interface, switchable on the fly.
- Downloads models with a progress bar; the models folder is configurable.
- Dark and light themes, settings are remembered.
- Picks the compute type for CPU or CUDA automatically.

## Download the ready-made program

1. Open [Releases](https://github.com/DmitryLeLeE/whisp/releases/latest) and download `WhisperSRT-Windows.zip`.
2. Unpack the archive into any folder.
3. Run `WhisperSRT\WhisperSRT.exe`. You do not need to install Python or FFmpeg.

On the first run the selected model is downloaded from Hugging Face and cached. After that the program works offline.

## Using the window

1. Add files with “Add files…” and “Add folder…”, or drag them into the list.
2. If a video has several audio tracks, select the file in the list and pick the track below the list. By default the track marked in the file itself is used.
3. Choose the model and the speech language. `small` and `turbo` are good for speed, `medium` and `large-v3` for accuracy. Next to the model you can see whether it is downloaded; the “Download” button fetches it in advance.
4. Choose the result: subtitles in the spoken language, translation to English by Whisper, or machine translation of the subtitles. For machine translation pick the language and tick what to save: the original, the translation, bilingual subtitles.
5. Tick the formats you need. If cues come out too long, turn on “Split into short cues” and set characters per line, number of lines and cue duration.
6. If needed, choose an output folder and press “Create subtitles”.

Result files are named `file_name.whisper.srt`, `file_name.whisper.vtt` and so on, and by default are saved next to the sources. With machine translation to English you also get `file_name.whisper.en.srt` (translation) and `file_name.whisper.en.bilingual.srt` (bilingual). A source is skipped when all its result files already exist, unless “Overwrite existing files” is on. “Stop after the current file” finishes the current file and does not start the next ones; “Cancel now” interrupts the work at once, and no result files are created for the interrupted file.

Settings are stored in `%APPDATA%\WhisperSRT\settings.json`. Models are kept in the Hugging Face cache by default (`%USERPROFILE%\.cache\huggingface\hub`).

## Machine translation of subtitles

Translation is done by the [NLLB-200](https://huggingface.co/facebook/nllb-200-distilled-600M) model (distilled, 600M) running on CTranslate2. It is downloaded the first time you translate (about 620 MB); after that no internet is needed. Supported languages: Russian, English, German, Ukrainian, French, Spanish, Italian, Polish, Portuguese, Turkish, Dutch, Czech, Japanese, Chinese, Korean, Arabic, Hindi and Vietnamese.

The source language comes from recognition. If it equals the target language, translation is skipped. Every cue is translated on its own, so machine translation can be inexact: proofread it for anything important.

> **Model license.** The NLLB-200 weights are released under **CC-BY-NC-4.0**: they may be used for non-commercial purposes only. The program code stays under MIT. If you need translation in a commercial project, point the program at a different model with the `WHISPERSRT_NLLB_REPO` environment variable (a Hugging Face repository with an NLLB model converted to the CTranslate2 format).

## Command-line tool

```bash
# One file
python whisper_universal.py "video.mp4" --model turbo --language en

# A whole folder including subfolders, results in a separate folder
python whisper_universal.py "D:\Videos" --recursive --output-dir "D:\Subs"

# Several formats and short cues (up to 2 lines of 42 characters)
python whisper_universal.py "video.mp4" -f srt,vtt,txt --max-line-chars 42

# Subtitles with an English translation: original, translation and a bilingual file
python whisper_universal.py "video.mp4" --translate-to en --variants original,translated,bilingual

# Show the audio tracks of a file, then pick one
python whisper_universal.py "movie.mkv" --list-streams
python whisper_universal.py "movie.mkv" --audio-stream 2
```

| Option | What it does |
|---|---|
| `-m`, `--model` | `tiny`, `base`, `small` (default), `medium`, `large-v3`, `turbo` |
| `-l`, `--language` | Language code (`ru`, `en`, `de`…) or `auto` for detection |
| `--task` | `transcribe` — text in the original language, `translate` — translation to English by Whisper |
| `--translate-to` | Machine-translate the subtitles (NLLB-200) into the given language: `en`, `ru`, `de`… |
| `--variants` | What to save when translating: `original`, `translated`, `bilingual`, comma-separated (default `original,translated`) |
| `--lang` | Language of messages and help: `auto`, `ru`, `en` |
| `-f`, `--formats` | Comma-separated formats: `srt`, `vtt`, `txt`, `json`, `ass` (default `srt`) |
| `--max-line-chars` | Maximum characters per line, `0` — do not split cues |
| `--max-lines` | Maximum lines per cue when splitting (default 2) |
| `--max-duration` | Maximum cue duration in seconds, `0` — unlimited |
| `--model-dir` | Folder for downloaded models |
| `--device` | `auto` (default), `cpu`, `cuda` |
| `--audio-stream` | Global FFmpeg audio stream index or `auto` |
| `-o`, `--output-dir` | Output folder |
| `-r`, `--recursive` | Look for files in subfolders |
| `--overwrite` | Overwrite existing result files |
| `--no-vad` | Disable the VAD filter |
| `--beam-size` | Beam search width (always 1 for `turbo`) |
| `--list-streams` | Show the streams of a file and exit |

Full list: `python whisper_universal.py --help`.

## NVIDIA GPU

GPU mode needs the NVIDIA driver, CUDA 12 (cuBLAS) and cuDNN 9. They are not included in the archive. If these libraries are missing in “Automatic” mode, the program says so in the log, switches to CPU and repeats the recognition. A `--device cuda` chosen explicitly on the command line does not fall back to CPU and shows the error.

## Run from source

Python 3.9–3.12 is required. The icon lives in `assets/` and the interface strings in `i18n.py`.

```bash
git clone https://github.com/DmitryLeLeE/whisp.git
cd whisp

python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Download a Windows FFmpeg build (for example from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) or [BtbN](https://github.com/BtbN/FFmpeg-Builds/releases)) and put `ffmpeg.exe` and `ffprobe.exe` into the `ffmpeg_bin/` folder in the project root. If FFmpeg is already in `PATH`, you can skip this step.

```bash
# The window
python WhisperSRT_GUI.py

# The command-line tool
python whisper_universal.py "video.mp4" --model turbo --language en
```

## Build your own `.exe`

```cmd
pip install -r requirements-build.txt
build.bat
```

The result appears in `dist\WhisperSRT\`. Copy the whole folder to move it to another computer.

## Releasing

A release is built automatically by GitHub Actions from a tag:

```bash
git tag v1.2.0
git push origin v1.2.0
```

The [`release.yml`](.github/workflows/release.yml) workflow checks the translation tables, downloads FFmpeg, builds the app, prints the build size, checks it by running `WhisperSRT.exe --selftest`, packs `WhisperSRT-Windows.zip` and attaches it to the release. If a release with that tag was already created by hand on GitHub, the archive is added to it. You can also start a build without a tag on the Actions tab: the archive appears in the run's artifacts.

## License

Code: [MIT](LICENSE). FFmpeg, the Whisper models and the NLLB-200 translation model (CC-BY-NC-4.0, non-commercial use only) are distributed under their own licenses.
