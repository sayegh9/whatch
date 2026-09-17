#!/bin/zsh

set -u
setopt NO_BG_NICE

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${WHATCH_PORT:-8000}"
APP_URL="http://127.0.0.1:${PORT}"
HEALTH_URL="${APP_URL}/api/health"
LOG_DIR="${SCRIPT_DIR}/data/logs"
LOG_FILE="${LOG_DIR}/whatch.log"
PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"
FRONTEND_DIR="${SCRIPT_DIR}/frontend"
FRONTEND_INDEX="${FRONTEND_DIR}/dist/index.html"
SERVER_PID=""

show_failure() {
  echo
  echo "Whatch could not start."
  echo "$1"
  echo
  echo "Log: ${LOG_FILE}"
  if [[ -f "${LOG_FILE}" ]]; then
    echo
    echo "Recent log output:"
    tail -20 "${LOG_FILE}"
  fi
  echo
  read "?Press Return to close this window."
  exit 1
}

cleanup() {
  if [[ -n "${SERVER_PID}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    echo
    echo "Stopping Whatch..."
    kill "${SERVER_PID}" 2>/dev/null
    wait "${SERVER_PID}" 2>/dev/null
  fi
}

trap cleanup EXIT INT TERM

cd "${SCRIPT_DIR}" || show_failure "The Whatch project folder could not be opened."
mkdir -p "${LOG_DIR}" || show_failure "The local log folder could not be created."

echo
echo "Whatch"
echo "======"

if curl --silent --fail --max-time 1 "${HEALTH_URL}" >/dev/null 2>&1; then
  echo "Whatch is already running."
  if [[ "${WHATCH_SKIP_OPEN:-0}" != "1" ]]; then
    open "${APP_URL}"
  fi
  exit 0
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
  if ! command -v uv >/dev/null 2>&1; then
    show_failure "Python dependencies are missing. Install uv, then run this launcher again."
  fi
  echo "Preparing the local Python environment..."
  uv sync || show_failure "The Python environment could not be prepared."
fi

echo "Updating the local database..."
"${PYTHON_BIN}" -m alembic upgrade head \
  || show_failure "The local database could not be updated."

NEEDS_BUILD=0
if [[ ! -f "${FRONTEND_INDEX}" ]]; then
  NEEDS_BUILD=1
elif [[ -n "$(find "${FRONTEND_DIR}/src" -type f -newer "${FRONTEND_INDEX}" -print -quit)" ]]; then
  NEEDS_BUILD=1
elif [[ "${FRONTEND_DIR}/package.json" -nt "${FRONTEND_INDEX}" ]] \
  || [[ "${FRONTEND_DIR}/vite.config.ts" -nt "${FRONTEND_INDEX}" ]]; then
  NEEDS_BUILD=1
fi

if [[ "${NEEDS_BUILD}" == "1" ]]; then
  if ! command -v npm >/dev/null 2>&1; then
    show_failure "The interface needs to be built, but npm is not installed."
  fi
  if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
    echo "Installing interface dependencies..."
    (cd "${FRONTEND_DIR}" && npm install) \
      || show_failure "The interface dependencies could not be installed."
  fi
  echo "Preparing the Whatch interface..."
  (cd "${FRONTEND_DIR}" && npm run build) \
    || show_failure "The Whatch interface could not be built."
fi

echo "Starting the private local server..."
"${PYTHON_BIN}" -m uvicorn backend.app.main:app \
  --host 127.0.0.1 \
  --port "${PORT}" \
  >>"${LOG_FILE}" 2>&1 &
SERVER_PID=$!

READY=0
for _attempt in {1..40}; do
  if curl --silent --fail --max-time 1 "${HEALTH_URL}" >/dev/null 2>&1; then
    READY=1
    break
  fi
  if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
    break
  fi
  sleep 0.25
done

if [[ "${READY}" != "1" ]]; then
  show_failure "The local server did not become ready."
fi

echo
echo "Whatch is ready: ${APP_URL}"
echo "Keep this window open while using the app."
echo "Close it or press Control-C to stop Whatch."
echo

if [[ "${WHATCH_SKIP_OPEN:-0}" != "1" ]]; then
  open "${APP_URL}"
fi

wait "${SERVER_PID}"
