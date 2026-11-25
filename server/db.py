"""SQLite-Schema und Verbindung."""
import os
import sqlite3
from pathlib import Path

PROJEKT = Path(__file__).resolve().parents[1]
STANDARD_DB = PROJEKT / "offertenregister.db"
STANDARD_DATEN = PROJEKT.parent / "data"

URTEILE = ("weiterverfolgen", "zurückstellen", "ablehnen")


def db_pfad() -> Path:
    return Path(os.environ.get("TC_DB_PFAD", STANDARD_DB))


def daten_pfad() -> Path:
    return Path(os.environ.get("TC_DATEN_PFAD", STANDARD_DATEN))


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS liegenschaften (
    liegenschaft_id   TEXT PRIMARY KEY,
    strasse           TEXT,
    plz               TEXT,
    ort               TEXT,
    kanton            TEXT,
    nutzung           TEXT,
    baujahr           INTEGER,
    letzte_sanierung  INTEGER,
    energietraeger    TEXT
);
CREATE TABLE IF NOT EXISTS einheiten (
    einheit_id      TEXT PRIMARY KEY,
    liegenschaft_id TEXT NOT NULL REFERENCES liegenschaften(liegenschaft_id),
    bezeichnung     TEXT,
    nutzung         TEXT,
    zimmer          REAL,
    flaeche_m2      REAL,
    geschoss        INTEGER
);
CREATE TABLE IF NOT EXISTS mietverhaeltnisse (
    mietverhaeltnis_id     TEXT PRIMARY KEY,
    einheit_id             TEXT NOT NULL REFERENCES einheiten(einheit_id),
    mieter                 TEXT,
    mietbeginn             TEXT,
    mietende               TEXT,
    nettomiete_monat_chf   REAL,
    nebenkosten_akonto_chf REAL,
    index_gebunden         TEXT
);
CREATE TABLE IF NOT EXISTS offerten (
    offerte_id                   TEXT PRIMARY KEY,
    eingang                      TEXT,
    strasse                      TEXT,
    plz                          TEXT,
    ort                          TEXT,
    objektart                    TEXT,
    angebotspreis_chf            INTEGER,
    ertrag_laut_expose_chf       INTEGER,
    wohnungen                    INTEGER,
    gewerbeeinheiten             INTEGER,
    gewerbeflaeche_m2            REAL,
    vermietungsstand_laut_expose TEXT,
    verkaeufer                   TEXT,
    status                       TEXT
);
CREATE TABLE IF NOT EXISTS beurteilungen (
    beurteilung_id       TEXT PRIMARY KEY,
    offerte_id           TEXT NOT NULL REFERENCES offerten(offerte_id),
    erstellt_am          TEXT NOT NULL,
    urteil               TEXT NOT NULL CHECK (urteil IN ({", ".join(repr(u) for u in URTEILE)})),
    begruendung          TEXT,
    rote_flaggen         TEXT,  -- JSON-Liste
    quelle_skill_version TEXT
);
"""


def verbinden(pfad: Path | str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(pfad or db_pfad())
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    return con
