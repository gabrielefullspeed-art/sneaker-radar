from .base import Source, Listing
from .shopify import ShopifySource
from .ebay import EbaySource
from .kicksdb import KicksDBReference
from .wethenew import WethenewSource


def build_sources(cfg, fx) -> list[Source]:
    """Costruisce le sorgenti d'acquisto attive secondo config.yaml."""
    sources: list[Source] = []

    sh = cfg["sources"].get("shopify", {})
    if sh.get("enabled"):
        for store in sh.get("stores", []):
            sources.append(ShopifySource(cfg, fx, store))

    wtn = cfg["sources"].get("wethenew", {})
    if wtn.get("enabled"):
        sources.append(WethenewSource(cfg, fx, wtn))

    eb = cfg["sources"].get("ebay", {})
    if eb.get("enabled"):
        s = EbaySource(cfg, fx)
        if s.available:
            sources.append(s)
        else:
            print("  · eBay saltato: EBAY_CLIENT_ID/SECRET non impostati")

    return sources


__all__ = ["Source", "Listing", "ShopifySource", "EbaySource",
           "KicksDBReference", "WethenewSource", "build_sources"]
