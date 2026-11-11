# Starts the project's private Neo4j Community server (bolt 7688, browser http://localhost:7475).
# Leave this window open while using the database; Ctrl+C stops it.
$project = $PSScriptRoot
$env:NEO4J_HOME = Join-Path $project ".neo4j\dist\neo4j-community-2025.12.1"
$env:NEO4J_CONF = Join-Path $project ".neo4j\conf"
$jdk = Join-Path $env:USERPROFILE ".Neo4jDesktop2\Cache\runtime\zulu21.44.17-ca-jdk21.0.8-win_x64"
if (Test-Path $jdk) { $env:JAVA_HOME = $jdk }
& (Join-Path $env:NEO4J_HOME "bin\neo4j.bat") console
