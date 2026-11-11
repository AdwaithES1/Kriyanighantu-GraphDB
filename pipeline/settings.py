"""Neo4j connection settings: environment variables first, then the project's .env file."""
import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def connection():
    """Return (uri, (user, password), database)."""
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    values.update({k: v for k, v in os.environ.items() if k.startswith("NEO4J_")})
    return (values.get("NEO4J_URI", "bolt://localhost:7688"),
            (values.get("NEO4J_USER", "neo4j"), values["NEO4J_PASSWORD"]),
            values.get("NEO4J_DATABASE", "neo4j"))
