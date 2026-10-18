@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 goto location_failed

if exist ".venv\Scripts\python.exe" goto check_environment
if exist ".venv" goto incompatible_environment

echo First run: creating the local Python environment...
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto create_with_py
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto create_with_python
python3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto create_with_python3
echo Python 3.10 or later is required. Install Python with its launcher or PATH option enabled.
goto failed

:create_with_py
py -3 -m venv .venv
if errorlevel 1 goto failed
goto check_environment

:create_with_python
python -m venv .venv
if errorlevel 1 goto failed
goto check_environment

:create_with_python3
python3 -m venv .venv
if errorlevel 1 goto failed

:check_environment
".venv\Scripts\python.exe" -c "import sys; sys.exit(sys.version_info < (3, 10))"
if errorlevel 1 goto invalid_environment
".venv\Scripts\python.exe" -c "import importlib.util, sys; packages = ['IPython', 'numpy', 'pandas', 'matplotlib', 'scipy', 'statsmodels', 'arch', 'yfinance']; sys.exit(any(importlib.util.find_spec(p) is None for p in packages))" >nul 2>&1
if not errorlevel 1 goto run_project
echo Installing project dependencies. Internet access is required for first-time setup...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed

:run_project
".venv\Scripts\python.exe" run_all.py %*
if errorlevel 1 goto failed
if not exist "results\Report.html" goto failed
start "" "results\Report.html"
echo Run completed. Report: results\Report.html
popd
pause
exit /b 0

:incompatible_environment
echo The existing .venv is not a usable Windows environment.
echo Close its Python sessions and rename .venv to .venv_old, then run this file again.
echo Virtual environments must be recreated on each computer; do not copy a Mac environment.
goto failed

:invalid_environment
echo The local Python environment is broken or uses Python older than 3.10.
echo Close its Python sessions and rename .venv to .venv_old, then run this file again.
goto failed

:failed
echo Run failed. No new completed report is confirmed.
echo See the error above, results\logs, and the setup instructions in README.md.
popd
pause
exit /b 1

:location_failed
echo Cannot open the project directory. Extract the entire project ZIP before running this file.
pause
exit /b 1
