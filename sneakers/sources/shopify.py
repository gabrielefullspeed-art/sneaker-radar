"""
Negozi su piattaforma Shopify.

Moltissime boutique sneaker europee girano su Shopify, che espone due
endpoint JSON pubblici molto utili:

    /search/suggest.json?q=...      -> ricerca prodotti
    /products/<handle>.js           -> dettaglio con TUTTE le varianti,
                                       cioe' prezzo e disponibilita'
                                       per ogni singola taglia

Verificato funzionante su Slam Jam, Asphaltgold, Overkill e Foot District.
Nota: /products.json e' spesso limitato da Cloudflare, mentre
/search/suggest.json passa — per questo si usa quello.
"""

import time
import httpx

from .base import Source, Listing, BROWSER_HEADERS
from ..sizes import parse_size
from ..matching import matches, search_terms


class ShopifySource(Source):
    name = "shopify"

    def __init__(self, cfg, fx, store: dict):
        super().__init__(cfg, fx)
        self.store = store
        self.name = store["name"]
        self.base = store["url"].rstrip("/")
        self.size_system = store.get("size_system", "auto")
        self.currency = store.get("currency", "EUR")
        self.delay = cfg["sources"]["shopify"].get("request_delay", 1.5)

    # -- rete ---------------------------------------------------------
    def _get(self, path: str, params: dict | None = None):
        time.sleep(self.delay)          # niente martellate: una richiesta ogni 1.5 s
        r = httpx.get(self.base + path, params=params, headers=BROWSER_HEADERS,
                      timeout=20, follow_redirects=True)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} su {path}")
        return r.json()

    # -- ricerca ------------------------------------------------------
    def _suggest(self, query: str) -> list[dict]:
        data = self._get("/search/suggest.json", {
            "q": query,
            "resources[type]": "product",
            "resources[limit]": 6,
        })
        return data.get("resources", {}).get("results", {}).get("products", [])

    def _variants(self, handle: str) -> dict:
        return self._get(f"/products/{handle}.js")

    # -- API pubblica -------------------------------------------------
    def search(self, product: dict, sizes_eu: list[float]) -> list[Listing]:
        out: list[Listing] = []
        seen_handles: set[str] = set()

        # Termini CORTI: la ricerca Shopify fa AND su tutte le parole,
        # quindi si cerca largo e si filtra dopo con matching.matches().
        for q in search_terms(product):
            try:
                hits = self._suggest(q)
            except Exception as e:
                self.log_error(f"ricerca '{q}' fallita: {e}")
                continue

            for hit in hits:
                handle = hit.get("handle")
                if not handle or handle in seen_handles:
                    continue
                seen_handles.add(handle)

                try:
                    detail = self._variants(handle)
                except Exception as e:
                    self.log_error(f"dettaglio '{handle}' fallito: {e}")
                    continue

                if not self._matches(detail, product):
                    continue

                out += self._extract(detail, product, sizes_eu, handle)

        return out

    def _matches(self, detail: dict, product: dict) -> bool:
        """Conferma che il prodotto trovato sia davvero quello cercato."""
        blob = " ".join(str(detail.get(k, "")) for k in ("title", "handle", "description", "tags"))
        blob += " " + " ".join(str(v.get("sku", "")) for v in detail.get("variants", []))
        return matches(blob, product)

    def _extract(self, detail: dict, product: dict, sizes_eu: list[float],
                 handle: str) -> list[Listing]:
        found = []
        gender = product.get("gender", "men")

        for v in detail.get("variants", []):
            if not v.get("available"):
                continue                                  # taglia esaurita
            size_eu = parse_size(v.get("title", ""), self.size_system, gender)
            if size_eu is None or size_eu not in sizes_eu:
                continue

            price = self.fx(v["price"] / 100.0, self.currency)   # Shopify usa i centesimi
            found.append(Listing(
                source=self.name,
                sku=product["sku"],
                size_eu=size_eu,
                price_eur=price,
                url=f"{self.base}/products/{handle}",
                title=detail.get("title", ""),
                condition="new",                          # i negozi vendono nuovo
                listing_id=str(v.get("id")),
            ))
        return found
