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
    """
    Cerca lo SKU completo, sia come 'DM7866-200' sia come 'DM7866200'.

    Solo la corrispondenza intera: cercare frammenti come 'DM7866'
    faceva scattare falsi positivi tra colorway della stessa serie.
    """
    t = re.sub(r"[^a-z0-9]", "", str(text).lower())
    s = re.sub(r"[^a-z0-9]", "", str(sku).lower())
    return bool(s) and s in t


_CODICE = re.compile(r"\b([A-Z]{2}\d{4}|\d{6})[\s-]?(\d{3})\b")


def codici_modello(text: str) -> set[str]:
    """Tutti i codici modello presenti nel testo, normalizzati."""
    return {a + b for a, b in _CODICE.findall(str(text).upper())}


def codice_contrastante(text: str, sku: str) -> str | None:
    """
    Il controllo piu' affidabile che esista, perche' non dipende dai nomi.

    I negozi scrivono il codice modello nel titolo: "FD8778 001".
    Se il testo espone un codice e NON e' il nostro, e' un'altra scarpa,
    per quanto il nome si assomigli. E' cosi' che si distingue la
    Rammellzee Low (FD8778) dalla High (FD8779), o la Air Ship
    "Every Game" (DZ3497-104) dalla "Tech Grey" (DZ3497-100).

    Restituisce il codice estraneo trovato, o None se va tutto bene.
    """
    trovati = codici_modello(text)
    if not trovati:
        return None                       # nessun codice: decidono i nomi
    nostro = re.sub(r"[^A-Z0-9]", "", str(sku).upper())
    if nostro in trovati:
        return None
    return sorted(trovati)[0]


def matches(text: str, product: dict) -> bool:
    """
    True se il testo descrive davvero la scarpa cercata.

    Lo SKU NON basta da solo: Kick Game pubblica la Travis Scott
    "Shy Pink" con il codice DM7866-200, che appartiene alla
    "Medium Olive". Fidarsi del solo codice avrebbe generato un finto
    affare da 550 €. Quindi le regole sul nome comandano sempre, e
    l'exclude ha sempre potere di veto.
    """
    # Prima di tutto: se l'annuncio dichiara un codice modello diverso
    # dal nostro, e' un'altra scarpa. Nessun nome puo' smentirlo.
    if codice_contrastante(text, product["sku"]):
        return False

    norm = " " + normalize(text) + " "

    # Confronto per parole intere, non per sottostringhe: exclude corti
    # come "ps", "gs" o "td" scattavano dentro "drops", "leggings",
    # "outdated" e facevano scartare annunci giusti.
    def presente(termine: str) -> bool:
        t = normalize(termine).strip()
        return bool(t) and f" {t} " in norm

    for bad in product.get("exclude", []):
        if presente(bad):
            return False

    required = product.get("match")
    if required:
        for group in required:
            if not any(presente(a) for a in str(group).split("|")):
                return False
        return True

    # senza regole sul nome resta lo SKU come unica conferma
    return sku_present(text, product["sku"])


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
