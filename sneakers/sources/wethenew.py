"""
Wethenew — piattaforma di resell francese.

Non e' Shopify come gli altri negozi, quindi serve una strada diversa.
E' un sito Next.js, e i siti Next.js espongono i dati della pagina in
JSON all'indirizzo:

    /_next/data/<buildId>/en/products/<slug>.json

Il buildId cambia a ogni rilascio del sito, quindi va riletto ogni
volta dalla home.

Per trovare i prodotti non si usa la ricerca (funziona solo lato
browser) ma la **sitemap**, che e' pubblica e pensata apposta per
essere letta dalle macchine: 7.700 prodotti, filtrati per parola
chiave prima di scaricare qualsiasi dettaglio.

Vale la pena rispetto a Stadium Goods: e' europeo, spedisce in Italia
senza dogana, autentica ogni paio, e le varianti riportano lo SKU Nike
vero e la taglia EU in chiaro.
"""

import re
import time
import httpx

from .base import Source, Listing, BROWSER_HEADERS
from ..matching import matches, normalize
from ..sizes import parse_size

HOME = "https://wethenew.com/en"
SITEMAP = "https://wethenew.com/sitemap-products.xml"


class WethenewSource(Source):
    name = "Wethenew"

    def __init__(self, cfg, fx, store: dict | None = None):
        super().__init__(cfg, fx)
        self.delay = (store or {}).get("request_delay",
                                       cfg["sources"]["shopify"].get("request_delay", 1.5))
        self._build_id: str | None = None
        self._slugs: list[str] | None = None

    # -- rete ---------------------------------------------------------
    def _get(self, url: str, **kw):
        time.sleep(self.delay)
        r = httpx.get(url, headers=BROWSER_HEADERS, timeout=30,
                      follow_redirects=True, **kw)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        return r

    def _build(self) -> str:
        """L'identificativo di build cambia a ogni aggiornamento del sito."""
        if self._build_id:
            return self._build_id
        html = self._get(HOME).text
        m = re.search(r'"buildId"\s*:\s*"([^"]+)"', html)
        if not m:
            raise RuntimeError("buildId non trovato: il sito e' cambiato")
        self._build_id = m.group(1)
        return self._build_id

    def _catalogo(self) -> list[str]:
        """Tutti gli slug prodotto, letti una volta sola per scansione."""
        if self._slugs is not None:
            return self._slugs
        xml = self._get(SITEMAP).text
        self._slugs = re.findall(r"<loc>[^<]*/products/([^<]+)</loc>", xml)
        return self._slugs

    # -- API pubblica --------------------------------------------------
    def search(self, product: dict, sizes_eu: list[float]) -> list[Listing]:
        try:
            slugs = self._catalogo()
            build = self._build()
        except Exception as e:
            self.log_error(f"catalogo non disponibile: {e}")
            return []

        candidati = self._candidati(product, slugs)
        out: list[Listing] = []

        for slug in candidati[:4]:          # basta e avanza, evita richieste inutili
            try:
                data = self._get(
                    f"https://wethenew.com/_next/data/{build}/en/products/{slug}.json"
                ).json()
            except Exception as e:
                self.log_error(f"{slug}: {e}")
                continue

            p = (data.get("pageProps") or {}).get("product") or {}
            if not p:
                continue

            varianti = p.get("variants") or []
            testo = " ".join([
                str(p.get("title", "")), slug,
                " ".join(str(v.get("sku", "")) for v in varianti[:3]),
            ])
            if not matches(testo, product):
                continue

            out += self._estrai(p, product, sizes_eu, slug)

        return out

    def _candidati(self, product: dict, slugs: list[str]) -> list[str]:
        """
        Restringe 7.700 slug a una manciata, confrontando le parole
        chiave della scarpa con il testo dell'indirizzo.
        """
        # Ogni termine va valutato PER CONTO SUO: unire le parole di
        # "Travis Scott" e "Cactus Jack Dunk" e pretenderle tutte
        # insieme non fa trovare niente. Basta che UN termine torni.
        gruppi = [[w for w in normalize(t).split() if len(w) > 2]
                  for t in product.get("terms", [])]
        gruppi = [g for g in gruppi if g]
        if not gruppi:
            return []

        # Il nome nello slug contiene quasi sempre il colorway, quindi
        # le regole match/exclude si applicano gia' qui: "Travis Scott"
        # da solo pesca 69 prodotti, e troncare ai primi quattro faceva
        # perdere proprio quello giusto.
        risultati = []
        for slug in slugs:
            piatto = slug.replace("-", " ")
            if not any(all(w in piatto for w in g) for g in gruppi):
                continue
            if matches(piatto, product):
                risultati.append(slug)
        return risultati

    def _estrai(self, p: dict, product: dict, sizes_eu: list[float],
                slug: str) -> list[Listing]:
        """
        Le varianti hanno titoli tipo "42 EU - 8.5 US - 695€".
        Il primo numero e' la taglia europea: si prende quella e si
        ignora il resto, che e' solo etichetta commerciale.
        """
        trovate: dict[tuple, Listing] = {}

        for v in p.get("variants", []):
            if not v.get("availableForSale"):
                continue

            titolo = str(v.get("title", ""))
            m = re.match(r"\s*(\d{2}(?:\.5)?)\s*EU", titolo)
            if not m:
                continue
            size_eu = parse_size(m.group(1), "EU", product.get("gender", "men"))
            if size_eu is None or size_eu not in sizes_eu:
                continue

            prezzo = v.get("price")
            if isinstance(prezzo, dict):
                prezzo = prezzo.get("amount")
            try:
                prezzo = float(prezzo)
            except (TypeError, ValueError):
                continue
            if prezzo <= 0:
                continue

            # piu' offerte per la stessa taglia (standard, express...):
            # interessa solo la piu' economica
            chiave = (size_eu,)
            if chiave in trovate and trovate[chiave].price_eur <= prezzo:
                continue

            trovate[chiave] = Listing(
                source=self.name,
                sku=product["sku"],
                size_eu=size_eu,
                price_eur=self.fx(prezzo, "EUR"),
                url=f"https://wethenew.com/en/products/{slug}",
                title=str(p.get("title", "")),
                condition="new",
                listing_id=str(v.get("id")),
            )

        return list(trovate.values())
