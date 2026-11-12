@echo off
chcp 65001 > nul
echo ========================================================
echo Сборка WhisperSRT GUI в автономное Windows-приложение...
echo ========================================================

if not exist "ffmpeg_bin\ffmpeg.exe" goto no_ffmpeg
if not exist "ffmpeg_bin\ffprobe.exe" goto no_ffmpeg
goto build

:no_ffmpeg
echo [ОШИБКА] Не найдены ffmpeg_bin\ffmpeg.exe и/или ffmpeg_bin\ffprobe.exe!
echo Положите ffmpeg.exe и ffprobe.exe в папку ffmpeg_bin и запустите сборку снова.
if defined CI exit /b 1
pause
exit /b 1

:build
python -m PyInstaller --noconfirm --clean ^
    --name "WhisperSRT" ^
    --windowed ^
    --onedir ^
    --add-data "ffmpeg_bin;ffmpeg_bin" ^
    --collect-all "faster_whisper" ^
    --collect-all "ctranslate2" ^
    --collect-all "onnxruntime" ^
    --collect-all "av" ^
    --hidden-import "whisper_universal" ^
    WhisperSRT_GUI.py
if errorlevel 1 goto failed

echo.
echo ========================================================
echo Сборка завершена!
echo Папка с готовым приложением: dist\WhisperSRT\
echo ========================================================
if not defined CI pause
exit /b 0

:failed
echo.
echo [ОШИБКА] PyInstaller завершился с ошибкой.
if not defined CI pause
exit /b 1
