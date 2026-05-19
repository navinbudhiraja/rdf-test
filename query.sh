#!/usr/bin/env bash
# Run a natural language query against the university dataset.
# Usage: ./query.sh "your question here"
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ $# -eq 0 ]; then
    echo "Usage: ./query.sh \"<your question>\""
    echo ""
    echo "Examples:"
    echo "  ./query.sh \"List all students\""
    echo "  ./query.sh \"Which professors teach more than one course?\""
    echo "  ./query.sh \"Who is enrolled in Database Systems?\""
    exit 1
fi

# Check Ontop is running
if ! curl -s http://localhost:8080/sparql -o /dev/null 2>/dev/null; then
    echo "Error: Ontop endpoint is not running."
    echo "Start it first with: ./start_ontop.sh"
    exit 1
fi

python3 "$PROJECT_DIR/src/nl_query.py" "$@"
