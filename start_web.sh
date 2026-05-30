#!/usr/bin/env bash
# Start the AcmeCorp HR Web Chat (FastAPI + uvicorn), using the project's venv.
#
# Usage:
#   ./start_web.sh           # serve on http://localhost:8000/
#   ./start_web.sh 9000      # serve on a different port
#
# Requires ANTHROPIC_API_KEY in .env and the HR Ontop endpoint on :8081
# (start it in another terminal:  ./start_ontop.sh hr).
#
# Runs in the foreground — Ctrl+C to stop. Single worker on purpose: the in-memory
# conversation state is not shared across workers.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${1:-8000}"

# Prefer the project venv so uvicorn / deps are found without activating it.
if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/.venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    PYTHON="python"
fi

if ! "$PYTHON" -c "import uvicorn, fastapi" &>/dev/null; then
    echo "Error: uvicorn/fastapi not installed for $PYTHON." >&2
    echo "Install deps:  $PYTHON -m pip install -r requirements.txt" >&2
    exit 1
fi

# Non-fatal heads-up if the HR SPARQL endpoint isn't reachable.
if ! curl -s -o /dev/null --max-time 2 "http://localhost:8081/sparql" 2>/dev/null; then
    echo "Warning: HR Ontop endpoint not reachable on :8081 — ask_hr will report"
    echo "         'Results unavailable'. Start it with:  ./start_ontop.sh hr"
    echo ""
fi

echo "Starting HR Web Chat at http://localhost:$PORT/  (Ctrl+C to stop)"
echo ""

cd "$PROJECT_DIR"
exec "$PYTHON" -m uvicorn web:app --app-dir src --port "$PORT"
