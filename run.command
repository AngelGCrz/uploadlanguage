#!/bin/bash
PROJECT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
"$PROJECT_DIR/run.sh" "$@"
STATUS=$?
if [ -t 0 ]; then
  printf '\nPulsa Enter para cerrar...'
  read -r
fi
exit "$STATUS"
