@echo off
REM Mesta PDF Pro build:
REM 1) builds the app with PyInstaller (in %TEMP% - Windows path-length limit)
REM 2) builds the multi-language installer release\MestaPDFPro-Setup-x.y.z.exe
REM    (run that installer to install / update the app)
cd /d "%~dp0"
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
set "B=%TEMP%\psbuild"
"%PY%" tools\make_icons.py
"%PY%" -m PyInstaller --noconfirm --clean --windowed --name MestaPDFPro --icon "%~dp0assets\logo.ico" ^
  --add-data "%~dp0assets;assets" --add-data "%~dp0tessdata;tessdata" ^
  --distpath "%B%\dist" --workpath "%B%\work" --specpath "%B%" ^
  --exclude-module onnxruntime --exclude-module pymupdf_layout --exclude-module pymupdf4llm ^
  --collect-submodules pymupdf --hidden-import pdfstudio.lang_en --hidden-import pdfstudio.lang_fr ^
  --hidden-import pdfstudio.ocr_worker "%~dp0main.py"
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ISCC%" "%ISCC%" /Q "/DSrcDir=%B%\dist\MestaPDFPro" "%~dp0installer\MestaPDFPro.iss"
echo.
echo Installer: %~dp0release
pause
