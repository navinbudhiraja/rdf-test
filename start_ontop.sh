#!/usr/bin/env bash
# Start the Ontop SPARQL endpoint (runs in foreground — Ctrl+C to stop)
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

export JAVA_HOME="${JAVA_HOME:-$HOME/java/jdk-21.0.11+10/Contents/Home}"
export PATH="$JAVA_HOME/bin:$PATH"

if ! command -v java &>/dev/null; then
    echo "Error: Java not found. Run ./setup.sh first."
    exit 1
fi

if [ ! -f "$PROJECT_DIR/ontop-cli/ontop" ]; then
    echo "Error: Ontop CLI not found. Run ./setup.sh first."
    exit 1
fi

# Kill any existing Ontop process holding the DuckDB lock
if pgrep -f "ontop endpoint" &>/dev/null; then
    echo "Stopping existing Ontop process..."
    pkill -9 -f "ontop endpoint"
    sleep 1
fi

echo "Starting Ontop SPARQL endpoint at http://localhost:8080/"
echo "Press Ctrl+C to stop."
echo ""

exec "$PROJECT_DIR/ontop-cli/ontop" endpoint \
    -m "$PROJECT_DIR/ontop/university.obda" \
    -t "$PROJECT_DIR/ontop/university.ttl" \
    -p "$PROJECT_DIR/ontop/database.properties" \
    --cors-allowed-origins='*'
