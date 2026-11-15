@echo off
title FS-MetaPostDiag GUI - Post-Processing CFD (BETA CAE META Post)
cd /d "%~dp0"
python main.py --gui
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ============================================================================
    echo [ERRORE] Impossibile avviare la GUI.
    echo Assicurati che Python sia installato e che le dipendenze siano installate.
    echo Puoi installarle automaticamente facendo doppio click su:
    echo   install_dependencies.bat
    echo oppure da terminale con:
    echo   pip install -r requirements.txt
    echo ============================================================================
    echo.
    pause
)
