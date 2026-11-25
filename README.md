# tc-server – Offertenregister

Lese-API (FastAPI) und MCP-Server für eingehende Kaufofferten und den eigenen Liegenschaftsbestand.

## Voraussetzungen

- [uv](https://docs.astral.sh/uv/) (installiert Python und alle Abhängigkeiten)
- Die Rohdaten liegen als CSV im Ordner `data/` neben diesem Repository. Sie sind bewusst nicht im Repository.
  Anderer Ort: Umgebungsvariable `TC_DATEN_PFAD`.

## Befehle

```
uv run pytest                 # Tests
uv run python -m server       # API auf http://127.0.0.1:8001/api
```

Host und Port lassen sich mit `TC_HOST` und `TC_PORT` ändern, der Pfad der Datenbank mit `TC_DB_PFAD`.

## Regeln

- Fehlende Werte werden nie geschätzt, sondern als Lücke ausgewiesen.
- Rohdaten in `data/` werden nie verändert.
- Geheimnisse stehen nur in der Umgebung, nie im Code.
