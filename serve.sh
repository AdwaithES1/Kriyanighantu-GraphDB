#!/bin/sh
# Linux / container start: build the graph if needed, load it into an empty Neo4j, serve the app on the network.
# Settings come from the environment or .env: NEO4J_*, APP_HOST (default 0.0.0.0), APP_PORT (5000), WORKERS (2).
set -e
cd "$(dirname "$0")"

PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python

# Neo4j installed by setup_linux.sh: start it if it is not running (no systemd needed).
if [ -d .linux/neo4j ]; then
    export JAVA_HOME="$PWD/.linux/jdk" NEO4J_HOME="$PWD/.linux/neo4j" NEO4J_URI=bolt://localhost:7687
    .linux/neo4j/bin/neo4j status > /dev/null 2>&1 || .linux/neo4j/bin/neo4j start
fi

[ -f output/graph.json ] || "$PY" pipeline/build_graph.py
"$PY" pipeline/load_neo4j.py --if-empty --wait 180

echo "Serving on http://${APP_HOST:-0.0.0.0}:${APP_PORT:-5000}"
exec "$PY" -m gunicorn --chdir webapp --bind "${APP_HOST:-0.0.0.0}:${APP_PORT:-5000}" \
     --workers "${WORKERS:-2}" --timeout 120 --access-logfile - app:app
