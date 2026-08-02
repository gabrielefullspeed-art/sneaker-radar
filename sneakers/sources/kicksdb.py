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
        Il formato esatto delle varianti puo' cambiare fra le versioni
        dell'API, quindi la lettura e' volutamente tollerante: si cerca
        una taglia e un prezzo comunque siano nominati i campi.
        """
        from ..sizes import parse_size

        products = data.get("data") or data.get("products") or []
        if isinstance(products, dict):
            products = [products]
        if not products:
            return {}

        gender = product.get("gender", "men")
        out: dict[float, float] = {}

        variants = products[0].get("variants") or products[0].get("sizes") or []
        for v in variants:
            raw_size = v.get("size") or v.get("size_us") or v.get("title")
            price = (v.get("lowest_ask") or v.get("lowestAsk")
                     or v.get("price") or v.get("last_sale") or v.get("lastSale"))
            if raw_size is None or not price:
                continue
            size_eu = parse_size(str(raw_size), "auto", gender)
            if size_eu in sizes_eu:
                out[size_eu] = self.fx(float(price), products[0].get("currency", "USD"))

        # fallback: prezzo unico non diviso per taglia
        if not out:
            p = (products[0].get("min_price") or products[0].get("avg_price")
                 or products[0].get("retail_price"))
            if p:
                cur = products[0].get("currency", "USD")
                out = {s: self.fx(float(p), cur) for s in sizes_eu}

        return out
