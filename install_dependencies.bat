@echo off
title FS-MetaPostDiag - Installazione Dipendenze Python
cd /d "%~dp0"
echo ============================================================================
echo   FS-MetaPostDiag: Installazione Dipendenze Python
echo ============================================================================
echo.
python --version
if %ERRORLEVEL% NEQ 0 (
    echo [ERRORE] Python non e' installato o non e' presente nella variabile PATH.
    echo Scarica e installa Python da https://www.python.org/ (seleziona "Add python.exe to PATH").
    echo.
    pause
    exit /b 1
)
echo.
echo Aggiornamento pip e installazione librerie (numpy, scipy, matplotlib, Pillow, PyYAML)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if %ERRORLEVEL% EQU 0 (
    echo.
    echo ============================================================================
    echo   Installazione completata con successo!
    echo   Puoi ora avviare l'applicazione con run_gui.bat o run_diagnostics.bat
    echo ============================================================================
) else (
    echo.
    echo [ATTENZIONE] Si sono verificati errori durante l'installazione delle dipendenze.
)
echo.
pause
