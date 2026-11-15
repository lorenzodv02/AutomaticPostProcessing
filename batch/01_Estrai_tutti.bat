@echo off
rem ============================================================
rem  FS-MetaPostDiag - estrazione in blocco delle analisi CFD
rem  Trascina su questo file la cartella che contiene le analisi,
rem  oppure avvialo e incolla il percorso.
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title FS-MetaPostDiag - estrazione in blocco

if not "%~1"=="" goto have_root
echo.
echo Trascina su questo file la CARTELLA RADICE che contiene le analisi
echo (le sottocartelle possono essere annidate: Venturi\analisi 1\file.cas).
echo.
set /p "ROOT=Cartella radice: "
goto check_root
:have_root
set "ROOT=%~1"
:check_root
set "ROOT=%ROOT:"=%"
if not exist "%ROOT%" goto bad_root

set "EXE=%~dp0FS-MetaPostDiag.exe"
if exist "%EXE%" goto have_exe
echo.
echo Eseguibile non trovato accanto agli script.
set /p "EXE=Percorso di FS-MetaPostDiag.exe: "
set "EXE=%EXE:"=%"
:have_exe
if not exist "%EXE%" goto bad_exe

set "ASM=full_car"
echo.
echo Assieme da analizzare:
echo   [1] full_car  (consigliato: conserva tutti i PID, si filtra dopo)
echo   [2] undertray
echo   [3] front_wing
echo   [4] rear_wing
set /p "SCELTA=Scelta [1]: "
if "%SCELTA%"=="2" set "ASM=undertray"
if "%SCELTA%"=="3" set "ASM=front_wing"
if "%SCELTA%"=="4" set "ASM=rear_wing"

echo.
set /p "DRY=Prima solo l'elenco dei casi trovati? [s/N]: "
set "OPT="
if /i "%DRY%"=="s" set "OPT=--dry-run"

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto py_ok
where python >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto py_ok
echo.
echo ERRORE: Python 3 non trovato.
echo Installalo da https://www.python.org/downloads/ segnando "Add python.exe to PATH",
echo oppure copia una installazione portatile accanto a questi script.
pause
exit /b 1

:py_ok
%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,8) else 1)"
if errorlevel 1 goto bad_py

echo.
echo Comando: %PY% batch_extract.py --root "%ROOT%" --exe "%EXE%" --assembly %ASM% %OPT%
echo.
%PY% batch_extract.py --root "%ROOT%" --exe "%EXE%" --assembly %ASM% %OPT%
if errorlevel 3 goto had_errors
if errorlevel 1 goto bad_run
if not defined OPT echo %ROOT%\_dati_batch> "%~dp0_ultima_cartella.txt"

echo.
if /i "%DRY%"=="s" goto done
echo Ora lancia 02_Tabelle_e_controlli.bat per costruire le tabelle.
goto done

:bad_root
echo.
echo ERRORE: cartella non trovata: %ROOT%
pause
exit /b 1
:bad_exe
echo.
echo ERRORE: eseguibile non trovato: %EXE%
pause
exit /b 1
:bad_py
echo.
echo ERRORE: serve Python 3.8 o superiore.
pause
exit /b 1
:bad_run
echo.
echo Estrazione non riuscita: leggi il messaggio sopra.
pause
exit /b 1
:had_errors
echo.
echo Alcuni casi hanno dato errore: leggi run_summary.txt nella cartella dei risultati.
pause
exit /b 3

:done
echo.
pause
endlocal
