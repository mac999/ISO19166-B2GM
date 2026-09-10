@echo off
rem Start the B2GM web view; extra arguments are passed on to B2GM_web.py.
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

echo Starting the web view. Press Ctrl+C to stop.
%PY% B2GM_web.py %*
