#!/bin/sh
# Linux / container start: build the graph if needed, load it into an empty Neo4j, serve the app on the network.
# Settings come from the environment or .env: NEO4J_*, APP_HOST (default 0.0.0.0), APP_PORT (5000), WORKERS (2).
set -e
cd "$(dirname "$0")"

PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python

[ -f output/graph.json ] || "$PY" pipeline/build_graph.py
"$PY" pipeline/load_neo4j.py --if-empty --wait 180

echo "Serving on http://${APP_HOST:-0.0.0.0}:${APP_PORT:-5000}"
exec "$PY" -m gunicorn --chdir webapp --bind "${APP_HOST:-0.0.0.0}:${APP_PORT:-5000}" \
     --workers "${WORKERS:-2}" --timeout 120 --access-logfile - app:app
