"""CSV → SQLite. Werte werden nicht korrigiert; leere Zellen werden NULL.

Stammdaten werden abgeglichen (einfügen/aktualisieren/entfernen), Beurteilungen
werden nur ergänzt und nie gelöscht. Alles läuft in einer Transaktion.

Aufruf: uv run python -m server.laden
"""
import csv
import sqlite3
from pathlib import Path

from server.db import daten_pfad, db_pfad, verbinden


class LadeFehler(Exception):
    pass


# Tabelle → (Primärschlüssel, {Spalte: Typ}); nicht genannte Spalten sind Text.
TABELLEN = {
    "liegenschaften": ("liegenschaft_id", {"baujahr": int, "letzte_sanierung": int}),
    "einheiten": ("einheit_id", {"zimmer": float, "flaeche_m2": float, "geschoss": int}),
    "mietverhaeltnisse": ("mietverhaeltnis_id", {"nettomiete_monat_chf": float, "nebenkosten_akonto_chf": float}),
    "offerten": ("offerte_id", {
        "angebotspreis_chf": int, "ertrag_laut_expose_chf": int, "wohnungen": int,
        "gewerbeeinheiten": int, "gewerbeflaeche_m2": float,
    }),
}
STAMMDATEN = list(TABELLEN)  # Reihenfolge: Eltern vor Kindern
BEURTEILUNGEN = "beurteilungen"


def _wert(roh: str, typ, tabelle: str, schluessel: str, spalte: str):
    if roh is None or roh.strip() == "":
        return None
    if typ is str:
        return roh
    try:
        return typ(roh)
    except ValueError:
        raise LadeFehler(
            f"{tabelle}: {schluessel}, Spalte {spalte}: '{roh}' ist keine gültige Zahl. Nicht geladen, nicht korrigiert."
        ) from None


def _lese_csv(pfad: Path, tabelle: str, pk: str, typen: dict) -> list[dict]:
    if not pfad.exists():
        raise LadeFehler(f"Datei fehlt: {pfad}")
    with open(pfad, encoding="utf-8-sig", newline="") as f:
        zeilen = list(csv.DictReader(f))
    gesehen = set()
    ergebnis = []
    for z in zeilen:
        schluessel = z.get(pk)
        if not schluessel:
            raise LadeFehler(f"{tabelle}: Zeile ohne {pk}: {z}")
        if schluessel in gesehen:
            raise LadeFehler(f"{tabelle}: {pk} {schluessel} kommt doppelt vor.")
        gesehen.add(schluessel)
        ergebnis.append({k: _wert(v, typen.get(k, str), tabelle, schluessel, k) for k, v in z.items()})
    return ergebnis


def _anzahl(con, tabelle) -> int:
    return con.execute(f"SELECT COUNT(*) FROM {tabelle}").fetchone()[0]


def laden(db: Path | str | None = None, daten: Path | str | None = None) -> dict:
    daten = Path(daten or daten_pfad())
    con = verbinden(db)
    con.isolation_level = None  # Transaktion selbst steuern
    bericht: dict[str, dict] = {}

    csv_daten = {t: _lese_csv(daten / f"{t}.csv", t, pk, typen) for t, (pk, typen) in TABELLEN.items()}
    beurteilungen = _lese_csv(daten / f"{BEURTEILUNGEN}.csv", BEURTEILUNGEN, "beurteilung_id", {})

    try:
        con.execute("BEGIN")
        for t in STAMMDATEN:
            bericht[t] = {"csv": len(csv_daten[t]), "vorher": _anzahl(con, t)}

        # 1. Einfügen/aktualisieren, Eltern zuerst
        for t in STAMMDATEN:
            pk, _ = TABELLEN[t]
            zeilen = csv_daten[t]
            if not zeilen:
                continue
            spalten = list(zeilen[0])
            platzhalter = ", ".join(f":{s}" for s in spalten)
            update = ", ".join(f"{s}=excluded.{s}" for s in spalten if s != pk)
            con.executemany(
                f"INSERT INTO {t} ({', '.join(spalten)}) VALUES ({platzhalter}) "
                f"ON CONFLICT({pk}) DO UPDATE SET {update}",
                zeilen,
            )

        # 2. Entfernen, was nicht mehr in der CSV steht – Kinder zuerst
        for t in reversed(STAMMDATEN):
            pk, _ = TABELLEN[t]
            behalten = {z[pk] for z in csv_daten[t]}
            vorhanden = {r[0] for r in con.execute(f"SELECT {pk} FROM {t}")}
            weg = sorted(vorhanden - behalten)
            if t == "offerten" and weg:
                blockiert = [
                    r[0] for r in con.execute(
                        f"SELECT DISTINCT offerte_id FROM beurteilungen WHERE offerte_id IN ({','.join('?' * len(weg))})", weg
                    )
                ]
                if blockiert:
                    raise LadeFehler(
                        f"Offerte(n) {', '.join(blockiert)} fehlen in offerten.csv, haben aber gespeicherte "
                        "Beurteilungen. Laden abgebrochen, nichts geändert."
                    )
            try:
                con.executemany(f"DELETE FROM {t} WHERE {pk} = ?", [(w,) for w in weg])
            except sqlite3.IntegrityError as e:
                raise LadeFehler(f"{t}: {', '.join(weg)} können nicht entfernt werden ({e}).") from None
            bericht[t]["entfernt"] = len(weg)

        # 3. Beurteilungen nur ergänzen
        vorher_b = _anzahl(con, BEURTEILUNGEN)
        neu = 0
        for z in beurteilungen:
            try:
                cur = con.execute(
                    "INSERT OR IGNORE INTO beurteilungen (beurteilung_id, offerte_id, erstellt_am, urteil, "
                    "begruendung, rote_flaggen, quelle_skill_version) VALUES (:beurteilung_id, :offerte_id, "
                    ":erstellt_am, :urteil, :begruendung, :rote_flaggen, :quelle_skill_version)",
                    z,
                )
            except sqlite3.IntegrityError as e:
                raise LadeFehler(f"beurteilungen: {z['beurteilung_id']} ungültig ({e}).") from None
            neu += cur.rowcount
        bericht[BEURTEILUNGEN] = {
            "csv": len(beurteilungen), "vorher": vorher_b, "neu_uebernommen": neu,
            "bereits_vorhanden": len(beurteilungen) - neu,
        }

        for t in bericht:
            bericht[t]["nachher"] = _anzahl(con, t)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    return bericht


def bericht_text(bericht: dict) -> str:
    zeilen = [f"{'Tabelle':<20}{'CSV':>6}{'vorher':>8}{'nachher':>9}  Details"]
    for t, b in bericht.items():
        extra = {k: v for k, v in b.items() if k not in ("csv", "vorher", "nachher")}
        details = ", ".join(f"{k}={v}" for k, v in extra.items())
        zeilen.append(f"{t:<20}{b['csv']:>6}{b['vorher']:>8}{b['nachher']:>9}  {details}")
    return "\n".join(zeilen)


if __name__ == "__main__":
    print(f"Daten: {daten_pfad()}\nDB:    {db_pfad()}\n")
    print(bericht_text(laden()))
