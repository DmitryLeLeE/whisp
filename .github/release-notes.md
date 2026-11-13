## Install / Как установить

**English**

1. Download **`WhisperSRT-Windows.zip`** below, in Assets.
2. Unpack it into any folder (do not run the `.exe` from inside the archive).
3. Run **`WhisperSRT\WhisperSRT.exe`**. You do not need to install Python or FFmpeg.

On the first run the selected model is downloaded from Hugging Face and cached; after that the program works offline. Machine translation downloads the NLLB-200 model (about 620 MB) the first time it is used. Its weights are CC-BY-NC-4.0: non-commercial use only.

NVIDIA GPU: CUDA 12 (cuBLAS) and cuDNN 9 are needed and are not included. If they are missing, “Automatic” mode switches to CPU by itself.

**Русский**

1. Скачайте **`WhisperSRT-Windows.zip`** ниже, в разделе Assets.
2. Распакуйте архив в любую папку (не запускайте `.exe` прямо из архива).
3. Запустите **`WhisperSRT\WhisperSRT.exe`**. Python и FFmpeg ставить не нужно.

При первом запуске выбранная модель скачивается с Hugging Face и сохраняется в кэш, дальше программа работает без интернета. Для машинного перевода при первом использовании скачивается модель NLLB-200 (около 620 МБ). Её веса распространяются под CC-BY-NC-4.0: только некоммерческое использование.

Видеокарта NVIDIA: нужны CUDA 12 (cuBLAS) и cuDNN 9, они в архив не входят. Если их нет, режим «Автоматически» сам переключится на CPU.

## What's changed / Что изменилось
