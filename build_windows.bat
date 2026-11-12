python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name WhisperSRT ^
  --collect-all faster_whisper ^
  --collect-all ctranslate2 ^
  --collect-all onnxruntime ^
  --collect-all av ^
  --hidden-import faster_whisper ^
  --hidden-import ctranslate2 ^
  --add-binary "ffmpeg_bin\ffmpeg.exe;ffmpeg_bin" ^
  --add-binary "ffmpeg_bin\ffprobe.exe;ffmpeg_bin" ^
  WhisperSRT_GUI.py