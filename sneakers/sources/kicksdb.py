"""
KicksDB — prezzo di riferimento StockX / GOAT.

Non e' una sorgente da cui comprare: serve a sapere QUANTO VALE una
scarpa, cioe' il metro con cui giudicare tutti gli altri annunci.

Il piano gratuito da' 1.000 richieste al mese, per questo il
riferimento si aggiorna UNA VOLTA AL GIORNO per scarpa e non a ogni
scansione (16 scarpe x 30 giorni = 480 richieste, resta margine).

Serve KICKSDB_API_KEY da kicks.dev (registrazione gratuita, no carta).
Senza chiave il sistema usa comunque lo storico interno: parte piu'
lento ma funziona.
"""

import os
import re
import json
import httpx

from .base import Source

BASE = "https://api.kicks.dev"


class KicksDBReference(Source):
    name = "KicksDB"

    def __init__(self, cfg, fx):
        super().__init__(cfg, fx)
        self.api_key = os.environ.get("KICKSDB_API_KEY")
        self.debug = os.environ.get("KICKSDB_DEBUG") == "1"

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def search(self, product, sizes_eu):
        # non e' una sorgente d'acquisto
        return []

    def reference_prices(self, product: dict, sizes_eu: list[float]) -> dict[float, float]:
        """
        Prezzi di mercato per taglia: {42.0: 780.0, 42.5: 810.0}
        Restituisce {} se non disponibile — non e' un errore fatale.
        """
        if not self.available:
            return {}

        try:
            data = self._fetch(product["sku"])
        except Exception as e:
            self.log_error(f"{product['sku']}: {e}")
            return {}

        if self.debug:
            print(json.dumps(data, indent=2)[:3000])

        return self._parse(data, product, sizes_eu)

    def _fetch(self, sku: str) -> dict:
        r = httpx.get(
            f"{BASE}/v3/stockx/products",
            headers={"Authorization": self.api_key},
            params={"query": sku, "limit": 1, "display[variants]": "true"},
            timeout=25,
        )
        if r.status_code in (401, 403):
            raise RuntimeError("chiave API rifiutata")
        if r.status_code == 429:
            raise RuntimeError("quota mensile esaurita")
        r.raise_for_status()
        return r.json()

    def _parse(self, data: dict, product: dict, sizes_eu: list[float]) -> dict[float, float]:
        """
        Estrae il lowest ask per ognuna delle taglie che interessano.

        Struttura reale della risposta:
            data[0].sku                       codice modello, da verificare
            data[0].variants[].lowest_ask     prezzo, 0 se nessuno vende
            data[0].variants[].currency       valuta (USD sul piano free)
            data[0].variants[].sizes[]        stessa taglia in tutti i
                                              sistemi, incluso {"type":"eu"}

        Le taglie EU arrivano gia' convertite dall'API, quindi qui non
        si indovina nulla: si legge l'etichetta "EU 42" cosi' com'e'.
        """
        products = data.get("data") or []
        if isinstance(products, dict):
            products = [products]
        if not products:
            return {}

        # niente sorprese: deve essere davvero la scarpa richiesta
        p = products[0]
        atteso = re.sub(r"[^a-z0-9]", "", product["sku"].lower())
        trovato = re.sub(r"[^a-z0-9]", "", str(p.get("sku", "")).lower())
        if atteso and trovato and atteso != trovato:
            self.log_error(f"{product['sku']}: l'API ha risposto con {p.get('sku')}, ignorato")
            return {}

        out: dict[float, float] = {}
        for v in p.get("variants", []):
            ask = v.get("lowest_ask")
            if not ask:                       # 0 = nessuno la vende in quella taglia
                continue

            etichetta_eu = next((s.get("size") for s in v.get("sizes", [])
                                 if s.get("type") == "eu"), None)
            if not etichetta_eu:
                continue

            m = re.search(r"(\d+(?:\.\d+)?)", str(etichetta_eu))
            if not m:
                continue
            size_eu = float(m.group(1))
            if size_eu in sizes_eu:
                out[size_eu] = self.fx(float(ask), v.get("currency", "USD"))

        return out

    def market_snapshot(self, product: dict, sizes_eu: list[float]) -> dict:
        """
        Come reference_prices, ma restituisce anche il contorno utile a
        capire quanto fidarsi del prezzo: quante offerte ci sono e
        quante vendite reali negli ultimi due mesi.
        """
        if not self.available:
            return {}
        try:
            data = self._fetch(product["sku"])
        except Exception as e:
            self.log_error(f"{product['sku']}: {e}")
            return {}

        products = data.get("data") or []
        if not products:
            return {}
        p = products[0]

        righe = {}
        for v in p.get("variants", []):
            etichetta_eu = next((s.get("size") for s in v.get("sizes", [])
                                 if s.get("type") == "eu"), "")
            m = re.search(r"(\d+(?:\.\d+)?)", str(etichetta_eu))
            if not m or float(m.group(1)) not in sizes_eu:
                continue
            righe[float(m.group(1))] = {
                "lowest_ask": v.get("lowest_ask") or 0,
                "currency": v.get("currency", "USD"),
                "eur": self.fx(float(v.get("lowest_ask") or 0), v.get("currency", "USD")),
                "offerte": v.get("total_asks") or 0,
                "vendite_60gg": v.get("sales_count_60_days") or 0,
            }
        return {"titolo": p.get("title"), "sku": p.get("sku"),
                "min": p.get("min_price"), "media": p.get("avg_price"), "taglie": righe}
