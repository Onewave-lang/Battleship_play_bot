#!/usr/bin/env bash
set -e

if [[ -z "$BOT_TOKEN" ]]; then
  echo "Error: BOT_TOKEN environment variable is not set." >&2
  exit 1
fi

if [[ -z "$WEBHOOK_URL" ]]; then
  echo "Error: WEBHOOK_URL environment variable is not set." >&2
  exit 1
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
