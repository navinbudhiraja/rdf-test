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



python3 "$PROJECT_DIR/src/nl_query.py" --dataset hr "$@"
