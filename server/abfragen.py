"""Fachlogik. Jede Antwort enthält `zeilen_basis` (aus wie vielen Zeilen sie
berechnet wurde). Fehlende oder unbrauchbare Werte werden nie geschätzt,
sondern unter `luecken` bzw. `hinweise` ausgewiesen."""
import datetime as dt
import json
import sqlite3
import uuid

from server.db import URTEILE


class AbfrageFehler(ValueError):
    pass


class NichtGefunden(AbfrageFehler):
    pass


def _norm(text: str | None) -> str:
    """Nur für den Vergleich: Gross/klein, Umlaute = ae/oe/ue, Leerraum."""
    if text is None:
        return ""
    t = " ".join(text.strip().casefold().split())
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("é", "e"), ("è", "e")):
        t = t.replace(a, b)
    return t


def _dict(row: sqlite3.Row) -> dict:
    return dict(row)


# --- portfolio_suchen -------------------------------------------------------

def portfolio_suchen(con, ort: str | None = None, plz: str | None = None, nutzung: str | None = None) -> dict:
    alle = [_dict(r) for r in con.execute("SELECT * FROM liegenschaften ORDER BY liegenschaft_id")]
    treffer, hinweise = [], []
    for l in alle:
        if ort and _norm(l["ort"]) != _norm(ort):
            continue
        if plz and (l["plz"] or "").strip() != str(plz).strip():
            continue
        if nutzung and _norm(l["nutzung"]) != _norm(nutzung):
            continue
        if ort and (l["ort"] or "").casefold() != ort.strip().casefold():
            hinweise.append(f"{l['liegenschaft_id']}: Ort ist als '{l['ort']}' gespeichert (Suche: '{ort}').")
        treffer.append(l)

    antwort = {
        "filter": {"ort": ort, "plz": plz, "nutzung": nutzung},
        "liegenschaften": treffer,
        "hinweise": hinweise,
        "zeilen_basis": {"liegenschaften": len(alle), "treffer": len(treffer)},
    }
    if not treffer:
        antwort["moegliche_werte"] = {
            k: sorted({l[k] for l in alle if l[k] is not None}) for k in ("ort", "plz", "nutzung")
        }
    return antwort


# --- liegenschaft_details ---------------------------------------------------

def _stichtag(stichtag: str | None) -> str:
    if stichtag is None:
        return dt.date.today().isoformat()
    try:
        return dt.date.fromisoformat(stichtag).isoformat()
    except (TypeError, ValueError):
        raise AbfrageFehler(f"Stichtag '{stichtag}' ist kein Datum im Format JJJJ-MM-TT.") from None


def _zustand(m: dict, stichtag: str) -> str:
    beginn, ende = m["mietbeginn"], m["mietende"]
    if beginn is None:
        return "unklar"
    if ende is not None and ende < beginn:
        return "widersprüchlich"
    if beginn > stichtag:
        return "zukünftig"
    if ende is not None and ende < stichtag:
        return "beendet"
    return "laufend"


