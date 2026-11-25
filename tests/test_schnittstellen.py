import anyio
import pytest
from fastapi.testclient import TestClient
from mcp import Client

from server.api import erstelle_app
from server.mcp_server import erstelle_mcp
from tests.conftest import STICHTAG

WERKZEUGE = {"portfolio_suchen", "liegenschaft_details", "offerten_liste", "beurteilung_speichern"}


# --- MCP --------------------------------------------------------------------

def mcp_aufruf(db, name, argumente):
    async def lauf():
        async with Client(erstelle_mcp(db)) as client:
            return await client.call_tool(name, argumente)
    return anyio.run(lauf)


def test_mcp_hat_genau_vier_werkzeuge(geladen):
    async def lauf():
        async with Client(erstelle_mcp(geladen)) as client:
            return await client.list_tools()
    tools = anyio.run(lauf).tools
    assert {t.name for t in tools} == WERKZEUGE
    assert all(t.description for t in tools)


@pytest.mark.parametrize(
    "name, argumente",
    [
        ("portfolio_suchen", {"ort": "Zürich"}),
        ("liegenschaft_details", {"liegenschaft_id": "L01", "stichtag": STICHTAG}),
        ("offerten_liste", {}),
        ("beurteilung_speichern", {
            "offerte_id": "O-2026-017", "urteil": "weiterverfolgen",
            "begruendung": "Rendite plausibel", "rote_flaggen": [], "quelle_skill_version": "t",
        }),
    ],
)
def test_mcp_werkzeuge_liefern_zeilen_basis(geladen, name, argumente):
    r = mcp_aufruf(geladen, name, argumente)
    assert not r.is_error, r.content
    assert "zeilen_basis" in r.structured_content


def test_mcp_l01_wert(geladen):
    r = mcp_aufruf(geladen, "liegenschaft_details", {"liegenschaft_id": "L01", "stichtag": STICHTAG})
    assert r.structured_content["ist_miete"]["chf_pro_m2_jahr"] == pytest.approx(356.87, abs=0.005)


def test_mcp_fehler_wird_gemeldet(geladen):
    r = mcp_aufruf(geladen, "beurteilung_speichern", {
        "offerte_id": "O-2026-017", "urteil": "super", "begruendung": "x", "rote_flaggen": [],
    })
    assert r.is_error


# --- FastAPI ----------------------------------------------------------------

@pytest.fixture
def api(geladen):
    with TestClient(erstelle_app(geladen)) as c:
        yield c


def test_api_leseendpunkte(api):
    r = api.get("/liegenschaften", params={"ort": "Zürich"})
    assert r.status_code == 200 and r.json()["zeilen_basis"]["treffer"] == 4

    r = api.get("/liegenschaften/L01", params={"stichtag": STICHTAG})
    assert r.status_code == 200 and r.json()["zeilen_basis"]["einheiten_in_berechnung"] == 11

    r = api.get("/offerten", params={"status": "neu"})
    assert r.status_code == 200 and r.json()["zeilen_basis"]["treffer"] == 5

    r = api.get("/offerten/O-2026-014/beurteilungen")
    assert r.status_code == 200 and r.json()["zeilen_basis"]["beurteilungen_zur_offerte"] == 0


def test_api_unbekannt_ist_404(api):
    assert api.get("/liegenschaften/L99").status_code == 404
    assert api.get("/offerten/O-1999-001/beurteilungen").status_code == 404


def test_api_ist_nur_lesend(api):
    assert api.post("/offerten", json={}).status_code == 405


def test_api_auch_unter_praefix(api):
    assert api.get("/api/offerten").json() == api.get("/offerten").json()
    r = api.get("/api/liegenschaften/L01", params={"stichtag": STICHTAG})
    assert r.status_code == 200 and r.json()["zeilen_basis"]["einheiten_in_berechnung"] == 11
    assert api.post("/api/offerten", json={}).status_code == 405


def test_cors_nur_lokal_und_nur_lesend(api):
    lokal = api.get("/api/offerten", headers={"Origin": "http://localhost:8080"})
    assert lokal.headers.get("access-control-allow-origin") == "http://localhost:8080"
    fremd = api.get("/api/offerten", headers={"Origin": "https://example.com"})
    assert "access-control-allow-origin" not in fremd.headers
    preflight = api.options("/api/offerten", headers={
        "Origin": "http://localhost:8080", "Access-Control-Request-Method": "POST"})
    assert preflight.status_code == 400
