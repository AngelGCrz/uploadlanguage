#!/bin/bash
set -e

PROJECT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
CODEX_PYTHON="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"

if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
  PYTHON="$PROJECT_DIR/.venv/bin/python"
elif [ -x "$CODEX_PYTHON" ]; then
  PYTHON="$CODEX_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  echo "No se encontró Python. Instala Python 3.10 o superior y consulta README.md." >&2
  exit 1
fi

if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Se requiere Python 3.10 o superior. Python seleccionado: $PYTHON" >&2
  echo "Crea .venv con una versión compatible siguiendo README.md." >&2
  exit 1
fi

if ! "$PYTHON" -c 'import docx' >/dev/null 2>&1; then
  echo "Falta python-docx. Instala las dependencias con:" >&2
  echo "\"$PYTHON\" -m pip install -r \"$PROJECT_DIR/requirements.txt\"" >&2
  exit 1
fi

exec "$PYTHON" -X utf8 "$PROJECT_DIR/upload_language.py" "$@"
