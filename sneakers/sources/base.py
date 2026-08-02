"""
Interfaccia comune a tutte le sorgenti.

Aggiungere un sito nuovo = scrivere una classe che eredita da Source
e implementa search(). Tutto il resto (taglie, prezzi, notifiche,
anti-spam) e' gia' gestito e non va toccato.
"""

from dataclasses import dataclass

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
}


@dataclass
class Listing:
    """Un annuncio: una scarpa, una taglia, un prezzo, su un sito."""
    source: str
    sku: str
    size_eu: float
    price_eur: float
    url: str
    title: str = ""
    condition: str = "unknown"   # new | used | unknown
    listing_id: str | None = None


class Source:
    name = "base"

    def __init__(self, cfg: dict, fx):
        self.cfg = cfg
        self.fx = fx          # funzione (importo, valuta) -> euro
        self.errors: list[str] = []

    def search(self, product: dict, sizes_eu: list[float]) -> list[Listing]:
        """Cerca un prodotto e restituisce gli annunci nelle taglie richieste."""
        raise NotImplementedError

    def log_error(self, msg: str):
        self.errors.append(f"[{self.name}] {msg}")
        print(f"  ! {self.name}: {msg}")
