import pytest

from server.abfragen import (
    AbfrageFehler,
    beurteilung_speichern,
    beurteilungen_liste,
    liegenschaft_details,
    offerten_liste,
    portfolio_suchen,
)
from tests.conftest import STICHTAG


def ids(antwort, schluessel="liegenschaften", feld="liegenschaft_id"):
    return sorted(x[feld] for x in antwort[schluessel])


# --- portfolio_suchen -------------------------------------------------------

def test_suche_ohne_filter_liefert_alle(con):
    a = portfolio_suchen(con)
    assert len(a["liegenschaften"]) == 12
    assert a["zeilen_basis"]["liegenschaften"] == 12


def test_suche_zuerich_findet_auch_zuerich_ohne_umlaut(con):
    a = portfolio_suchen(con, ort="Zürich")
    assert ids(a) == ["L01", "L02", "L03", "L04"]
    l04 = next(x for x in a["liegenschaften"] if x["liegenschaft_id"] == "L04")
    assert l04["ort"] == "Zuerich"  # Originalwert, nicht korrigiert
    assert any("L04" in h and "Zuerich" in h for h in a["hinweise"])
    assert a["zeilen_basis"] == {"liegenschaften": 12, "treffer": 4}
    # Nur abweichende Schreibweise wird gemeldet, nicht Gross/klein
    klein = portfolio_suchen(con, ort="zürich")
    assert len(klein["hinweise"]) == 1 and "L04" in klein["hinweise"][0]


def test_suche_nach_plz_und_nutzung(con):
    assert ids(portfolio_suchen(con, plz="6300")) == ["L05", "L06"]
    assert ids(portfolio_suchen(con, nutzung="büro")) == ["L05", "L10"]
    assert ids(portfolio_suchen(con, ort="Zug", nutzung="Wohnen")) == ["L06"]


def test_suche_ohne_treffer_nennt_moegliche_werte(con):
    a = portfolio_suchen(con, nutzung="Hotel")
    assert a["liegenschaften"] == []
    assert a["zeilen_basis"]["treffer"] == 0
    assert "Wohnen mit Gewerbe" in a["moegliche_werte"]["nutzung"]


def test_fehlende_werte_bleiben_luecken(con):
    a = portfolio_suchen(con, plz="8057")
    assert a["liegenschaften"][0]["letzte_sanierung"] is None


# --- liegenschaft_details ---------------------------------------------------

def test_details_l01_miete_pro_m2(con):
    a = liegenschaft_details(con, "L01", stichtag=STICHTAG)
    k = a["ist_miete"]
    assert k["jahresmiete_chf"] == 315120
    assert k["flaeche_m2"] == 883
    assert k["chf_pro_m2_jahr"] == pytest.approx(356.87, abs=0.005)
    assert a["zeilen_basis"] == {"einheiten": 15, "mietverhaeltnisse": 14, "einheiten_in_berechnung": 11}
    assert a["stichtag"] == STICHTAG


def test_details_l01_luecken_und_konflikte(con):
    a = liegenschaft_details(con, "L01", stichtag=STICHTAG)
    luecken = {x["einheit_id"]: x["grund"] for x in a["luecken"]}
    assert set(luecken) == {"E006", "E007", "E011", "E015"}
    assert "2 laufende" in luecken["E006"]
    assert "kein laufendes" in luecken["E007"]

    einheiten = {e["einheit_id"]: e for e in a["einheiten"]}
    assert einheiten["E006"]["status"] == "konflikt"
    assert einheiten["E006"]["chf_pro_m2_jahr"] is None
    assert einheiten["E007"]["status"] == "leer"
    assert einheiten["E001"]["chf_pro_m2_jahr"] == pytest.approx(346.34, abs=0.005)
    m013 = next(m for m in einheiten["E015"]["mietverhaeltnisse"] if m["mietverhaeltnis_id"] == "M013")
    assert m013["zustand"] == "widersprüchlich"


def test_details_flaeche_null_ist_luecke(con):
    a = liegenschaft_details(con, "L08", stichtag=STICHTAG)
    luecken = {x["einheit_id"]: x["grund"] for x in a["luecken"]}
    assert set(luecken) == {"E093"}
    assert "Fläche" in luecken["E093"]
    assert a["zeilen_basis"]["einheiten_in_berechnung"] == 23
    assert a["ist_miete"]["chf_pro_m2_jahr"] == pytest.approx(210.74, abs=0.005)


