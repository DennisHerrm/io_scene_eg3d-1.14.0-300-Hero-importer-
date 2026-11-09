@echo off
REM ===========================================================================
REM  BAUE_RELEASE.bat - Release-ZIP des Blender-Addons bauen
REM
REM  Aufruf:  BAUE_RELEASE.bat [pfad\zu\blender.exe]
REM           ohne Angabe: neuestes Blender unter "Program Files\Blender Foundation"
REM
REM  Ergebnis in dist\:
REM    io_scene_eg3d-<version>.zip   installierbar ueber
REM                                  Edit > Preferences > Get Extensions >
REM                                  Install from Disk (Blender 4.2+)
REM    SHA256SUMS.txt
REM
REM  Die Version steht an zwei Stellen und muss gleich sein:
REM    io_scene_eg3d\blender_manifest.toml   version = "x.y.z"
REM    io_scene_eg3d\__init__.py             ADDON_VERSION = (x, y, z)
REM  Das Skript bricht ab, wenn sie auseinanderlaufen.
REM
REM  Gebaut wird mit Blenders eigenem "extension build" (laesst __pycache__
REM  und andere Reste weg) und danach mit "extension validate" geprueft.
REM ===========================================================================
setlocal enabledelayedexpansion
set "PSModulePath="
cd /d "%~dp0"
set "QUELLE=%CD%\io_scene_eg3d"
set "DIST=%CD%\dist"

REM  Aus einer 32-Bit-Shell gestartet zeigt %ProgramFiles% auf "(x86)" -
REM  Blender liegt aber unter dem 64-Bit-Ordner.
set "PF=%ProgramW6432%"
if not defined PF set "PF=%ProgramFiles%"
set "BLENDER=%~1"
if "%BLENDER%"=="" (
  for /f "usebackq delims=" %%b in (`powershell -NoProfile -Command "Get-ChildItem '%PF%\Blender Foundation' -Directory | Sort-Object { [version](($_.Name -replace '[^0-9.]','') + '.0') } -Descending | ForEach-Object { Join-Path $_.FullName 'blender.exe' } | Where-Object { Test-Path $_ } | Select-Object -First 1"`) do set "BLENDER=%%b"
)
if not exist "%BLENDER%" (echo FEHLER: blender.exe nicht gefunden - Pfad als Argument angeben & exit /b 1)
echo  Blender: %BLENDER%

REM ---- Version aus beiden Quellen, muessen gleich sein ----------------------
for /f "usebackq delims=" %%v in (`powershell -NoProfile -Command "(Get-Content '%QUELLE%\blender_manifest.toml' | Where-Object { $_ -match '^version' }) -replace '[^0-9.]',''"`) do set "VER=%%v"
for /f "usebackq delims=" %%v in (`powershell -NoProfile -Command "(Get-Content '%QUELLE%\__init__.py' | Where-Object { $_ -match '^ADDON_VERSION' }) -replace '^[^(]*\(','' -replace '\).*','' -replace '\s','' -replace ',','.'"`) do set "VERPY=%%v"
if not defined VER (echo FEHLER: version in blender_manifest.toml nicht lesbar & exit /b 1)
if not "%VER%"=="%VERPY%" (echo FEHLER: Manifest sagt %VER%, __init__.py sagt %VERPY% & exit /b 1)
echo  Version: %VER%

if not exist "%DIST%" mkdir "%DIST%"
set "ZIP=%DIST%\io_scene_eg3d-%VER%.zip"
if exist "%ZIP%" del "%ZIP%"

"%BLENDER%" --factory-startup --command extension build --source-dir "%QUELLE%" --output-filepath "%ZIP%"
if errorlevel 1 (echo FEHLER: extension build & exit /b 1)
if not exist "%ZIP%" (echo FEHLER: ZIP wurde nicht erzeugt & exit /b 1)

"%BLENDER%" --factory-startup --command extension validate "%ZIP%"
if errorlevel 1 (echo FEHLER: extension validate & exit /b 1)

powershell -NoProfile -Command "Get-ChildItem '%ZIP%' | ForEach-Object { '{0}  {1}' -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name } | Set-Content -Encoding ascii '%DIST%\SHA256SUMS.txt'"
echo.
echo  FERTIG:
type "%DIST%\SHA256SUMS.txt"
exit /b 0
