@echo off
rem ============================================================
rem  FS-MetaPostDiag - tabelle e controlli del dataset estratto
rem  Da lanciare dopo 01_Estrai_tutti.bat.
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title FS-MetaPostDiag - tabelle e controlli

set "DATA="
if not "%~1"=="" set "DATA=%~1"
if defined DATA goto normalizza
rem default: cartella dei risultati accanto alla radice usata in precedenza
if exist "%~dp0_ultima_cartella.txt" (
    set /p "DATA=" < "%~dp0_ultima_cartella.txt"
)
if defined DATA goto normalizza
echo.
echo Trascina su questo file la cartella dei risultati (_dati_batch)
echo oppure la cartella radice delle analisi.
echo.
set /p "DATA=Cartella: "

:normalizza
set "DATA=%DATA:"=%"
if exist "%DATA%\_dati_batch" set "DATA=%DATA%\_dati_batch"
if not exist "%DATA%" goto bad_dir

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto py_ok
where python >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto py_ok
echo ERRORE: Python 3 non trovato.
pause
exit /b 1

:py_ok
echo.
echo === Tabelle ===
%PY% make_tables.py --data "%DATA%"
echo.
echo === Controlli di coerenza ===
%PY% check_dataset.py --data "%DATA%"
if errorlevel 4 goto problems

echo.
echo Apro la cartella dei risultati...
start "" "%DATA%"
pause
exit /b 0

:problems
echo.
echo Ci sono problemi bloccanti: leggi _controlli.txt nella cartella dei risultati.
start "" "%DATA%"
pause
exit /b 4

:bad_dir
echo.
echo ERRORE: cartella non trovata: %DATA%
pause
exit /b 1
