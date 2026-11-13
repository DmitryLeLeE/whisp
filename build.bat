@echo off
chcp 65001 > nul
echo ========================================================
echo Building WhisperSRT as a standalone Windows application...
echo ========================================================

if not exist "ffmpeg_bin\ffmpeg.exe" goto no_ffmpeg
if not exist "ffmpeg_bin\ffprobe.exe" goto no_ffmpeg
goto build

:no_ffmpeg
echo [ERROR] ffmpeg_bin\ffmpeg.exe and/or ffmpeg_bin\ffprobe.exe not found!
echo Put ffmpeg.exe and ffprobe.exe into the ffmpeg_bin folder and run the build again.
if defined CI exit /b 1
pause
exit /b 1

:build
python -m PyInstaller --noconfirm --clean ^
    --name "WhisperSRT" ^
    --windowed ^
    --onedir ^
    --icon "assets\icon.ico" ^
    --add-data "ffmpeg_bin;ffmpeg_bin" ^
    --add-data "assets;assets" ^
    --collect-all "faster_whisper" ^
    --collect-all "ctranslate2" ^
    --collect-all "onnxruntime" ^
    --collect-all "av" ^
    --collect-all "sv_ttk" ^
    --collect-all "tkinterdnd2" ^
    --collect-all "sentencepiece" ^
    --hidden-import "whisper_universal" ^
    --hidden-import "translator" ^
    --hidden-import "hub" ^
    --hidden-import "i18n" ^
    WhisperSRT_GUI.py
if errorlevel 1 goto failed

echo.
echo ========================================================
echo Build finished!
echo The finished application is in dist\WhisperSRT\
echo ========================================================
if not defined CI pause
exit /b 0

:failed
echo.
echo [ERROR] PyInstaller failed.
if not defined CI pause
exit /b 1
