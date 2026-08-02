"""
Database SQLite: storico prezzi + notifiche gia' inviate.

Il file vive dentro il repository (data/prices.db) e viene aggiornato
a ogni scansione. E' questo storico che, dopo qualche settimana,
permette di sapere quale sia il prezzo "normale" di ogni scarpa in
ogni taglia senza dipendere da nessun servizio esterno.
"""

import sqlite3
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id          INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL,
    sku         TEXT NOT NULL,
    size_eu     REAL NOT NULL,
    source      TEXT NOT NULL,
    price_eur   REAL NOT NULL,
    condition   TEXT,            -- new | used | unknown
    url         TEXT,
    title       TEXT,
    listing_id  TEXT             -- id stabile dell'annuncio, se il sito lo espone
);
CREATE INDEX IF NOT EXISTS idx_obs_lookup ON observations(sku, size_eu, ts);

CREATE TABLE IF NOT EXISTS reference (
    sku         TEXT NOT NULL,
    size_eu     REAL NOT NULL,
    ts          TEXT NOT NULL,
    price_eur   REAL NOT NULL,
    source      TEXT NOT NULL,   -- kicksdb | history | bootstrap
    PRIMARY KEY (sku, size_eu, source)
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL,
    fingerprint TEXT NOT NULL,   -- sku|taglia|sito
    sku         TEXT NOT NULL,
    size_eu     REAL NOT NULL,
    source      TEXT NOT NULL,
    price_eur   REAL NOT NULL,
    channel     TEXT NOT NULL,   -- main | grails | suspicious
    url         TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_fp ON alerts(fingerprint, ts);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | Path = "data/prices.db") -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def fingerprint(sku: str, size_eu: float, source: str) -> str:
    return hashlib.sha1(f"{sku}|{size_eu}|{source}".encode()).hexdigest()[:16]


def record_observation(con, *, sku, size_eu, source, price_eur,
                       condition="unknown", url=None, title=None, listing_id=None):
    con.execute(
        "INSERT INTO observations (ts, sku, size_eu, source, price_eur, condition, url, title, listing_id)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (_now(), sku, float(size_eu), source, float(price_eur), condition, url, title, listing_id),
    )


def prices_in_window(con, sku: str, size_eu: float, days: int) -> list[float]:
    """Tutti i prezzi visti per quella scarpa/taglia negli ultimi N giorni."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    rows = con.execute(
        "SELECT price_eur FROM observations WHERE sku=? AND size_eu=? AND ts>=?",
        (sku, float(size_eu), since),
    ).fetchall()
    return [r["price_eur"] for r in rows]


def set_reference(con, sku: str, size_eu: float, price_eur: float, source: str):
    con.execute(
        "INSERT INTO reference (sku, size_eu, ts, price_eur, source) VALUES (?,?,?,?,?)"
        " ON CONFLICT(sku, size_eu, source) DO UPDATE SET price_eur=excluded.price_eur, ts=excluded.ts",
        (sku, float(size_eu), _now(), float(price_eur), source),
    )


def get_reference(con, sku: str, size_eu: float) -> tuple[float, str] | None:
    """Riferimento piu' affidabile disponibile: prima KicksDB, poi lo storico."""
    for src in ("kicksdb", "history", "bootstrap"):
        row = con.execute(
            "SELECT price_eur, ts FROM reference WHERE sku=? AND size_eu=? AND source=?",
            (sku, float(size_eu), src),
        ).fetchone()
        if row:
            return row["price_eur"], src
    return None


def reference_age_hours(con, sku: str, size_eu: float, source: str) -> float | None:
    row = con.execute(
        "SELECT ts FROM reference WHERE sku=? AND size_eu=? AND source=?",
        (sku, float(size_eu), source),
    ).fetchone()
    if not row:
        return None
    ts = datetime.fromisoformat(row["ts"])
    return (datetime.now(timezone.utc) - ts).total_seconds() / 3600


def last_alert(con, fp: str) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM alerts WHERE fingerprint=? ORDER BY ts DESC LIMIT 1", (fp,)
    ).fetchone()


def record_alert(con, *, sku, size_eu, source, price_eur, channel, url):
    con.execute(
        "INSERT INTO alerts (ts, fingerprint, sku, size_eu, source, price_eur, channel, url)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (_now(), fingerprint(sku, size_eu, source), sku, float(size_eu),
         source, float(price_eur), channel, url),
    )


def prune(con, keep_days: int = 400):
    """
    Tiene il database piccolo: il repo GitHub non deve gonfiarsi.

    Il VACUUM riscrive l'intero file, quindi girerebbe un commit git
    grosso a ogni scansione: si esegue solo quando si e' davvero
    cancellato qualcosa. E deve stare fuori da una transazione.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat(timespec="seconds")
    cur = con.execute("DELETE FROM observations WHERE ts < ?", (cutoff,))
    deleted = cur.rowcount
    con.commit()
    if deleted > 0:
        con.isolation_level = None      # VACUUM non tollera transazioni aperte
        con.execute("VACUUM")
        con.isolation_level = ""
    return deleted
