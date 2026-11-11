#!/bin/sh
# Setup on Linux without root or Docker (works inside a container too).
# Puts the Python packages in .venv and Java 21 + Neo4j in .linux/, sets the Neo4j password and ports from .env.
# Safe to run again: downloads are skipped, and ports are re-applied (e.g. after changing them in .env).
# Then start everything with:  sh serve.sh
set -e
cd "$(dirname "$0")"

NEO4J_VERSION=2025.12.1
case "$(uname -m)" in aarch64|arm64) ARCH=aarch64 ;; *) ARCH=x64 ;; esac
JDK_URL="https://api.adoptium.net/v3/binary/latest/21/ga/linux/$ARCH/jdk/hotspot/normal/eclipse"
NEO4J_URL="https://dist.neo4j.org/neo4j-community-$NEO4J_VERSION-unix.tar.gz"

# Value of KEY from the environment, else .env, else DEFAULT.
env_value() {
    eval "current=\${$1:-}"
    [ -n "$current" ] && { echo "$current"; return; }
    value=$(grep "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r')
    echo "${value:-$2}"
}

[ -f .env ] || { echo "First run: cp .env.example .env   and set NEO4J_PASSWORD"; exit 1; }
PASSWORD=$(env_value NEO4J_PASSWORD "")
[ ${#PASSWORD} -ge 8 ] || { echo "NEO4J_PASSWORD in .env must be at least 8 characters"; exit 1; }
BOLT_PORT=$(env_value NEO4J_BOLT_PORT 7693)
HTTP_PORT=$(env_value NEO4J_HTTP_PORT 7480)

echo "== 1/4 Python packages (.venv)"
# The system Python refuses pip installs (PEP 668), so everything goes into a virtual environment.
if [ ! -x .venv/bin/python ]; then
    if ! python3 -m venv .venv 2>/dev/null; then
        echo "python3-venv is not installed; creating the venv without it"
        rm -rf .venv
        python3 -m venv --without-pip .venv
        curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python - -q
    fi
fi
# Retry a few times: large downloads on a busy network can drop.
for attempt in 1 2 3; do
    .venv/bin/python -m pip install -q --retries 10 --timeout 60 --upgrade pip \
        && .venv/bin/python -m pip install -q --retries 10 --timeout 60 -r requirements.txt && break
    [ "$attempt" = 3 ] && { echo "Installing Python packages failed. Check the network and run setup_linux.sh again."; exit 1; }
    echo "Retrying in 10 s..."; sleep 10
done

# Download URL to .linux/NAME.tar.gz (resuming after drops), extract it, and rename its top folder to .linux/NAME.
fetch() {
    name=$1; url=$2
    for attempt in 1 2 3 4 5 6; do
        curl -fL -C - --progress-bar -o ".linux/$name.tar.gz" "$url" && break
        [ "$attempt" = 6 ] && { echo "Download of $name failed. Check the network and run setup_linux.sh again."; exit 1; }
        echo "Download interrupted; resuming in 5 s..."; sleep 5
    done
    rm -rf .linux/unpack && mkdir .linux/unpack
    tar xzf ".linux/$name.tar.gz" -C .linux/unpack || {
        rm -rf .linux/unpack ".linux/$name.tar.gz"
        echo "The $name download was damaged and has been deleted. Run setup_linux.sh again."; exit 1; }
    mv .linux/unpack/* ".linux/$name"
    rm -rf .linux/unpack ".linux/$name.tar.gz"
}

echo "== 2/4 Java 21 and Neo4j $NEO4J_VERSION in .linux/ (about 400 MB download, first time only)"
mkdir -p .linux
[ -d .linux/jdk ] || fetch jdk "$JDK_URL"
[ -d .linux/neo4j ] || fetch neo4j "$NEO4J_URL"

echo "== 3/4 Neo4j settings: Bolt port $BOLT_PORT, browser port $HTTP_PORT (this machine only)"
CONF=.linux/neo4j/conf/neo4j.conf
sed -i -e '/^server\.memory\.heap\.max_size=/d' -e '/^server\.memory\.pagecache\.size=/d' \
       -e '/^server\.default_listen_address=/d' -e '/^server\.bolt\.listen_address=/d' \
       -e '/^server\.bolt\.advertised_address=/d' -e '/^server\.http\.listen_address=/d' \
       -e '/^server\.http\.advertised_address=/d' -e '/^server\.https\.enabled=/d' "$CONF"
cat >> "$CONF" <<EOF
server.memory.heap.max_size=1g
server.memory.pagecache.size=512m
server.default_listen_address=127.0.0.1
server.bolt.listen_address=127.0.0.1:$BOLT_PORT
server.bolt.advertised_address=localhost:$BOLT_PORT
server.http.listen_address=127.0.0.1:$HTTP_PORT
server.http.advertised_address=localhost:$HTTP_PORT
server.https.enabled=false
EOF
# Point the app at this Neo4j.
if grep -q '^NEO4J_URI=' .env; then
    sed -i "s|^NEO4J_URI=.*|NEO4J_URI=bolt://localhost:$BOLT_PORT|" .env
else
    echo "NEO4J_URI=bolt://localhost:$BOLT_PORT" >> .env
fi

echo "== 4/4 Neo4j password and graph"
export JAVA_HOME="$PWD/.linux/jdk" NEO4J_HOME="$PWD/.linux/neo4j"
if [ ! -d .linux/neo4j/data/databases/system ]; then  # only possible before the first start
    .linux/neo4j/bin/neo4j-admin dbms set-initial-password "$PASSWORD"
fi
.venv/bin/python pipeline/build_graph.py > /dev/null

echo "Setup done. Start the app with:  sh serve.sh"
