#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="${ROOT}/.dev-pids"

if [ ! -f "$PID_FILE" ]; then
  echo "[dev-stop] No PID file found at $PID_FILE"
  echo "[dev-stop] Searching for uvicorn and pnpm processes..."
  pkill -f "uvicorn main:app" 2>/dev/null && echo "[dev-stop] Killed sandbox-svc" || echo "[dev-stop] No sandbox-svc found"
  pkill -f "pnpm dev" 2>/dev/null && echo "[dev-stop] Killed dashboard" || echo "[dev-stop] No dashboard found"
  exit 0
fi

echo "[dev-stop] Stopping dev processes..."
while read -r pid; do
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null && echo "[dev-stop] Killed PID $pid" || echo "[dev-stop] Failed to kill PID $pid"
  fi
done < "$PID_FILE"

rm -f "$PID_FILE"
echo "[dev-stop] Done"
