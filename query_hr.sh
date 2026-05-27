#!/usr/bin/env bash
# Run a natural language query against the AcmeCorp HR dataset (SPARQL-only).
# Usage: ./query_hr.sh "your question here"
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ $# -eq 0 ]; then
    echo "Usage: ./query_hr.sh \"<your question>\""
    echo ""
    echo "Examples:"
    echo "  ./query_hr.sh \"Which employees are software engineers across all subsidiaries?\""
    echo "  ./query_hr.sh \"Show the reporting chain for Alice Chen\""
    echo "  ./query_hr.sh \"Which role mappings need review?\""
    echo "  ./query_hr.sh \"What does AcmeDE call the role AcmeUK calls Senior Software Engineer?\""
    exit 1
fi

# Check the HR Ontop endpoint is listening on port 8081 using a raw TCP probe
# (not an HTTP request), so the server logs nothing for the health check.
if ! (exec 3<>/dev/tcp/localhost/8081) 2>/dev/null; then
    echo "Error: HR Ontop endpoint is not running."
    echo "Start it first with: ./start_ontop.sh hr"
    exit 1
fi

python3 "$PROJECT_DIR/src/nl_query.py" --dataset hr "$@"