def test_details_stichtag_bestimmt_laufend(con):
    heute = liegenschaft_details(con, "L03", stichtag=STICHTAG)
    frueher = liegenschaft_details(con, "L03", stichtag="2025-06-01")
    status = lambda a: {e["einheit_id"]: e["status"] for e in a["einheiten"]}["E050"]
    assert status(heute) == "leer"
    assert status(frueher) == "vermietet"
    assert heute["ist_miete"]["chf_pro_m2_jahr"] == pytest.approx(531.45, abs=0.005)


def test_details_ohne_stichtag_nimmt_heute(con):
    import datetime as dt
    assert liegenschaft_details(con, "L01")["stichtag"] == dt.date.today().isoformat()


def test_details_unbekannte_liegenschaft(con):
    with pytest.raises(AbfrageFehler, match="L99"):
        liegenschaft_details(con, "L99")


def test_details_ungueltiger_stichtag(con):
    with pytest.raises(AbfrageFehler, match="Stichtag"):
        liegenschaft_details(con, "L01", stichtag="25.11.2026")


# --- offerten_liste ---------------------------------------------------------

def test_offerten_alle(con):
    a = offerten_liste(con)
    assert len(a["offerten"]) == 6
    assert a["zeilen_basis"] == {"offerten": 6, "treffer": 6, "beurteilungen": 0}


def test_offerten_filter_status(con):
    a = offerten_liste(con, status="neu")
    assert len(a["offerten"]) == 5
    assert a["zeilen_basis"]["treffer"] == 5


def test_offerten_hinweise_statt_korrektur(con):
    o = {x["offerte_id"]: x for x in offerten_liste(con)["offerten"]}
    assert o["O-2026-018"]["ertrag_laut_expose_chf"] == 0
    assert o["O-2026-018"]["vermietungsstand_laut_expose"] is None
    h018 = " ".join(o["O-2026-018"]["hinweise"])
    assert "Ertrag" in h018 and "Vermietungsstand" in h018
    assert any("O-2026-019" in h for h in o["O-2026-014"]["hinweise"])
    assert any("O-2026-014" in h for h in o["O-2026-019"]["hinweise"])
    assert o["O-2026-015"]["hinweise"] == []


# --- beurteilung_speichern --------------------------------------------------

def test_beurteilung_speichern_und_zaehlen(con):
    a = beurteilung_speichern(con, "O-2026-016", "zurückstellen", "Leerstand klären", ["2 von 6 leer"], "skill-1.0")
    b = a["beurteilung"]
    assert b["offerte_id"] == "O-2026-016"
    assert b["rote_flaggen"] == ["2 von 6 leer"]
    assert b["beurteilung_id"] and b["erstellt_am"]
    assert a["zeilen_basis"] == {"beurteilungen_zur_offerte": 1}

    a2 = beurteilung_speichern(con, "O-2026-016", "ablehnen", "Zu teuer", [], "skill-1.0")
    assert a2["beurteilung"]["beurteilung_id"] != b["beurteilung_id"]
    assert a2["zeilen_basis"] == {"beurteilungen_zur_offerte": 2}

    liste = beurteilungen_liste(con, "O-2026-016")
    assert [x["urteil"] for x in liste["beurteilungen"]] == ["zurückstellen", "ablehnen"]
    assert offerten_liste(con)["zeilen_basis"]["beurteilungen"] == 2


@pytest.mark.parametrize("urteil", ["gut", "", "Ablehnen ", "kaufen"])
def test_beurteilung_nur_feste_urteile(con, urteil):
    with pytest.raises(AbfrageFehler, match="urteil"):
        beurteilung_speichern(con, "O-2026-016", urteil, "x", [], None)


def test_beurteilung_unbekannte_offerte(con):
    with pytest.raises(AbfrageFehler, match="O-1999-001"):
        beurteilung_speichern(con, "O-1999-001", "ablehnen", "x", [], None)


def test_beurteilung_braucht_begruendung(con):
    with pytest.raises(AbfrageFehler, match="begruendung"):
        beurteilung_speichern(con, "O-2026-016", "ablehnen", "  ", [], None)


# --- Querschnitt: jede Antwort nennt ihre Zeilenbasis -----------------------

@pytest.mark.parametrize(
    "aufruf",
    [
        lambda c: portfolio_suchen(c, ort="Basel"),
        lambda c: liegenschaft_details(c, "L05", stichtag=STICHTAG),
        lambda c: offerten_liste(c),
        lambda c: beurteilungen_liste(c, "O-2026-014"),
        lambda c: beurteilung_speichern(c, "O-2026-014", "weiterverfolgen", "ok", [], None),
    ],
)
def test_jede_antwort_hat_zeilen_basis(con, aufruf):
    a = aufruf(con)
    assert isinstance(a["zeilen_basis"], dict) and a["zeilen_basis"]
    assert all(isinstance(v, int) for v in a["zeilen_basis"].values())
