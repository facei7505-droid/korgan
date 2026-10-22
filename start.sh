#!/usr/bin/env sh
# Qorgan: one-command start on macOS/Linux (needs Docker running).
set -e
cd "$(dirname "$0")"
[ -d .git ] && git pull --ff-only || true
docker compose up --build -d
printf '[Qorgan] Waiting for the API'
i=0
until curl -fs http://localhost:8000/health >/dev/null; do
  i=$((i+1)); [ $i -gt 90 ] && { echo; docker compose logs api --tail 60; exit 1; }
  printf '.'; sleep 2
done
echo
echo "[Qorgan] Ready: http://localhost:5173/stage  (console: /console, API docs: http://localhost:8000/docs)"
(command -v open >/dev/null && open http://localhost:5173/stage) || (command -v xdg-open >/dev/null && xdg-open http://localhost:5173/stage) || true
