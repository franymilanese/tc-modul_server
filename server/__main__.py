"""Startet FastAPI (Leseendpunkte) und den MCP-Server unter /mcp.

uv run python -m server   (Host/Port über TC_HOST / TC_PORT, DB über TC_DB_PFAD)
"""
import os
import sys

import uvicorn

from server.api import erstelle_app
from server.db import db_pfad


def main():
    if not db_pfad().exists():
        sys.exit(f"Keine Datenbank unter {db_pfad()}. Zuerst laden: uv run python -m server.laden")
    host = os.environ.get("TC_HOST", "127.0.0.1")
    port = int(os.environ.get("TC_PORT", "8001"))
    print(f"API: http://{host}:{port}/docs   MCP: http://{host}:{port}/mcp")
    uvicorn.run(erstelle_app(mit_mcp=True), host=host, port=port)


if __name__ == "__main__":
    main()
