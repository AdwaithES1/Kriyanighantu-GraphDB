#!/bin/sh
# Stop the web app started by serve.sh and the Neo4j installed by setup_linux.sh.
# Only this project's processes are stopped, nothing else on the server.
cd "$(dirname "$0")"

if [ -f .app.pid ] && kill "$(cat .app.pid)" 2>/dev/null; then
    echo "Web app stopped."
else
    echo "Web app was not running."
fi
rm -f .app.pid

# A finished process left as a zombie (containers without an init process keep these) counts as stopped.
NEO4J_PID=.linux/neo4j/run/neo4j.pid
neo4j_running() {
    [ -f "$NEO4J_PID" ] || return 1
    state=$(awk '{print $3}' "/proc/$(cat "$NEO4J_PID")/stat" 2>/dev/null)
    [ -n "$state" ] && [ "$state" != Z ]
}

if neo4j_running; then
    pid=$(cat "$NEO4J_PID")
    printf "Stopping Neo4j"
    kill "$pid"                     # Neo4j shuts down cleanly on SIGTERM
    waited=0
    while neo4j_running && [ "$waited" -lt 120 ]; do
        sleep 1; waited=$((waited + 1)); printf "."
    done
    if neo4j_running; then
        echo " still running after 2 minutes; forcing it to stop."
        kill -9 "$pid" 2>/dev/null
    else
        echo " stopped."
    fi
else
    echo "Neo4j was not running."
fi
rm -f "$NEO4J_PID"