def liegenschaft_details(con, liegenschaft_id: str, stichtag: str | None = None) -> dict:
    stichtag = _stichtag(stichtag)
    l = con.execute("SELECT * FROM liegenschaften WHERE liegenschaft_id = ?", (liegenschaft_id,)).fetchone()
    if l is None:
        raise NichtGefunden(f"Liegenschaft {liegenschaft_id} nicht gefunden.")

    einheiten = [_dict(r) for r in con.execute(
        "SELECT * FROM einheiten WHERE liegenschaft_id = ? ORDER BY einheit_id", (liegenschaft_id,))]
    mv_alle = [_dict(r) for r in con.execute(
        "SELECT m.* FROM mietverhaeltnisse m JOIN einheiten e USING (einheit_id) "
        "WHERE e.liegenschaft_id = ? ORDER BY m.mietbeginn, m.mietverhaeltnis_id", (liegenschaft_id,))]

    luecken, hinweise = [], []
    summe_miete = summe_flaeche = 0.0
    in_berechnung = 0

    for e in einheiten:
        mvs = [dict(m, zustand=_zustand(m, stichtag)) for m in mv_alle if m["einheit_id"] == e["einheit_id"]]
        e["mietverhaeltnisse"] = mvs
        for m in mvs:
            if m["zustand"] == "widersprüchlich":
                hinweise.append(
                    f"{m['mietverhaeltnis_id']} ({e['einheit_id']}): Mietende {m['mietende']} liegt vor "
                    f"Mietbeginn {m['mietbeginn']}; nicht berücksichtigt."
                )
        laufend = [m for m in mvs if m["zustand"] == "laufend"]
        e["jahresmiete_chf"] = None
        e["chf_pro_m2_jahr"] = None

        if len(laufend) == 0:
            e["status"] = "leer"
            luecken.append({"einheit_id": e["einheit_id"], "grund": f"kein laufendes Mietverhältnis am {stichtag}"})
            continue
        if len(laufend) > 1:
            e["status"] = "konflikt"
            ids = ", ".join(m["mietverhaeltnis_id"] for m in laufend)
            luecken.append({"einheit_id": e["einheit_id"],
                            "grund": f"{len(laufend)} laufende Mietverhältnisse ({ids}); keines ausgewählt"})
            continue

        e["status"] = "vermietet"
        miete = laufend[0]["nettomiete_monat_chf"]
        if miete is None:
            luecken.append({"einheit_id": e["einheit_id"], "grund": "Nettomiete fehlt"})
            continue
        e["jahresmiete_chf"] = miete * 12
        if e["flaeche_m2"] is None or e["flaeche_m2"] <= 0:
            luecken.append({"einheit_id": e["einheit_id"],
                            "grund": f"Fläche {e['flaeche_m2']!r} m² unbrauchbar; keine m²-Miete"})
            continue
        e["chf_pro_m2_jahr"] = round(e["jahresmiete_chf"] / e["flaeche_m2"], 2)
        summe_miete += e["jahresmiete_chf"]
        summe_flaeche += e["flaeche_m2"]
        in_berechnung += 1

    return {
        "liegenschaft": _dict(l),
        "stichtag": stichtag,
        "ist_miete": {
            "jahresmiete_chf": summe_miete if in_berechnung else None,
            "flaeche_m2": summe_flaeche if in_berechnung else None,
            "chf_pro_m2_jahr": round(summe_miete / summe_flaeche, 2) if in_berechnung else None,
            "methode": "Summe Nettomiete×12 / Summe Fläche, nur Einheiten mit genau einem laufenden "
                       "Mietverhältnis und Fläche > 0",
        },
        "einheiten": einheiten,
        "luecken": luecken,
        "hinweise": hinweise,
        "zeilen_basis": {
            "einheiten": len(einheiten),
            "mietverhaeltnisse": len(mv_alle),
            "einheiten_in_berechnung": in_berechnung,
        },
    }


# --- offerten_liste ---------------------------------------------------------

