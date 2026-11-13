# Changelog / История изменений

## 1.2.0

**English**
- Machine translation of subtitles (NLLB-200 via CTranslate2) into 18 languages. Save the translation, the original, or bilingual subtitles. In the command line: `--translate-to` and `--variants`. The model weights are CC-BY-NC-4.0 (non-commercial use only).
- English and Russian interface, switchable on the fly; `--lang` for the command line (messages and `--help`). The README and the release notes are now in both languages.
- "Cancel now" button: interrupts the current file at once, no partial result is written.
- Sound, taskbar flash and Windows notification when the work is finished (can be turned off).
- Program icon.
- The build prints the size of its folders, and the self-test checks the translator stack, the icon and the translation tables.

**Русский**
- Машинный перевод субтитров (NLLB-200 через CTranslate2) на 18 языков. Можно сохранить перевод, оригинал или двуязычные субтитры. В консоли: `--translate-to` и `--variants`. Веса модели распространяются под CC-BY-NC-4.0 (только некоммерческое использование).
- Интерфейс на русском и английском, язык переключается на лету; `--lang` для консоли (сообщения и `--help`). README и описания релизов теперь на двух языках.
- Кнопка «Отменить сейчас»: текущий файл прерывается сразу, частичный результат не записывается.
- Сигнал, мигание кнопки на панели задач и уведомление Windows по окончании работы (можно отключить).
- Иконка программы.
- Сборка выводит размеры своих папок, а самопроверка проверяет переводчик, иконку и таблицы переводов.

## 1.1.0 (русский)

Интерфейс
- Список файлов с длительностью, выбранной аудиодорожкой и состоянием каждого файла. Файлы можно перетаскивать в окно.
- Выбор аудиодорожки из списка (язык, название, кодек) отдельно для каждого файла.
- Современное оформление, тёмная и светлая темы. По умолчанию тема берётся из настроек Windows.
- Два индикатора прогресса: по текущему файлу и по всей очереди, оценка оставшегося времени.
- Настройки запоминаются между запусками (`%APPDATA%\WhisperSRT\settings.json`).
- Кнопка «Открыть папку».

Функции
- Форматы вывода: SRT, VTT, TXT, JSON, ASS. Можно выбрать несколько сразу.
- Разбиение длинных реплик: максимум символов в строке, число строк и длительность реплики.
- Режим «Перевод на английский» в окне программы.
- Скачивание моделей с индикатором загрузки, отдельная кнопка «Скачать» и своя папка для моделей.
- В консольной утилите новые параметры `--formats`, `--max-line-chars`, `--max-lines`, `--max-duration`, `--model-dir`.

Сборка
- В собранном приложении есть режим `--selftest`, его запускает CI перед упаковкой архива.

## 1.0.0 (русский)

- Первый релиз: окно программы и консольная утилита, VAD-фильтр, выбор аудиодорожки, CUDA и CPU.
- Автоматический переход на CPU, если не хватает библиотек CUDA.
