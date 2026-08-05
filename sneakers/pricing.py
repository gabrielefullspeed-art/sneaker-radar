"""
Il motore che decide cosa e' un affare.

Regola (vedi config.yaml -> deal):
  un annuncio e' un affare quando il prezzo entra nel percentile piu'
  basso degli ultimi 30 giorni per QUELLA scarpa in QUELLA taglia,
  ed e' comunque almeno il 15% sotto il prezzo di riferimento.

Perche' non una soglia fissa tipo "-20%": la watchlist va da scarpe
da 180 € a scarpe da 2000 €. Il -20% su una Air Ship sono 36 € di
risparmio (notifiche inutili), sul Travis Scott Mocha sono 380 €
(ma resta fuori budget). Il percentile si adatta da solo.
"""

from dataclasses import dataclass, field
from statistics import median


@dataclass
class Deal:
    product_name: str        # come la chiami tu nella watchlist
    sku: str
    size_eu: float
    source: str
    price: float
    reference: float
    discount: float
    url: str
    condition: str = "unknown"
    channel: str = "main"
    notes: list[str] = field(default_factory=list)
    listing_title: str = ""  # come la chiama il negozio: serve a te per
                             # accorgerti al volo se ha sbagliato scarpa


def percentile(values: list[float], p: float) -> float | None:
    """Percentile con interpolazione lineare. p in 0-100."""
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * (p / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def compute_reference(history: list[float], external: float | None,
                      min_obs: int) -> tuple[float, str] | None:
    """
    Prezzo di riferimento per una scarpa/taglia.

    Con abbastanza storico usa la MEDIANA (non la media: un annuncio
    fake a 60 € distruggerebbe una media, non una mediana).
    Finche' lo storico e' scarso usa il dato esterno StockX/GOAT,
    cosi' il sistema funziona dal primo giorno invece che tra un mese.
    """
    if len(history) >= min_obs:
        return median(history), "history"
    if external:
        return external, "kicksdb"
    if history:
        return median(history), "bootstrap"
    return None


def evaluate(listing, product, reference: float, history: list[float],
             cfg: dict, budget: float, history_long: list[float] | None = None) -> Deal | None:
    """
    Decide se un annuncio merita una notifica.
    Restituisce None se non e' un affare.

    history      prezzi degli ultimi 30 giorni  -> regola normale
    history_long prezzi degli ultimi 180 giorni -> regola grails
    """
    d = cfg["deal"]
    price = listing.price_eur
    if price <= 0 or reference <= 0:
        return None

    discount = 1.0 - (price / reference)
    notes: list[str] = []

    # --- filtro anti-fake ------------------------------------------
    # Sotto meta' del prezzo di mercato su scarpe come Pushead,
    # Rammellzee o Travis Scott non esistono occasioni: esistono repliche.
    if price < reference * d["fake_floor"]:
        return Deal(
            product_name=product["name"], sku=product["sku"], size_eu=listing.size_eu,
            source=listing.source, price=price, reference=reference,
            discount=discount, url=listing.url, condition=listing.condition,
            channel="suspicious", listing_title=listing.title,
            notes=["Prezzo troppo basso per essere autentico — verifica con estrema attenzione.",
                   "Chiedi foto della scatola, dell'etichetta interna e della suola."],
        )

    # --- soglia manuale per singola scarpa -------------------------
    # Se nella watchlist hai scritto max_price, comandi tu: niente
    # percentile, niente sconto minimo, notifica solo a quel prezzo
    # o meno. Vale unicamente per le scarpe dove l'hai indicato.
    soglia = product.get("max_price")
    if soglia is not None:
        if price > float(soglia):
            return None
        notes.append(f"Sotto la tua soglia di {float(soglia):.0f} € per questa scarpa.")
        if listing.condition == "used":
            notes.append("Annuncio dichiarato come usato — chiedi foto reali.")
        if product.get("vintage"):
            notes.append("Paio vintage: controlla intersuola e collante prima di comprare.")
        return Deal(
            product_name=product["name"], sku=product["sku"], size_eu=listing.size_eu,
            source=listing.source, price=price, reference=reference,
            discount=discount, url=listing.url, condition=listing.condition,
            channel="main", notes=notes, listing_title=listing.title,
        )

    is_grail = bool(product.get("grail") or reference > budget)

    # --- grail sopra budget: regola dedicata -----------------------
    # Qui la soglia del 15% non ha senso: su una scarpa da 1.900 €
    # non scendera' mai cosi' tanto, ma sapere che ha toccato il
    # minimo semestrale e' comunque l'informazione che serve.
    if is_grail and price > budget:
        floor = min(history_long) if history_long else None
        if floor is None or price > floor * 1.02:
            return None
        channel = "grails"
        notes.append(f"Minimo degli ultimi {d['grail_window_days']} giorni.")
        notes.append(f"Sopra il tuo budget di {budget:.0f} € — solo per seguire il mercato.")

    # --- regola normale --------------------------------------------
    else:
        if price > budget:
            return None
        if discount < d["min_discount"]:
            return None
        if len(history) >= d["min_observations"]:
            threshold = percentile(history, d["percentile"])
            if threshold is not None and price > threshold:
                return None
        # con poco storico ci si affida al solo sconto minimo
        channel = "main"
        if is_grail:
            notes.append("Grail sotto budget: occasione rara, verifica bene l'autenticita'.")

    # --- avvisi sui paia vintage -----------------------------------
    if product.get("vintage"):
        notes.append("Paio vintage: controlla intersuola e collante prima di comprare.")

    if listing.condition == "used":
        notes.append("Annuncio dichiarato come usato — chiedi foto reali.")

    return Deal(
        product_name=product["name"], sku=product["sku"], size_eu=listing.size_eu,
        source=listing.source, price=price, reference=reference,
        discount=discount, url=listing.url, condition=listing.condition,
        channel=channel, notes=notes, listing_title=listing.title,
    )


def should_notify(con, deal: Deal, cfg: dict) -> bool:
    """
    Anti-spam: non ripete la stessa notifica se non e' passato
    abbastanza tempo o il prezzo non e' sceso ancora.
    """
    from datetime import datetime, timezone
    from . import db

    a = cfg["alerts"]
    prev = db.last_alert(con, db.fingerprint(deal.sku, deal.size_eu, deal.source))
    if prev is None:
        return True

    hours = (datetime.now(timezone.utc) - datetime.fromisoformat(prev["ts"])).total_seconds() / 3600
    if hours >= a["cooldown_hours"]:
        return True
    # entro il cooldown notifica solo se e' sceso ancora sensibilmente
    return deal.price <= prev["price_eur"] * (1 - a["redrop_pct"])


def rejected_by_keywords(text: str, keywords: list[str]) -> str | None:
    """
    Scarta repliche, box vuote, magliette e taglie bambino.
    Restituisce la parola incriminata, o None se l'annuncio va bene.

    Confronto per parole intere: cercare "tee" come sottostringa
    scarterebbe anche "steel" e "canteen".
    """
    from .matching import normalize

    norm = " " + normalize(text) + " "
    for kw in keywords:
        k = normalize(kw).strip()
        if k and f" {k} " in norm:
            return kw
    return None
