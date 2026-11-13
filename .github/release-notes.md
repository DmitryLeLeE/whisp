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
- New download `WhisperSRT.exe`: a single file with all libraries inside.
- The exe shows its version, name and author in the file properties; the icon is embedded and checked by the build.

**Русский**
- Новая загрузка `WhisperSRT.exe`: один файл со всеми библиотеками внутри.
- В свойствах exe видны версия, название и автор; иконка встроена и проверяется при сборке.
