#!/bin/sh
# Linux / container start: build the graph if needed, load it into an empty Neo4j, serve the app on the network.
# Settings come from the environment or .env: NEO4J_*, APP_HOST (default 0.0.0.0), APP_PORT (5000), WORKERS (2).
set -e
cd "$(dirname "$0")"

PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python

# APP_PORT and WORKERS can also be set in .env (the environment wins).
if [ -f .env ]; then
    for key in APP_PORT WORKERS; do
        value=$(grep "^$key=" .env | tail -1 | cut -d= -f2- | tr -d '\r ')
        eval "current=\${$key:-}"
        [ -z "$current" ] && [ -n "$value" ] && export "$key=$value"
    done
fi

# Fail early with a clear message if the port is taken.
if "$PY" -c "import socket,sys; s=socket.socket(); sys.exit(s.connect_ex(('127.0.0.1', int(sys.argv[1]))) != 0)" "${APP_PORT:-5000}"; then
    echo "Port ${APP_PORT:-5000} is already in use by another program. Choose a free port with APP_PORT=... in .env"
    exit 1
fi

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
