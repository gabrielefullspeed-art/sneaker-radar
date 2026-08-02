"""
eBay — API Browse ufficiale (gratuita).

E' la sorgente piu' importante per questa watchlist: nessun negozio
avra' mai un paio di Pushead del 2005, eBay si'. Interroga piu'
mercati (IT, DE, GB, FR) perche' spesso un venditore tedesco espone
un prezzo che in Italia nessuno fa.

Serve un account sviluppatore gratuito su developer.ebay.com:
   EBAY_CLIENT_ID  +  EBAY_CLIENT_SECRET
Senza credenziali la sorgente si disattiva da sola senza far fallire
la scansione.
"""

import os
import re
import base64
import time
import httpx

from .base import Source, Listing
from ..sizes import parse_size
from ..matching import matches, search_terms

OAUTH = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH = "https://api.ebay.com/buy/browse/v1/item_summary/search"

_CONDITION = {
    "NEW": "new", "NEW_OTHER": "new", "NEW_WITH_DEFECTS": "new",
    "USED": "used", "VERY_GOOD": "used", "GOOD": "used",
    "LIKE_NEW": "used", "PRE_OWNED_EXCELLENT": "used",
}


class EbaySource(Source):
    name = "eBay"

    def __init__(self, cfg, fx):
        super().__init__(cfg, fx)
        self.client_id = os.environ.get("EBAY_CLIENT_ID")
        self.client_secret = os.environ.get("EBAY_CLIENT_SECRET")
        self.marketplaces = cfg["sources"]["ebay"].get("marketplaces", ["EBAY_IT"])
        self.max_results = cfg["sources"]["ebay"].get("max_results", 50)
        self._token = None
        self._token_exp = 0

    @property
    def available(self) -> bool:
        return bool(self.client_id and self.client_secret)

    # -- autenticazione -----------------------------------------------
    def _get_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        creds = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        r = httpx.post(
            OAUTH,
            headers={"Authorization": f"Basic {creds}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials",
                  "scope": "https://api.ebay.com/oauth/api_scope"},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 7200))
        return self._token

    # -- ricerca -------------------------------------------------------
    def search(self, product: dict, sizes_eu: list[float]) -> list[Listing]:
        if not self.available:
            return []

        out: list[Listing] = []
        seen: set[str] = set()
        # eBay regge query piu' lunghe di Shopify, ma lo SKU resta il
        # modo piu' preciso: molti venditori lo scrivono nel titolo.
        queries = [product["sku"]] + search_terms(product)

        for market in self.marketplaces:
            for q in queries:
                try:
                    items = self._call(q, market)
                except Exception as e:
                    self.log_error(f"{market} '{q}': {e}")
                    continue

                for it in items:
                    iid = it.get("itemId")
                    if not iid or iid in seen:
                        continue
                    seen.add(iid)
                    lst = self._to_listing(it, product, sizes_eu, market)
                    if lst:
                        out.append(lst)
        return out

    def _call(self, query: str, marketplace: str) -> list[dict]:
        r = httpx.get(
            SEARCH,
            headers={"Authorization": f"Bearer {self._get_token()}",
                     "X-EBAY-C-MARKETPLACE-ID": marketplace},
            params={"q": query, "limit": self.max_results,
                    "category_ids": "15709",          # Scarpe da uomo/sneaker
                    "filter": "buyingOptions:{FIXED_PRICE}"},
            timeout=25,
        )
        if r.status_code == 429:
            raise RuntimeError("rate limit eBay raggiunto")
        r.raise_for_status()
        return r.json().get("itemSummaries") or []

    # -- conversione ----------------------------------------------------
    def _to_listing(self, item: dict, product: dict,
                    sizes_eu: list[float], market: str) -> Listing | None:
        title = item.get("title", "")
        if not matches(title, product):
            return None

        size_eu = self._size_from(item, title, product.get("gender", "men"))
        if size_eu is None or size_eu not in sizes_eu:
            return None

        price = item.get("price") or {}
        try:
            value = float(price.get("value"))
        except (TypeError, ValueError):
            return None

        return Listing(
            source=f"eBay {market.replace('EBAY_', '')}",
            sku=product["sku"],
            size_eu=size_eu,
            price_eur=self.fx(value, price.get("currency", "EUR")),
            url=item.get("itemWebUrl", ""),
            title=title,
            condition=_CONDITION.get(str(item.get("condition", "")).upper().replace(" ", "_"), "unknown"),
            listing_id=item.get("itemId"),
        )

    def _size_from(self, item: dict, title: str, gender: str) -> float | None:
        """La taglia sta negli aspetti strutturati o, in mancanza, nel titolo."""
        for asp in item.get("localizedAspects") or []:
            if str(asp.get("name", "")).lower() in ("us shoe size", "eu shoe size",
                                                    "shoe size", "taglia", "size"):
                got = parse_size(asp.get("value", ""), "auto", gender)
                if got:
                    return got

        # dal titolo: "... Size US 9", "... EU 42.5", "... Tg 42"
        m = re.search(r"\b(?:size|sz|tg|taglia|eu|us|uk)[\s.]*(\d{1,2}(?:[.,]5)?)\b",
                      title, re.IGNORECASE)
        if m:
            return parse_size(m.group(0), "auto", gender)
        return None
