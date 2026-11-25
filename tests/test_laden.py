import hashlib

import pytest

from server.abfragen import beurteilung_speichern
from server.db import verbinden
from server.laden import LadeFehler, laden
from tests.conftest import DATEN

CSV_ZEILEN = {
    "liegenschaften": 12,
    "einheiten": 166,
    "mietverhaeltnisse": 158,
    "offerten": 6,
    "beurteilungen": 0,
}


def test_erstes_laden_meldet_vorher_und_nachher(db_pfad):
    bericht = laden(db_pfad, DATEN)
    for tabelle, n in CSV_ZEILEN.items():
        assert bericht[tabelle]["csv"] == n, tabelle
        assert bericht[tabelle]["vorher"] == 0, tabelle
        assert bericht[tabelle]["nachher"] == n, tabelle


def test_zweites_laden_aendert_zeilenzahl_nicht(db_pfad):
    laden(db_pfad, DATEN)
    bericht = laden(db_pfad, DATEN)
    for tabelle, n in CSV_ZEILEN.items():
        assert bericht[tabelle]["vorher"] == n, tabelle
        assert bericht[tabelle]["nachher"] == n, tabelle


def test_werte_werden_nicht_korrigiert(con):
    q = lambda sql, *a: con.execute(sql, a).fetchone()[0]
    assert q("SELECT ort FROM liegenschaften WHERE liegenschaft_id='L04'") == "Zuerich"
    assert q("SELECT letzte_sanierung FROM liegenschaften WHERE liegenschaft_id='L04'") is None
    assert q("SELECT flaeche_m2 FROM einheiten WHERE einheit_id='E093'") == 0
    assert q("SELECT zimmer FROM einheiten WHERE einheit_id='E015'") is None
    assert q("SELECT mietende FROM mietverhaeltnisse WHERE mietverhaeltnis_id='M013'") == "2019-06-30"
    assert q("SELECT ertrag_laut_expose_chf FROM offerten WHERE offerte_id='O-2026-018'") == 0
    assert q("SELECT vermietungsstand_laut_expose FROM offerten WHERE offerte_id='O-2026-018'") is None
    assert q("SELECT plz FROM liegenschaften WHERE liegenschaft_id='L12'") == "1201"
    # Beide laufenden Mietverhältnisse von E006 bleiben erhalten
    assert q("SELECT COUNT(*) FROM mietverhaeltnisse WHERE einheit_id='E006'") == 2


def test_rohdaten_bleiben_unveraendert(db_pfad):
    def hashes():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in DATEN.glob("*.csv")}

    vorher = hashes()
    laden(db_pfad, DATEN)
    laden(db_pfad, DATEN)
    assert hashes() == vorher


def test_neuladen_loescht_keine_beurteilungen(geladen):
    con = verbinden(geladen)
    beurteilung_speichern(con, "O-2026-015", "weiterverfolgen", "Lage passt", ["Heizung Öl?"], "v1")
    con.close()

    bericht = laden(geladen, DATEN)
    assert bericht["beurteilungen"]["vorher"] == 1
    assert bericht["beurteilungen"]["nachher"] == 1

    con = verbinden(geladen)
    zeile = con.execute("SELECT offerte_id, urteil FROM beurteilungen").fetchone()
    assert tuple(zeile) == ("O-2026-015", "weiterverfolgen")


def test_beurteilung_aus_csv_wird_nur_einmal_uebernommen(db_pfad, daten_kopie):
    with open(daten_kopie / "beurteilungen.csv", "a", encoding="utf-8", newline="") as f:
        f.write('B-CSV-1,O-2026-014,2026-10-15,zurückstellen,Preis zu hoch,"[""Preis""]",v0\r\n')
    erst = laden(db_pfad, daten_kopie)
    zweit = laden(db_pfad, daten_kopie)
    assert erst["beurteilungen"]["csv"] == 1
    assert erst["beurteilungen"]["nachher"] == 1
    assert zweit["beurteilungen"]["vorher"] == 1
    assert zweit["beurteilungen"]["nachher"] == 1


def test_offerte_mit_beurteilung_darf_nicht_verschwinden(db_pfad, daten_kopie):
    laden(db_pfad, daten_kopie)
    con = verbinden(db_pfad)
    beurteilung_speichern(con, "O-2026-019", "ablehnen", "Dublette", [], None)
    con.close()

    pfad = daten_kopie / "offerten.csv"
    zeilen = pfad.read_text(encoding="utf-8").splitlines(keepends=True)
    pfad.write_text("".join(z for z in zeilen if not z.startswith("O-2026-019")), encoding="utf-8")

    with pytest.raises(LadeFehler, match="O-2026-019"):
        laden(db_pfad, daten_kopie)

    # Transaktion zurückgerollt: alles wie vorher
    con = verbinden(db_pfad)
    assert con.execute("SELECT COUNT(*) FROM offerten").fetchone()[0] == 6
    assert con.execute("SELECT COUNT(*) FROM beurteilungen").fetchone()[0] == 1


def test_unlesbare_zahl_bricht_ab_statt_zu_raten(db_pfad, daten_kopie):
    pfad = daten_kopie / "einheiten.csv"
    text = pfad.read_text(encoding="utf-8").replace("E001,L01,Whg 1.1,Wohnen,4.5,101,0", "E001,L01,Whg 1.1,Wohnen,4.5,ca. 100,0")
    pfad.write_text(text, encoding="utf-8")
    with pytest.raises(LadeFehler, match="E001"):
        laden(db_pfad, daten_kopie)
