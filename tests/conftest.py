import shutil
from pathlib import Path

import pytest

from server.db import verbinden
from server.laden import laden

DATEN = Path(__file__).resolve().parents[2] / "data"
STICHTAG = "2026-11-25"


@pytest.fixture
def daten_kopie(tmp_path):
    """Kopie der Rohdaten, damit Tests sie variieren können, ohne data/ anzufassen."""
    ziel = tmp_path / "data"
    shutil.copytree(DATEN, ziel)
    return ziel


@pytest.fixture
def db_pfad(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def geladen(db_pfad):
    """Datenbank, einmal aus den echten Rohdaten geladen."""
    laden(db_pfad, DATEN)
    return db_pfad


@pytest.fixture
def con(geladen):
    c = verbinden(geladen)
    yield c
    c.close()
