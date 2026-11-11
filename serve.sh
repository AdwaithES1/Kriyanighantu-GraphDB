#!/bin/sh
# Linux start: start Neo4j (if installed by setup_linux.sh), load the graph into an empty database,
# and serve the app on the network. Settings come from the environment or .env:
#   APP_PORT (default 5006), WORKERS (2), APP_HOST (0.0.0.0), NEO4J_BOLT_PORT (7693), NEO4J_* connection settings.
set -e
cd "$(dirname "$0")"

PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python

# Value of KEY from the environment, else .env, else DEFAULT.
env_value() {
    eval "current=\${$1:-}"
    [ -n "$current" ] && { echo "$current"; return; }
    value=$(grep "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r ')
    echo "${value:-$2}"
}

# Succeeds if something is already listening on 127.0.0.1:PORT.
port_busy() {
    "$PY" -c "import socket,sys; s=socket.socket(); sys.exit(s.connect_ex(('127.0.0.1', int(sys.argv[1]))) != 0)" "$1"
}

# Succeeds if this project's Neo4j is running. A finished process left as a zombie (containers without an
# init process do not clean these up) counts as stopped.
NEO4J_PID=.linux/neo4j/run/neo4j.pid
neo4j_running() {
    [ -f "$NEO4J_PID" ] || return 1
    state=$(awk '{print $3}' "/proc/$(cat "$NEO4J_PID")/stat" 2>/dev/null)
    [ -n "$state" ] && [ "$state" != Z ]
}

APP_PORT=$(env_value APP_PORT 5006)
WORKERS=$(env_value WORKERS 2)
if port_busy "$APP_PORT"; then
    echo "Port $APP_PORT is already in use by another program. Choose a free port with APP_PORT=... in .env"
    exit 1
fi

# Neo4j installed by setup_linux.sh: start it if it is not running (no systemd needed).
if [ -d .linux/neo4j ]; then
    export JAVA_HOME="$PWD/.linux/jdk" NEO4J_HOME="$PWD/.linux/neo4j"
    BOLT_PORT=$(env_value NEO4J_BOLT_PORT 7693)
    HTTP_PORT=$(env_value NEO4J_HTTP_PORT 7480)
    export NEO4J_URI="bolt://localhost:$BOLT_PORT"
    if ! neo4j_running; then
        rm -f "$NEO4J_PID"   # stale, e.g. after a crash
        for port in "$BOLT_PORT" "$HTTP_PORT"; do
            if port_busy "$port"; then
                echo "Neo4j port $port is already in use by another program."
                echo "Set NEO4J_BOLT_PORT / NEO4J_HTTP_PORT to free ports in .env, run: sh setup_linux.sh, then start again."
                exit 1
            fi
        done
        grep -q "^server.bolt.listen_address=127.0.0.1:$BOLT_PORT$" .linux/neo4j/conf/neo4j.conf || {
            echo "Neo4j is not configured for port $BOLT_PORT yet. Run: sh setup_linux.sh"; exit 1; }
        .linux/neo4j/bin/neo4j start
    fi
fi

[ -f output/graph.json ] || "$PY" pipeline/build_graph.py
"$PY" pipeline/load_neo4j.py --if-empty --wait 180

echo "Serving on http://${APP_HOST:-0.0.0.0}:$APP_PORT"
exec "$PY" -m gunicorn --chdir webapp --bind "${APP_HOST:-0.0.0.0}:$APP_PORT" \
     --workers "$WORKERS" --timeout 120 --access-logfile - --pid "$PWD/.app.pid" app:app
