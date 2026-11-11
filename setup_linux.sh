#!/bin/sh
# One-time setup on Linux WITHOUT Docker and without root (works inside a container too).
# Puts the Python packages in .venv and Java 21 + Neo4j in .linux/, and sets the Neo4j password from .env.
# Then start everything with ./serve.sh
set -e
cd "$(dirname "$0")"

NEO4J_VERSION=2025.12.1
case "$(uname -m)" in aarch64|arm64) ARCH=aarch64 ;; *) ARCH=x64 ;; esac
JDK_URL="https://api.adoptium.net/v3/binary/latest/21/ga/linux/$ARCH/jdk/hotspot/normal/eclipse"
NEO4J_URL="https://dist.neo4j.org/neo4j-community-$NEO4J_VERSION-unix.tar.gz"

[ -f .env ] || { echo "First run: cp .env.example .env   and set NEO4J_PASSWORD"; exit 1; }
PASSWORD=$(grep '^NEO4J_PASSWORD=' .env | cut -d= -f2-)
[ ${#PASSWORD} -ge 8 ] || { echo "NEO4J_PASSWORD in .env must be at least 8 characters"; exit 1; }

echo "== 1/3 Python packages (.venv)"
# The system Python refuses pip installs (PEP 668), so everything goes into a virtual environment.
if [ ! -x .venv/bin/python ]; then
    if ! python3 -m venv .venv 2>/dev/null; then
        echo "python3-venv is not installed; creating the venv without it"
        rm -rf .venv
        python3 -m venv --without-pip .venv
        curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python - -q
    fi
fi
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt

echo "== 2/3 Java 21 and Neo4j $NEO4J_VERSION in .linux/ (about 400 MB download)"
mkdir -p .linux
if [ ! -d .linux/jdk ]; then
    curl -fL --progress-bar "$JDK_URL" | tar xz -C .linux
    mv .linux/jdk-21* .linux/jdk
fi
if [ ! -d .linux/neo4j ]; then
    curl -fL --progress-bar "$NEO4J_URL" | tar xz -C .linux
    mv .linux/neo4j-community-* .linux/neo4j
    printf '\nserver.memory.heap.max_size=1g\nserver.memory.pagecache.size=512m\n' >> .linux/neo4j/conf/neo4j.conf
fi

echo "== 3/3 Neo4j password and graph"
export JAVA_HOME="$PWD/.linux/jdk" NEO4J_HOME="$PWD/.linux/neo4j"
if [ ! -d .linux/neo4j/data/databases/system ]; then  # only possible before the first start
    .linux/neo4j/bin/neo4j-admin dbms set-initial-password "$PASSWORD"
fi
.venv/bin/python pipeline/build_graph.py > /dev/null

echo "Setup done. Start the app with:  ./serve.sh"
