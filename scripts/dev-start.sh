#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="${ROOT}/.dev-pids"

cleanup() {
  echo "[dev-stop] Cleaning up..."
  if [ -f "$PID_FILE" ]; then
    while read -r pid; do
      kill "$pid" 2>/dev/null || true
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi
  echo "[dev-stop] Done"
}

trap cleanup EXIT INT TERM

# Kill any existing dev processes first
if [ -f "$PID_FILE" ]; then
  echo "[dev-start] Stopping existing dev processes..."
  while read -r pid; do
    kill "$pid" 2>/dev/null || true
  done < "$PID_FILE"
  rm -f "$PID_FILE"
fi

# Start sandbox-svc on :8080
echo "[dev-start] Starting sandbox-svc on :8080..."
cd "$ROOT/services/sandbox-svc"
uvicorn main:app --reload --port 8080 --host 0.0.0.0 &
SANDBOX_PID=$!
echo "$SANDBOX_PID" > "$PID_FILE"
echo "[dev-start] sandbox-svc PID: $SANDBOX_PID"

# Wait for sandbox-svc to be ready
echo "[dev-start] Waiting for sandbox-svc to be ready..."
for i in $(seq 1 30); do
  if curl -s http://localhost:8080/health >/dev/null 2>&1; then
    echo "[dev-start] sandbox-svc ready"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "[dev-start] WARNING: sandbox-svc not ready after 30s, continuing..."
  fi
  sleep 1
done

# Start dashboard on :3000
echo "[dev-start] Starting dashboard on :3000..."
cd "$ROOT/apps/dashboard"
pnpm dev &
DASHBOARD_PID=$!
echo "$DASHBOARD_PID" >> "$PID_FILE"
echo "[dev-start] dashboard PID: $DASHBOARD_PID"

echo ""
echo "[dev-start] Both services starting:"
echo "  Dashboard  -> http://localhost:3000"
echo "  Sandbox    -> http://localhost:8080"
echo "  Health     -> http://localhost:8080/health"
echo ""
echo "[dev-start] PID file: $PID_FILE"
echo "[dev-start] Press Ctrl+C to stop both services."

wait
