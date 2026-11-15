@echo off
rem ============================================================
rem  Aero Suite - un processo, un report
rem  Trascina su questo file la cartella _dati_batch, oppure avvialo
rem  e incolla il percorso.
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Aero Suite

if not "%~1"=="" goto have_data
echo.
echo Trascina su questo file la cartella _dati_batch (quella con dataset.csv).
echo.
set /p "DATA=Cartella dati: "
goto check
:have_data
set "DATA=%~1"
:check
set "DATA=%DATA:"=%"
if not exist "%DATA%\dataset.csv" goto bad_data

set "EXE=%~dp0FS-MetaPostDiag.exe"
if exist "%EXE%" goto have_exe
if exist "%~dp0..\FS-MetaPostDiag.exe" set "EXE=%~dp0..\FS-MetaPostDiag.exe"
if exist "%EXE%" goto have_exe
set /p "EXE=Percorso di FS-MetaPostDiag.exe: "
set "EXE=%EXE:"=%"
:have_exe
if not exist "%EXE%" goto bad_exe

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
echo Dati: %DATA%
echo Exe : %EXE%
echo.
set "SKIP="
echo.
echo I report completi (immagini META, report HTML/PDF, AI se configurata) richiedono
echo circa 1-2 minuti per caso. Puoi saltarli per la sola analisi dati.
set /p "FULL=Eseguire i report completi per ogni caso? (S/n): "
if /i "%FULL%"=="n" set "SKIP=--skip-process"
echo.
set /p "NOMETA=Saltare il rendering META (piu' veloce, immagini solo dai grafici)? (s/N): "
if /i "%NOMETA%"=="s" set "SKIP=%SKIP% --no-meta"
echo.
%PY% aero_suite.py --data "%DATA%" --exe "%EXE%" --tools "..\tools" --stage all %SKIP%
if errorlevel 3 goto partial
echo.
echo Apro l'Aero Suite...
start "" "%DATA%\Aero_Suite.html"
pause
exit /b 0

:partial
echo.
echo Alcuni casi non hanno prodotto la geometria (vedi sopra). La suite si apre comunque.
start "" "%DATA%\Aero_Suite.html"
pause
exit /b 3

:bad_data
echo.
echo ERRORE: in %DATA% non c'e' dataset.csv (non e' la cartella _dati_batch).
pause
exit /b 1
:bad_exe
echo.
echo ERRORE: eseguibile non trovato: %EXE%
pause
exit /b 1
