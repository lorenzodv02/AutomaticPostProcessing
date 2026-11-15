@echo off
title FS-MetaPostDiag - Post-Processing CFD & Diagnostica Design (META Post)
cd /d "%~dp0"
echo ============================================================================
echo  Avvio Pipeline Post-Processing CFD ^& Diagnostica Design (BETA CAE META)
echo ============================================================================
python main.py --open-report
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ============================================================================
    echo [ATTENZIONE] Si e' verificato un problema durante l'esecuzione.
    echo Assicurati che le dipendenze siano installate con:
    echo   install_dependencies.bat
    echo oppure:
    echo   pip install -r requirements.txt
    echo ============================================================================
    echo.
    pause
)
