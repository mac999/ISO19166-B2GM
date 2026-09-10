@echo off
rem Run the PD -> CM -> EM -> LM pipeline on the shipped example.
rem Extra arguments are passed on to B2GM_main.py, e.g.:
rem   run_pipeline.bat --citygml-version 3.0
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo Python 3.9 or newer is required but was not found on PATH.
    echo Install it from https://www.python.org/downloads/ and tick "Add to PATH".
    exit /b 1
)

%PY% -c "import ifcopenshell, pyproj, shapely, numpy, tqdm" >nul 2>&1
if errorlevel 1 (
    echo Installing the core dependencies ...
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 exit /b 1
)

%PY% B2GM_main.py %*
