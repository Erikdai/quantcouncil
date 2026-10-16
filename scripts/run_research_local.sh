#!/usr/bin/env bash
# Start this project's local services; Ctrl-C stops app processes, keeps DB data.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python || ! -d frontend/node_modules ]]; then
  echo 'Install dependencies first: uv venv --python 3.12 && uv pip install -e ".[platform-dev]" && npm ci --prefix frontend'
  exit 1
fi
for port in 8018 8019 5187; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $port is in use. If this app is already running, open http://127.0.0.1:5187/deep-research"
    exit 1
  fi
done
docker compose -p quantcouncil up -d --wait postgres redis
.venv/bin/alembic upgrade head
mkdir -p .quantcouncil/logs
export QUANTCOUNCIL_MCP_URL=http://127.0.0.1:8019/mcp
pids=()
.venv/bin/python -m quantcouncil.mcp_server --transport streamable-http --port 8019 >.quantcouncil/logs/mcp.log 2>&1 &
pids+=("$!")
cleanup() {
  trap - INT TERM EXIT
  kill "${pids[@]}" 2>/dev/null || true
  wait || true
}
trap cleanup INT TERM EXIT
.venv/bin/uvicorn quantcouncil.api.main:app --host 127.0.0.1 --port 8018 >.quantcouncil/logs/api.log 2>&1 &
pids+=("$!")
.venv/bin/taskiq worker quantcouncil.worker.broker:broker quantcouncil.worker.tasks --workers 1 --max-async-tasks 2 >.quantcouncil/logs/worker.log 2>&1 &
pids+=("$!")
.venv/bin/taskiq scheduler quantcouncil.worker.broker:scheduler quantcouncil.worker.tasks >.quantcouncil/logs/scheduler.log 2>&1 &
pids+=("$!")
VITE_API_TARGET=http://127.0.0.1:8018 npm run dev --prefix frontend -- --host 127.0.0.1 --port 5187 --strictPort >.quantcouncil/logs/web.log 2>&1 &
pids+=("$!")
echo 'Research: http://127.0.0.1:5187/deep-research'
echo 'Logs: .quantcouncil/logs/ . Press Ctrl-C to stop the app; database data is retained.'
wait
