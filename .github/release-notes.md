## Install / Как установить

**English**

Choose one of the two files below, in Assets. It is the same program, and you do not need to install Python or FFmpeg.

- **`WhisperSRT.exe`**: a single file, nothing to unpack. It unpacks itself into a temporary folder on every start, so it starts more slowly.
- **`WhisperSRT-Windows.zip`**: a folder. Unpack it into any folder (do not run the `.exe` from inside the archive) and run **`WhisperSRT\WhisperSRT.exe`**. It starts faster.

On the first run the selected model is downloaded from Hugging Face and cached; after that the program works offline. Machine translation downloads the NLLB-200 model (about 620 MB) the first time it is used. Its weights are CC-BY-NC-4.0: non-commercial use only.

NVIDIA GPU: CUDA 12 (cuBLAS) and cuDNN 9 are needed and are not included. If they are missing, “Automatic” mode switches to CPU by itself.

**Русский**

Выберите один из двух файлов ниже, в разделе Assets. Программа одна и та же, Python и FFmpeg ставить не нужно.

- **`WhisperSRT.exe`**: один файл, распаковывать нечего. При каждом запуске он распаковывается во временную папку, поэтому стартует медленнее.
- **`WhisperSRT-Windows.zip`**: папка. Распакуйте её в любое место (не запускайте `.exe` прямо из архива) и запустите **`WhisperSRT\WhisperSRT.exe`**. Стартует быстрее.

При первом запуске выбранная модель скачивается с Hugging Face и сохраняется в кэш, дальше программа работает без интернета. Для машинного перевода при первом использовании скачивается модель NLLB-200 (около 620 МБ). Её веса распространяются под CC-BY-NC-4.0: только некоммерческое использование.

Видеокарта NVIDIA: нужны CUDA 12 (cuBLAS) и cuDNN 9, они в архив не входят. Если их нет, режим «Автоматически» сам переключится на CPU.

## What's changed / Что изменилось


**English**
- Fixed: recognition failed on every file with the error "open() got an unexpected keyword argument 'metadata_errors'" (incompatibility of faster-whisper with the new PyAV 19). If you downloaded 1.2.0 or 1.2.1, please update.
- The self-test now decodes a real audio file, so this kind of breakage is caught before a release.
- The single-file `WhisperSRT.exe` is available next to the folder version.

**Русский**
- Исправлено: распознавание падало на любом файле с ошибкой «open() got an unexpected keyword argument 'metadata_errors'» (несовместимость faster-whisper с новым PyAV 19). Если вы скачали 1.2.0 или 1.2.1, обновитесь.
- Самопроверка теперь декодирует настоящий звуковой файл, поэтому такие поломки ловятся до релиза.
- Одиночный `WhisperSRT.exe` доступен рядом с папочной версией.
