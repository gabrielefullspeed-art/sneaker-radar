"""
Riconoscere la scarpa giusta.

Sembra banale, non lo e'. Le boutique usano SKU interni propri
(Slam Jam scrive J360252, non DM7866-200), quindi il codice modello
spesso non compare da nessuna parte e bisogna riconoscere la scarpa
dal nome. Ma "Travis Scott Air Jordan 1 Low" da solo non basta:
esistono la Mocha, la Reverse Mocha, la Olive, le versioni bambino.

Regole, per ogni scarpa in watchlist.yaml:

    match:   TUTTI questi devono comparire nel testo.
             Dentro una voce, "|" separa alternative equivalenti:
             "off-white|off white" accetta entrambe le grafie.
    exclude: se compare anche solo uno di questi, si scarta.

Lo SKU, quando c'e', vince su tutto e conferma da solo.
"""

import re


def normalize(text: str) -> str:
    """Minuscole, accenti via, punteggiatura in spazi."""
    text = str(text).lower()
    for a, b in (("à", "a"), ("è", "e"), ("é", "e"), ("ì", "i"), ("ò", "o"), ("ù", "u")):
        text = text.replace(a, b)
    return re.sub(r"[^a-z0-9]+", " ", text)


def sku_present(text: str, sku: str) -> bool:
    """Cerca lo SKU sia come 'DM7866-200' sia come 'DM7866200' o 'DM7866'."""
    t = re.sub(r"[^a-z0-9]", "", str(text).lower())
    s = re.sub(r"[^a-z0-9]", "", str(sku).lower())
    if s and s in t:
        return True
    stem = s.split("0")[0] if len(s) > 6 else s
    return len(stem) >= 6 and stem in t


def matches(text: str, product: dict) -> bool:
    """True se il testo descrive davvero la scarpa cercata."""
    if sku_present(text, product["sku"]):
        return True

    norm = " " + normalize(text) + " "

    for bad in product.get("exclude", []):
        if normalize(bad).strip() in norm:
            return False

    required = product.get("match")
    if not required:
        return False                      # senza regole non si indovina

    for group in required:
        alternatives = [normalize(a).strip() for a in str(group).split("|")]
        if not any(a and a in norm for a in alternatives):
            return False

    return True


def search_terms(product: dict) -> list[str]:
    """
    Cosa digitare nella ricerca del sito.

    La ricerca di Shopify fa AND su tutte le parole: query lunghe come
    "Travis Scott Jordan 1 Low Olive" restituiscono zero, mentre
    "Travis Scott" restituisce sei risultati da filtrare. Quindi:
    termini corti, filtro severo dopo.
    """
    terms = list(product.get("terms", []))
    if not terms:
        terms = [product["name"].split("x")[-1].strip()[:20]]
    return terms