def offerten_liste(con, status: str | None = None) -> dict:
    alle = [_dict(r) for r in con.execute("SELECT * FROM offerten ORDER BY eingang, offerte_id")]
    anzahl_b = {r[0]: r[1] for r in con.execute("SELECT offerte_id, COUNT(*) FROM beurteilungen GROUP BY offerte_id")}
    letztes = {r[0]: r[1] for r in con.execute(
        "SELECT offerte_id, urteil FROM beurteilungen b WHERE erstellt_am = "
        "(SELECT MAX(erstellt_am) FROM beurteilungen WHERE offerte_id = b.offerte_id)")}

    adressen: dict[tuple, list[str]] = {}
    for o in alle:
        adressen.setdefault((_norm(o["strasse"]), o["plz"]), []).append(o["offerte_id"])

    treffer = []
    for o in alle:
        if status and _norm(o["status"]) != _norm(status):
            continue
        h = []
        if o["ertrag_laut_expose_chf"] is None:
            h.append("Ertrag laut Exposé fehlt.")
        elif o["ertrag_laut_expose_chf"] == 0:
            h.append("Ertrag laut Exposé ist 0 – möglicherweise fehlend, nicht als Ertrag interpretieren.")
        if o["vermietungsstand_laut_expose"] is None:
            h.append("Vermietungsstand laut Exposé fehlt.")
        if o["angebotspreis_chf"] is None:
            h.append("Angebotspreis fehlt.")
        andere = [x for x in adressen[(_norm(o["strasse"]), o["plz"])] if x != o["offerte_id"]]
        if andere:
            h.append(f"Gleiche Adresse wie {', '.join(andere)} – mögliche Dublette oder neue Version.")
        treffer.append(dict(o, hinweise=h, anzahl_beurteilungen=anzahl_b.get(o["offerte_id"], 0),
                            letztes_urteil=letztes.get(o["offerte_id"])))

    return {
        "filter": {"status": status},
        "offerten": treffer,
        "zeilen_basis": {"offerten": len(alle), "treffer": len(treffer), "beurteilungen": sum(anzahl_b.values())},
    }


# --- Beurteilungen ----------------------------------------------------------

def _beurteilung(row) -> dict:
    d = _dict(row)
    d["rote_flaggen"] = json.loads(d["rote_flaggen"]) if d["rote_flaggen"] else []
    return d


def _offerte_pruefen(con, offerte_id: str):
    if con.execute("SELECT 1 FROM offerten WHERE offerte_id = ?", (offerte_id,)).fetchone() is None:
        raise NichtGefunden(f"Offerte {offerte_id} nicht gefunden.")


def beurteilungen_liste(con, offerte_id: str) -> dict:
    _offerte_pruefen(con, offerte_id)
    rows = con.execute(
        "SELECT * FROM beurteilungen WHERE offerte_id = ? ORDER BY erstellt_am, rowid", (offerte_id,)).fetchall()
    return {
        "offerte_id": offerte_id,
        "beurteilungen": [_beurteilung(r) for r in rows],
        "zeilen_basis": {"beurteilungen_zur_offerte": len(rows)},
    }


def beurteilung_speichern(con, offerte_id: str, urteil: str, begruendung: str,
                          rote_flaggen: list[str] | None = None, quelle_skill_version: str | None = None) -> dict:
    if urteil not in URTEILE:
        raise AbfrageFehler(f"urteil '{urteil}' ungültig; erlaubt: {', '.join(URTEILE)}.")
    if not begruendung or not begruendung.strip():
        raise AbfrageFehler("begruendung darf nicht leer sein.")
    rote_flaggen = list(rote_flaggen or [])
    if not all(isinstance(f, str) for f in rote_flaggen):
        raise AbfrageFehler("rote_flaggen muss eine Liste von Texten sein.")
    _offerte_pruefen(con, offerte_id)

    b = {
        "beurteilung_id": f"B-{uuid.uuid4().hex[:12]}",
        "offerte_id": offerte_id,
        "erstellt_am": dt.datetime.now().astimezone().isoformat(timespec="microseconds"),
        "urteil": urteil,
        "begruendung": begruendung,
        "rote_flaggen": json.dumps(rote_flaggen, ensure_ascii=False),
        "quelle_skill_version": quelle_skill_version,
    }
    with con:
        con.execute(
            "INSERT INTO beurteilungen VALUES (:beurteilung_id, :offerte_id, :erstellt_am, :urteil, "
            ":begruendung, :rote_flaggen, :quelle_skill_version)", b)
    n = con.execute("SELECT COUNT(*) FROM beurteilungen WHERE offerte_id = ?", (offerte_id,)).fetchone()[0]
    return {"beurteilung": dict(b, rote_flaggen=rote_flaggen), "zeilen_basis": {"beurteilungen_zur_offerte": n}}
