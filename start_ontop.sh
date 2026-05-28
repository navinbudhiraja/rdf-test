#!/usr/bin/env bash
# Start an Ontop SPARQL endpoint (runs in foreground — Ctrl+C to stop).
#
# Usage:
#   ./start_ontop.sh            # university dataset on port 8080 (default)
#   ./start_ontop.sh university # same
#   ./start_ontop.sh hr         # AcmeCorp HR dataset on port 8081
#
# The two datasets are independent: run each in its own terminal to query both.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATASET="${1:-university}"

case "$DATASET" in
    university)
        OBDA="university.obda" ; TTL="university.ttl"
        PROPS="database.properties" ; PORT=8080 ;;
    hr)
        OBDA="hr.obda" ; TTL="hr.ttl"
        PROPS="hr_database.properties" ; PORT=8081 ;;
    *)
        echo "Unknown dataset: $DATASET (expected 'university' or 'hr')" >&2
        exit 1 ;;
esac

export JAVA_HOME="${JAVA_HOME:-$HOME/java/jdk-21.0.11+10/Contents/Home}"
export PATH="$JAVA_HOME/bin:$PATH"

# Give the rewriter enough heap; G1GC handles large-object allocation better
# than the default GC for Ontop's SPARQL-to-SQL term trees.
export ONTOP_JAVA_ARGS="${ONTOP_JAVA_ARGS:--Xmx2g -XX:+UseG1GC -XX:MaxGCPauseMillis=200}"

if ! command -v java &>/dev/null; then
    echo "Error: Java not found. Run ./setup.sh first."
    exit 1
fi

if [ ! -f "$PROJECT_DIR/ontop-cli/ontop" ]; then
    echo "Error: Ontop CLI not found. Run ./setup.sh first."
    exit 1
fi

# Kill only an existing endpoint for THIS dataset (scoped to its mapping file),
# so the two datasets don't kill each other. The Java cmdline contains
# "endpoint -m .../<dataset>.obda", so match on that (DuckDB allows only one
# process to hold the .ddb file lock).
if pgrep -f "endpoint.*$OBDA" &>/dev/null; then
    echo "Stopping existing Ontop process for '$DATASET'..."
    pkill -9 -f "endpoint.*$OBDA"
    sleep 2
fi

echo "Starting Ontop SPARQL endpoint for '$DATASET' at http://localhost:$PORT/"
echo "Press Ctrl+C to stop."
echo ""

exec "$PROJECT_DIR/ontop-cli/ontop" endpoint \
    -m "$PROJECT_DIR/ontop/$OBDA" \
    -t "$PROJECT_DIR/ontop/$TTL" \
    -p "$PROJECT_DIR/ontop/$PROPS" \
    --port "$PORT" \
    --cors-allowed-origins='*'
