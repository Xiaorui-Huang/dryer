@echo off
rem Run the duplication finder, creating a local virtualenv on first use.
setlocal
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  python -m venv "%ROOT%\.venv"
  "%PY%" -m pip install -e "%ROOT%"
)
"%PY%" -m dryer %*
exit /b %ERRORLEVEL%
