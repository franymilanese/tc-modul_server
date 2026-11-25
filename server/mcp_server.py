"""MCP-Server mit vier Werkzeugen (Streamable HTTP, siehe server/__main__.py)."""
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from server import abfragen
from server.db import verbinden

HINWEIS = (
    " Jede Antwort enthält `zeilen_basis` (aus wie vielen Zeilen berechnet) und weist fehlende "
    "Werte als Lücke aus; nichts wird geschätzt."
)
NUR_LESEN = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


def erstelle_mcp(db: Path | str | None = None) -> MCPServer:
    mcp = MCPServer(
        name="offertenregister",
        instructions="Register für eingehende Kaufofferten und den eigenen Liegenschaftsbestand." + HINWEIS,
    )

    def mit_db(f, *args, **kwargs):
        con = verbinden(db)
        try:
            return f(con, *args, **kwargs)
        finally:
            con.close()

    @mcp.tool(annotations=NUR_LESEN, description=(
        "Eigene Liegenschaften suchen. Filter optional und kombinierbar: Ort (Umlaute/ue gleichwertig, "
        "Gross/klein egal), PLZ (exakt), Nutzung (exakt, z. B. 'Wohnen', 'Wohnen mit Gewerbe', 'Büro', "
        "'Gewerbe'). Ohne Treffer werden die möglichen Werte geliefert." + HINWEIS))
    def portfolio_suchen(ort: str | None = None, plz: str | None = None,
                         nutzung: str | None = None) -> dict[str, Any]:
        return mit_db(abfragen.portfolio_suchen, ort=ort, plz=plz, nutzung=nutzung)

    @mcp.tool(annotations=NUR_LESEN, description=(
        "Details einer eigenen Liegenschaft: Einheiten, Mietverhältnisse (laufend/beendet/zukünftig/"
        "widersprüchlich zum Stichtag) und Ist-Nettomiete pro m² und Jahr, je Einheit und gesamt. "
        "Stichtag im Format JJJJ-MM-TT, Standard heute. Leere Einheiten, Konflikte und Fläche 0 stehen "
        "unter `luecken`." + HINWEIS))
    def liegenschaft_details(liegenschaft_id: str, stichtag: str | None = None) -> dict[str, Any]:
        return mit_db(abfragen.liegenschaft_details, liegenschaft_id, stichtag=stichtag)

    @mcp.tool(annotations=NUR_LESEN, description=(
        "Eingegangene Kaufofferten mit Angaben laut Exposé, Hinweisen zu fehlenden oder auffälligen Werten "
        "(z. B. Ertrag 0, mögliche Dubletten) und Anzahl Beurteilungen. Optional nach Status filtern "
        "(z. B. 'neu', 'in Prüfung')." + HINWEIS))
    def offerten_liste(status: str | None = None) -> dict[str, Any]:
        return mit_db(abfragen.offerten_liste, status=status)

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False,
                                    openWorldHint=False),
        description=(
            "Urteil zu einer Offerte ablegen. Legt immer eine neue Beurteilung an, überschreibt nie. "
            "urteil: 'weiterverfolgen', 'zurückstellen' oder 'ablehnen'. begruendung ist Pflicht. "
            "rote_flaggen: Liste kurzer Texte. quelle_skill_version: Version des beurteilenden Skills."
        ))
    def beurteilung_speichern(
        offerte_id: str,
        urteil: Literal["weiterverfolgen", "zurückstellen", "ablehnen"],
        begruendung: str,
        rote_flaggen: list[str] | None = None,
        quelle_skill_version: str | None = None,
    ) -> dict[str, Any]:
        return mit_db(abfragen.beurteilung_speichern, offerte_id, urteil, begruendung,
                      rote_flaggen, quelle_skill_version)

    return mcp
