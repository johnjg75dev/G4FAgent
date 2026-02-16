#!/usr/bin/env bash

set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR" || exit 1
export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"

if command -v python3 >/dev/null 2>&1; then
  PY_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PY_BIN="python"
else
  echo "Python interpreter not found."
  exit 1
fi

run_offline() {
  echo
  echo "Running offline tests..."
  "$PY_BIN" -m unittest discover -s tests -p "test_offline_*.py" -v
}

run_online() {
  echo
  echo "Running online tests..."
  G4F_ONLINE_TESTS=1 "$PY_BIN" -m unittest discover -s tests -p "test_online_*.py" -v
}

while true; do
  cat <<'MENU'

======================================
G4FAgent Test Runner
======================================
1. Run offline-only tests
2. Run online-only tests
3. Run both offline and online tests
4. Exit
MENU
  read -r -p "Select an option [1-4]: " choice

  case "$choice" in
    1)
      run_offline
      exit $?
      ;;
    2)
      run_online
      exit $?
      ;;
    3)
      rc=0
      run_offline || rc=1
      run_online || rc=1
      exit $rc
      ;;
    4)
      exit 0
      ;;
    *)
      echo "Invalid option."
      ;;
  esac
done
