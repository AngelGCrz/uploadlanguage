@echo off
setlocal
set "UPLOAD_LANGUAGE_PYTHON_ARGS="
set "UPLOAD_LANGUAGE_PYTHON=%~dp0.venv\Scripts\python.exe"
if exist "%UPLOAD_LANGUAGE_PYTHON%" goto run_python
set "UPLOAD_LANGUAGE_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%UPLOAD_LANGUAGE_PYTHON%" goto run_python
where py >nul 2>&1
if not errorlevel 1 (
  set "UPLOAD_LANGUAGE_PYTHON=py"
  set "UPLOAD_LANGUAGE_PYTHON_ARGS=-3"
  goto run_python
)
where python >nul 2>&1
if not errorlevel 1 (
  set "UPLOAD_LANGUAGE_PYTHON=python"
  goto run_python
)
echo No se encontro Python. Instala Python 3.10 o superior y consulta README.md. 1>&2
exit /b 1

:run_python
"%UPLOAD_LANGUAGE_PYTHON%" %UPLOAD_LANGUAGE_PYTHON_ARGS% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo Se requiere Python 3.10 o superior. Consulta README.md. 1>&2
  exit /b 1
)
"%UPLOAD_LANGUAGE_PYTHON%" %UPLOAD_LANGUAGE_PYTHON_ARGS% -c "import docx" >nul 2>&1
if errorlevel 1 (
  echo Falta python-docx. Instala las dependencias con: 1>&2
  echo "%UPLOAD_LANGUAGE_PYTHON%" %UPLOAD_LANGUAGE_PYTHON_ARGS% -m pip install -r "%~dp0requirements.txt" 1>&2
  exit /b 1
)
"%UPLOAD_LANGUAGE_PYTHON%" %UPLOAD_LANGUAGE_PYTHON_ARGS% -X utf8 "%~dp0upload_language.py" %*
exit /b %errorlevel%
