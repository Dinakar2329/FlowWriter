@echo off
setlocal
cd /d "%~dp0"
set "FLOWWRITER_BUILD_ROOT=%~dp0"
set "FW_NO_PAUSE="
set "FW_NO_SHORTCUT="
:args
if "%~1"=="" goto :setup
if /i "%~1"=="--no-pause" (
    set "FW_NO_PAUSE=1"
    shift
    goto :args
)
if /i "%~1"=="--no-shortcut" (
    set "FW_NO_SHORTCUT=1"
    shift
    goto :args
)
echo Unknown option: %~1
exit /b 2
:setup
echo Building FlowWriter Studio for Windows...
if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv 2>nul
    if errorlevel 1 python -m venv .venv
    if errorlevel 1 goto :failed
)
echo Installing declared build and test dependencies...
".venv\Scripts\python.exe" -m pip install "setuptools>=70" wheel
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install --no-build-isolation -e ".[build,test]"
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pytest -q tests
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m compileall -q flowwriter scripts
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" scripts\build_release.py
if errorlevel 1 goto :failed
if not exist "dist\FlowWriterStudio\FlowWriterStudio.exe" goto :failed
echo Verifying the packaged app with disposable data...
powershell -NoProfile -NonInteractive -Command "$exe=Join-Path $env:FLOWWRITER_BUILD_ROOT 'dist\FlowWriterStudio\FlowWriterStudio.exe'; $process=Start-Process -FilePath $exe -ArgumentList '--smoke-test' -PassThru -WindowStyle Hidden; if (-not $process.WaitForExit(30000)) { Stop-Process -Id $process.Id; exit 1 }; exit $process.ExitCode"
if errorlevel 1 goto :failed
if defined FW_NO_SHORTCUT goto :done
echo Creating your desktop shortcut...
powershell -NoProfile -NonInteractive -Command "$root=$env:FLOWWRITER_BUILD_ROOT; $exe=Join-Path $root 'dist\FlowWriterStudio\FlowWriterStudio.exe'; $desktop=[Environment]::GetFolderPath('Desktop'); $shell=New-Object -ComObject WScript.Shell; $link=$shell.CreateShortcut((Join-Path $desktop 'FlowWriter Studio.lnk')); $link.TargetPath=$exe; $link.WorkingDirectory=Split-Path -LiteralPath $exe; $link.IconLocation=$exe+',0'; $link.Description='FlowWriter Studio'; $link.Save()"
if errorlevel 1 (
    echo The executable was built, but the desktop shortcut could not be created.
    echo Launch dist\FlowWriterStudio\FlowWriterStudio.exe directly.
    if not defined FW_NO_PAUSE pause
    exit /b 1
)
:done
echo.
echo Ready: "%~dp0dist\FlowWriterStudio\FlowWriterStudio.exe"
echo Keep the entire dist\FlowWriterStudio folder together when moving the app.
if defined FW_NO_PAUSE exit /b 0
echo.
echo Press any key to open FlowWriter Studio...
pause >nul
start "" "%~dp0dist\FlowWriterStudio\FlowWriterStudio.exe"
exit /b 0
:failed
echo.
echo Build failed. Check the error above. No successful build is being claimed.
if not defined FW_NO_PAUSE pause
exit /b 1
