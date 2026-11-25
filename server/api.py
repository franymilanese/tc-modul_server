"""FastAPI: nur Leseendpunkte. Optional wird der MCP-Server unter /mcp eingehängt.

Die Leseendpunkte liegen unter /api (für das Dashboard in tc-client) und
weiterhin ohne Präfix. CORS erlaubt nur GET von lokalen Seiten
(localhost / 127.0.0.1, beliebiger Port)."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from server import abfragen
from server.db import verbinden


def erstelle_app(db: Path | str | None = None, mit_mcp: bool = False) -> FastAPI:
    mcp = None
    if mit_mcp:
        from server.mcp_server import erstelle_mcp
        mcp = erstelle_mcp(db)
        mcp_app = mcp.streamable_http_app(streamable_http_path="/mcp")

    @asynccontextmanager
    async def lifespan(_app):
        if mcp is None:
            yield
        else:
            async with mcp.session_manager.run():
                yield

    app = FastAPI(title="Offertenregister", description="Leseendpunkte. Jede Antwort enthält zeilen_basis.",
                  lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["GET"],
    )
    router = APIRouter()

    def aufruf(f, *args, **kwargs):
        con = verbinden(db)
        try:
            return f(con, *args, **kwargs)
        except abfragen.NichtGefunden as e:
            raise HTTPException(404, str(e)) from None
        except abfragen.AbfrageFehler as e:
            raise HTTPException(422, str(e)) from None
        finally:
            con.close()

    @router.get("/liegenschaften")
    def liegenschaften(ort: str | None = None, plz: str | None = None, nutzung: str | None = None):
        return aufruf(abfragen.portfolio_suchen, ort=ort, plz=plz, nutzung=nutzung)

    @router.get("/liegenschaften/{liegenschaft_id}")
    def liegenschaft(liegenschaft_id: str, stichtag: str | None = None):
        return aufruf(abfragen.liegenschaft_details, liegenschaft_id, stichtag=stichtag)

    @router.get("/offerten")
    def offerten(status: str | None = None):
        return aufruf(abfragen.offerten_liste, status=status)

    @router.get("/offerten/{offerte_id}/beurteilungen")
    def beurteilungen(offerte_id: str):
        return aufruf(abfragen.beurteilungen_liste, offerte_id)

    app.include_router(router, prefix="/api")
    app.include_router(router, include_in_schema=False)  # bisherige Pfade ohne Präfix

    if mcp is not None:
        app.mount("/", mcp_app)  # nach den API-Routen, damit diese Vorrang haben
    return app
