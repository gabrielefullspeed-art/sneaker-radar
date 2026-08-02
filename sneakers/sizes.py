"""
Conversione taglie.

Il problema: ogni sito scrive le taglie a modo suo. Slam Jam usa UK,
Asphaltgold usa EU, eBay US scrive "US 8.5", i giapponesi scrivono i cm,
e le uscite WMNS hanno una numerazione completamente diversa.

Qui tutto viene ricondotto alla taglia EU, che e' quella che l'utente conosce.

  EU 42    = US uomo 8.5 = US donna 10   = UK 7.5 = 26.5 cm
  EU 42.5  = US uomo 9   = US donna 10.5 = UK 8   = 27.0 cm
"""

import re

# Tabella Nike, ancorata alla taglia EU.
# (eu, us_men, us_women, uk, cm)
_TABLE = [
    (38.5, 6.0, 7.5, 5.5, 24.0),
    (39.0, 6.5, 8.0, 6.0, 24.5),
    (40.0, 7.0, 8.5, 6.0, 25.0),
    (40.5, 7.5, 9.0, 6.5, 25.5),
    (41.0, 8.0, 9.5, 7.0, 26.0),
    (42.0, 8.5, 10.0, 7.5, 26.5),
    (42.5, 9.0, 10.5, 8.0, 27.0),
    (43.0, 9.5, 11.0, 8.5, 27.5),
    (44.0, 10.0, 11.5, 9.0, 28.0),
    (44.5, 10.5, 12.0, 9.5, 28.5),
    (45.0, 11.0, 12.5, 10.0, 29.0),
    (45.5, 11.5, 13.0, 10.5, 29.5),
    (46.0, 12.0, 13.5, 11.0, 30.0),
]

_BY_EU = {r[0]: r for r in _TABLE}
_IDX = {"EU": 0, "US_M": 1, "US_W": 2, "UK": 3, "CM": 4}


def eu_to(eu: float, system: str, gender: str = "men") -> float | None:
    """Da EU al sistema richiesto. 'US' si risolve secondo il gender."""
    row = _BY_EU.get(float(eu))
    if row is None:
        return None
    if system == "US":
        system = "US_W" if gender == "women" else "US_M"
    idx = _IDX.get(system)
    return row[idx] if idx is not None else None


def to_eu(value: float, system: str, gender: str = "men") -> float | None:
    """Dal sistema di un sito alla taglia EU."""
    if system == "US":
        system = "US_W" if gender == "women" else "US_M"
    idx = _IDX.get(system)
    if idx is None:
        return None
    for row in _TABLE:
        if abs(row[idx] - value) < 0.01:
            return row[0]
    return None


_FRACTIONS = {"1/3": 0.33, "2/3": 0.67, "1/2": 0.5, "½": 0.5, "⅓": 0.33, "⅔": 0.67}


def _extract_number(text: str) -> float | None:
    """Estrae il primo numero da una stringa, gestendo anche '42 2/3'."""
    text = text.strip()
    for frac, val in _FRACTIONS.items():
        if frac in text:
            base = re.search(r"(\d+)", text)
            if base:
                return float(base.group(1)) + val
    m = re.search(r"(\d+(?:[.,]\d+)?)", text)
    return float(m.group(1).replace(",", ".")) if m else None


def parse_size(raw: str, default_system: str = "auto", gender: str = "men") -> float | None:
    """
    Converte l'etichetta taglia di un sito in taglia EU.

    Accetta forme come: '42', 'EU 42.5', 'US 9', 'UK 7.5', '27cm',
    '8.5 / Grey' (Shopify concatena le varianti), '10W', 'Size 9'.
    Restituisce None se non riesce a interpretarla: meglio saltare
    un annuncio che comprare la taglia sbagliata.
    """
    if raw is None:
        return None
    s = str(raw).strip().upper()

    # Shopify concatena le opzioni: "8.5 / Grey" -> tiene solo la prima
    if "/" in s and not re.match(r"^\d+\s*/\s*\d+$", s):
        s = s.split("/")[0].strip()

    s = s.replace("SIZE", "").replace("TAGLIA", "").strip()
    if not s:
        return None

    # Sistema dichiarato esplicitamente nell'etichetta
    system = None
    if re.search(r"\bEU\b|\bEUR\b", s):
        system = "EU"
    elif re.search(r"\bUK\b", s):
        system = "UK"
    elif re.search(r"\bCM\b|\bJP\b", s):
        system = "CM"
    elif re.search(r"\bUS\s*W\b|\bW\s*US\b|\bWMNS\b|\d+\s*W\b", s):
        system = "US_W"
    elif re.search(r"\bUS\b|\bM\b", s):
        system = "US"

    num = _extract_number(s)
    if num is None:
        return None

    if system is None:
        system = default_system

    # 'auto': indovina dal valore. I range non si sovrappongono molto.
    if system == "auto":
        if num >= 35:
            system = "EU"          # 38-48 -> per forza EU
        elif num >= 24 and num < 32:
            system = "CM"          # 24-31 -> centimetri
        else:
            system = "US"          # 4-15 -> US/UK, si assume US

    if system == "EU":
        # arrotonda ai mezzi punti della tabella (42.4 -> 42.5)
        candidates = [r[0] for r in _TABLE]
        best = min(candidates, key=lambda c: abs(c - num))
        return best if abs(best - num) <= 0.35 else None

    return to_eu(num, system, gender)


def size_labels(eu: float, gender: str = "men") -> list[str]:
    """
    Tutte le stringhe con cui quella taglia puo' comparire su un sito.
    Serve per filtrare i titoli degli annunci (eBay, Vinted...).
    """
    row = _BY_EU.get(float(eu))
    if not row:
        return []
    us = row[2] if gender == "women" else row[1]
    out = []
    for label, val in (("EU", row[0]), ("US", us), ("UK", row[3])):
        txt = f"{val:g}"
        out += [f"{label} {txt}", f"{label}{txt}", txt]
    return list(dict.fromkeys(out))
