@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" launch_demo.py %*
  goto finished
)
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
  "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" launch_demo.py %*
  goto finished
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 launch_demo.py %*
  goto finished
)
where python >nul 2>nul
if not errorlevel 1 (
  python launch_demo.py %*
  goto finished
)
echo Python was not found. Install Python 3.9 or newer, then run this file again.
pause
goto end
:finished
if errorlevel 1 pause
:end
popd
endlocal
