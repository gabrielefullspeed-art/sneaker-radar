"""
Laced — piattaforma di resell britannica.

E' la sorgente tecnicamente migliore di tutte, perche' ha un'API vera:

    /api/v1/products/<id>/stock_prices_by_size
        ?delivery_location=IT&currency=EUR

Risponde con ogni taglia gia' convertita (uk, eu, us) e il prezzo gia'
in euro per una consegna in Italia. Niente conversioni da indovinare,
niente cambi valuta, niente sorprese: due delle tre fonti di errore
che ci hanno dato problemi qui semplicemente non esistono.

L'unico passaggio in piu' e' trovare l'id numerico del prodotto, che
si ricava dai dati Next.js della pagina, raggiunta partendo dalla
sitemap.
"""

import re
import time
import httpx

from .base import Source, Listing, BROWSER_HEADERS
from ..matching import matches, normalize

HOME = "https://www.laced.com"
SITEMAP = "https://www.laced.com/sitemap.xml"


class LacedSource(Source):
    name = "Laced"

    def __init__(self, cfg, fx, store: dict | None = None):
        super().__init__(cfg, fx)
        self.delay = (store or {}).get("request_delay", 1.2)
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
        if self._build_id:
            return self._build_id
        m = re.search(r'"buildId"\s*:\s*"([^"]+)"', self._get(HOME).text)
        if not m:
            raise RuntimeError("buildId non trovato: il sito e' cambiato")
        self._build_id = m.group(1)
        return self._build_id

    def _catalogo(self) -> list[str]:
        """
        La sitemap principale rimanda a piu' file di prodotti.
        Si leggono una volta sola per scansione.
        """
        if self._slugs is not None:
            return self._slugs
        indice = self._get(SITEMAP).text
        files = [u for u in re.findall(r"<loc>([^<]+)</loc>", indice) if "products" in u]

        slugs: list[str] = []
        for f in files[:6]:                     # bastano per il catalogo attivo
            try:
                xml = self._get(f).text
            except Exception as e:
                self.log_error(f"sitemap {f.split('/')[-1]}: {e}")
                continue
            slugs += [u.rstrip("/").split("/")[-1]
                      for u in re.findall(r"<loc>([^<]+/products/[^<]+)</loc>", xml)]

        self._slugs = slugs
        return slugs

    # -- API pubblica --------------------------------------------------
    def search(self, product: dict, sizes_eu: list[float]) -> list[Listing]:
        try:
            slugs = self._catalogo()
        except Exception as e:
            self.log_error(f"catalogo non disponibile: {e}")
            return []

        # Ogni termine per conto suo: vedi la nota in wethenew.py
        gruppi = [[w for w in normalize(t).split() if len(w) > 2]
                  for t in product.get("terms", [])]
        gruppi = [g for g in gruppi if g]
        if not gruppi:
            return []

        # Le regole match/exclude si applicano gia' allo slug, che
        # contiene il colorway: evita di scaricare 69 pagine Travis Scott
        # per poi scartarle, e soprattutto di troncarle prima di quella giusta.
        candidati = [s for s in slugs
                     if any(all(w in s.replace("-", " ") for w in g) for g in gruppi)
                     and matches(s.replace("-", " "), product)]
        out: list[Listing] = []

        for slug in candidati[:4]:
            info = self._prodotto(slug)
            if not info:
                continue
            pid, titolo = info
            if not matches(f"{titolo} {slug}", product):
                continue
            out += self._prezzi(pid, product, sizes_eu, slug, titolo)

        return out

    def _prodotto(self, slug: str) -> tuple[int, str] | None:
        """Id numerico e titolo, dai dati Next.js della pagina prodotto."""
        try:
            data = self._get(
                f"{HOME}/_next/data/{self._build()}/products/{slug}.json"
            ).json()
        except Exception as e:
            self.log_error(f"{slug}: {e}")
            return None

        testo = str(data)
        m = re.search(r'"product_id"\s*:\s*(\d{3,7})', testo) or \
            re.search(r'/api/v1/products/(\d{3,7})/', testo)
        if not m:
            return None

        t = re.search(r'"(?:name|title)"\s*:\s*"([^"]{6,90})"', testo)
        return int(m.group(1)), (t.group(1) if t else slug.replace("-", " "))

    def _prezzi(self, pid: int, product: dict, sizes_eu: list[float],
                slug: str, titolo: str) -> list[Listing]:
        try:
            data = self._get(
                f"{HOME}/api/v1/products/{pid}/stock_prices_by_size",
                params={"delivery_location": "IT", "currency": "EUR",
                        "discount_requestor": "web"},
            ).json()
        except Exception as e:
            self.log_error(f"prezzi {slug}: {e}")
            return []

        out = []
        for s in data.get("sizes", []):
            try:
                size_eu = float(str(s.get("eu", "")).replace(",", "."))
            except ValueError:
                continue
            if size_eu not in sizes_eu:
                continue

            # piu' offerte per la stessa taglia: interessa la piu' bassa
            migliore = None
            for c in s.get("sale_collections") or []:
                cents = ((c.get("price") or {}).get("cents"))
                if not cents:
                    continue
                euro = float(cents) / 100.0
                if migliore is None or euro < migliore:
                    migliore = euro
            if migliore is None:
                continue

            out.append(Listing(
                source=self.name,
                sku=product["sku"],
                size_eu=size_eu,
                price_eur=migliore,          # gia' in euro, nessuna conversione
                url=f"{HOME}/products/{slug}",
                title=titolo,
                condition="new",
                listing_id=f"{pid}-{s.get('id')}",
            ))
        return out
