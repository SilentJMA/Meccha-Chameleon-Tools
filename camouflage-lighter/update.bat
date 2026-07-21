@echo off
chcp 65001 >nul
title Camouflage Lighter - Update

echo ============================================
echo  Camouflage Lighter - Update Script
echo ============================================
echo.

REM --- Find the latest version installed in AppData ---
set "BASE=%LOCALAPPDATA%\MecchaCamouflage\versions"
if not exist "%BASE%" (
    echo ERROR: No MecchaCamouflage installation found in %%LOCALAPPDATA%%.
    echo Run the official release EXE once, then run this script.
    pause
    exit /b 1
)

REM --- Find newest version folder ---
set "LATEST="
for /f "delims=" %%d in ('dir "%BASE%" /b /ad /o-n 2^>nul') do (
    if not defined LATEST set "LATEST=%%d"
)
if "%LATEST%"=="" (
    echo ERROR: No version directories found in %BASE%.
    pause
    exit /b 1
)
echo Found version: %LATEST%
echo.

set "SRC=%BASE%\%LATEST%\runtime\package-assets"

REM --- Find the assets folder (hash-named subfolder) ---
set "ASSETS="
for /f "delims=" %%d in ('dir "%SRC%" /b /ad 2^>nul') do (
    set "ASSETS=%%d"
)
if "%ASSETS%"=="" (
    echo ERROR: No package-assets folder found in %SRC%.
    echo Run the official release and wait for it to fully extract.
    pause
    exit /b 1
)

set "NATIVE_SRC=%SRC%\%ASSETS%\native"
set "MESH_SRC=%SRC%\%ASSETS%\mesh-profiles"

echo Copying native files...
copy /y "%NATIVE_SRC%\runtime-bridge.dll" "native\runtime-bridge.dll" >nul
copy /y "%NATIVE_SRC%\runtime-injector.exe" "native\runtime-injector.exe" >nul
echo  - runtime-bridge.dll
echo  - runtime-injector.exe

echo.
echo Copying mesh profiles...
if exist "%MESH_SRC%" (
    if not exist "mesh-profiles" mkdir mesh-profiles
    copy /y "%MESH_SRC%\*.json" "mesh-profiles\" >nul
    echo  - mesh profiles copied
) else (
    echo  WARNING: mesh-profiles directory not found in release assets.
    echo  If paint fails, re-run the official release first.
)

echo.
echo Installing Python dependencies...
pip install -r requirements.txt -q

echo.
echo Building lighter EXE...
pyinstaller --onefile --windowed --name "Camouflage" --add-data "native;native" --add-data "mesh-profiles;mesh-profiles" --distpath "." --noconfirm main.py >nul

echo.
echo ============================================
echo  Update complete!
echo  Output: Camouflage.exe
echo ============================================
pause
