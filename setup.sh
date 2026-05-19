#!/usr/bin/env bash
set -euo pipefail

ONTOP_VERSION="5.5.0"
DUCKDB_JDBC_VERSION="1.1.3"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Setting up NL-to-SPARQL/SQL engine"
echo "    Project root: $PROJECT_DIR"

# ── 1. Python dependencies ──────────────────────────────────────────────────
echo ""
echo "==> Installing Python dependencies..."
pip3 install -r "$PROJECT_DIR/requirements.txt" --quiet

# ── 2. Download Ontop CLI ───────────────────────────────────────────────────
ONTOP_DIR="$PROJECT_DIR/ontop-cli"
if [ ! -f "$ONTOP_DIR/ontop" ]; then
    echo ""
    echo "==> Downloading Ontop CLI v$ONTOP_VERSION..."
    ZIP="$PROJECT_DIR/ontop-cli.zip"
    curl -L --progress-bar \
        "https://github.com/ontop/ontop/releases/download/ontop-$ONTOP_VERSION/ontop-cli-$ONTOP_VERSION.zip" \
        -o "$ZIP"
    mkdir -p "$ONTOP_DIR"
    unzip -q "$ZIP" -d "$ONTOP_DIR"
    rm -f "$ZIP"
    # The script may be at root or inside a versioned subfolder
    if [ ! -f "$ONTOP_DIR/ontop" ]; then
        SUBDIR="$(find "$ONTOP_DIR" -maxdepth 1 -mindepth 1 -type d | head -1)"
        if [ -n "$SUBDIR" ] && [ -f "$SUBDIR/ontop" ]; then
            mv "$SUBDIR"/* "$ONTOP_DIR/"
            rmdir "$SUBDIR"
        fi
    fi
    chmod +x "$ONTOP_DIR/ontop"
    echo "    Ontop CLI extracted to: $ONTOP_DIR"
else
    echo "==> Ontop CLI already present, skipping download."
fi

# ── 3. Download DuckDB JDBC driver ─────────────────────────────────────────
JDBC_JAR="$PROJECT_DIR/ontop/jdbc/duckdb_jdbc-$DUCKDB_JDBC_VERSION.jar"
if [ ! -f "$JDBC_JAR" ]; then
    echo ""
    echo "==> Downloading DuckDB JDBC driver v$DUCKDB_JDBC_VERSION..."
    curl -L --progress-bar \
        "https://repo1.maven.org/maven2/org/duckdb/duckdb_jdbc/$DUCKDB_JDBC_VERSION/duckdb_jdbc-$DUCKDB_JDBC_VERSION.jar" \
        -o "$JDBC_JAR"
    echo "    JDBC JAR saved to: $JDBC_JAR"
else
    echo "==> DuckDB JDBC driver already present, skipping download."
fi

# Copy JDBC JAR into ontop-cli/jdbc/ so Ontop can find the driver
if [ -d "$ONTOP_DIR/jdbc" ]; then
    cp "$JDBC_JAR" "$ONTOP_DIR/jdbc/"
    echo "    Copied JDBC JAR to: $ONTOP_DIR/jdbc/"
fi

# ── 4. Initialise DuckDB database ──────────────────────────────────────────
DB_FILE="$PROJECT_DIR/university.ddb"
echo ""
echo "==> Initialising DuckDB database..."
python3 - <<PYEOF
import duckdb, os
db_path = "$DB_FILE"
sql_path = "$PROJECT_DIR/data/university.sql"
if os.path.exists(db_path):
    os.remove(db_path)
con = duckdb.connect(db_path)
with open(sql_path) as f:
    raw = f.read()
for stmt in raw.split(";"):
    stmt = stmt.strip()
    code_lines = [l for l in stmt.splitlines() if l.strip() and not l.strip().startswith("--")]
    if code_lines:
        con.execute(stmt)
con.close()
print(f"    Database written to: {db_path}")
PYEOF

# ── 5. Verify table row counts ─────────────────────────────────────────────
python3 - <<PYEOF
import duckdb
con = duckdb.connect("$DB_FILE", read_only=True)
tables = ["student", "academic", "course", "teaching", "course_registration"]
for t in tables:
    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"    {t:25s}: {n} rows")
con.close()
PYEOF

# ── 6. Update database.properties with absolute path ──────────────────────
PROPS="$PROJECT_DIR/ontop/database.properties"
# Replace the jdbc.url line with absolute path to the .ddb file
sed -i.bak "s|jdbc.url=.*|jdbc.url=jdbc:duckdb:$DB_FILE|" "$PROPS"
rm -f "$PROPS.bak"
echo ""
echo "    Updated ontop/database.properties with absolute DB path."

# ── Done ────────────────────────────────────────────────────────────────────
echo ""
echo "================================================================"
echo " Setup complete!"
echo "================================================================"
echo ""
echo " Next steps:"
echo ""
echo " 1. Start the Ontop SPARQL endpoint (in a separate terminal):"
echo ""
echo "    cd $PROJECT_DIR"
echo "    ./ontop-cli/ontop endpoint \\"
echo "        -m ontop/university.obda \\"
echo "        -t ontop/university.ttl \\"
echo "        -p ontop/database.properties \\"
echo "        --cors-allowed-origins='*'"
echo ""
echo "    SPARQL UI will be at: http://localhost:8080/"
echo ""
echo " 2. Set your Anthropic API key:"
echo "    export ANTHROPIC_API_KEY=your_key_here"
echo ""
echo " 3. Ask a question:"
echo "    python src/nl_query.py \"List all students\""
echo "    python src/nl_query.py \"Which professors teach more than one course?\""
echo "    python src/nl_query.py \"Who is enrolled in Database Systems?\""
echo ""
