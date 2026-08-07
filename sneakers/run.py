"""
Punto di ingresso.

    python -m sneakers.run doctor      controlla chiavi e siti raggiungibili
    python -m sneakers.run reference   aggiorna i prezzi di mercato (1 volta/giorno)
    python -m sneakers.run scan        cerca affari e notifica (8 volte/giorno)
    python -m sneakers.run telegram    invia un messaggio di prova

Su GitHub Actions vengono lanciati 'reference' e 'scan' automaticamente.
"""

import sys
import argparse
from pathlib import Path

# il terminale Windows non digerisce le emoji delle notifiche
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx
import yaml

from . import db, notify, pricing
from .sources import build_sources, KicksDBReference

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    """
    Legge le chiavi dal file .env locale, se c'e'.

    Cosi' le credenziali stanno in un file che NON finisce mai su GitHub
    (e' escluso da .gitignore) e non vanno scritte nei comandi.
    Su GitHub Actions il file non esiste e le chiavi arrivano dai Secrets.
    """
    import os
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)


# ---------------------------------------------------------------- config
def load(name: str):
    with open(ROOT / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def make_fx(cfg):
    """Convertitore di valuta. Tassi live, con fallback offline dal config."""
    rates = dict(cfg.get("fx_fallback", {}))
    try:
        r = httpx.get("https://api.frankfurter.app/latest",
                      params={"from": "EUR", "to": "USD,GBP"}, timeout=10)
        if r.status_code == 200:
            live = r.json().get("rates", {})
            for cur, per_eur in live.items():
                if per_eur:
                    rates[cur] = 1.0 / float(per_eur)   # quanti euro vale 1 unita'
            rates["EUR"] = 1.0
    except Exception:
        print("  · tassi di cambio live non disponibili, uso quelli di riserva")

    def fx(amount: float, currency: str) -> float:
        return float(amount) * rates.get(str(currency).upper(), 1.0)

    return fx


# ---------------------------------------------------------------- comandi
def cmd_doctor(cfg, watch):
    """Verifica cosa funziona e cosa manca, senza inviare notifiche."""
    import os
    print("=== CHIAVI ===")
    for key, what in [
        ("TELEGRAM_BOT_TOKEN", "notifiche (obbligatoria)"),
        ("TELEGRAM_CHAT_ID", "notifiche (obbligatoria)"),
        ("EBAY_CLIENT_ID", "eBay (consigliata)"),
        ("EBAY_CLIENT_SECRET", "eBay (consigliata)"),
        ("KICKSDB_API_KEY", "riferimento StockX/GOAT (opzionale)"),
    ]:
        print(f"  {'OK ' if os.environ.get(key) else '-- '} {key:24} {what}")

    print("\n=== WATCHLIST ===")
    print(f"  {len(watch)} scarpe, taglie EU {cfg['sizes_eu']}, budget {cfg['budget_eur']} €")
    grails = [p["name"] for p in watch if p.get("grail")]
    if grails:
        print(f"  canale grails: {len(grails)} ({', '.join(g[:28] for g in grails)})")

    print("\n=== SITI ===")
    fx = make_fx(cfg)
    for src in build_sources(cfg, fx):
        try:
            got = src.search(watch[0], cfg["sizes_eu"])
            print(f"  OK  {src.name:16} raggiungibile ({len(got)} risultati sul test)")
        except Exception as e:
            print(f"  --  {src.name:16} {type(e).__name__}: {str(e)[:60]}")
    return 0


def cmd_reference(cfg, watch):
    """Aggiorna i prezzi di mercato StockX/GOAT. Da lanciare 1 volta al giorno."""
    con = db.connect(ROOT / "data" / "prices.db")
    fx = make_fx(cfg)
    kdb = KicksDBReference(cfg, fx)

    if not kdb.available:
        print("KICKSDB_API_KEY non impostata: salto (il sistema usera' lo storico interno)")
        return 0

    refresh_h = cfg["sources"]["kicksdb"].get("refresh_hours", 20)
    updated = 0

    for product in watch:
        for size in cfg["sizes_eu"]:
            age = db.reference_age_hours(con, product["sku"], size, "kicksdb")
            if age is not None and age < refresh_h:
                continue                       # gia' fresco, risparmia una richiesta

            # una richiesta per piattaforma copre tutte le taglie
            for etichetta, prezzi in (("kicksdb", kdb.reference_prices(product, cfg["sizes_eu"])),
                                      ("goat", kdb.goat_prices(product, cfg["sizes_eu"]))):
                for s, p in prezzi.items():
                    db.set_reference(con, product["sku"], s, p, etichetta)
                    updated += 1
            break

    con.commit()
    print(f"Riferimenti aggiornati: {updated}")
    return 0


def cmd_scan(cfg, watch):
    """Scansione completa: cerca, valuta, notifica."""
    con = db.connect(ROOT / "data" / "prices.db")
    fx = make_fx(cfg)
    sources = build_sources(cfg, fx)
    sizes = [float(s) for s in cfg["sizes_eu"]]
    budget = float(cfg["budget_eur"])
    reject_kw = cfg["condition"]["reject_keywords"]
    accept_used = cfg["condition"]["accept_used"]

    scanned = 0
    deals: list[pricing.Deal] = []
    errors: list[str] = []

    for product in watch:
        print(f"\n>> {product['name']}")
        for src in sources:
            try:
                listings = src.search(product, sizes)
            except Exception as e:
                errors.append(f"{src.name}/{product['sku']}: {type(e).__name__}")
                continue

            for lst in listings:
                scanned += 1

                if not accept_used and lst.condition == "used":
                    continue
                bad = pricing.rejected_by_keywords(f"{lst.title}", reject_kw)
                if bad:
                    continue

                # Lo storico va letto PRIMA di registrare questo prezzo,
                # altrimenti l'annuncio finisce nel proprio metro di
                # paragone: il minimo storico includerebbe se stesso e
                # la condizione "sei al minimo" sarebbe sempre vera.
                history = db.prices_in_window(con, lst.sku, lst.size_eu,
                                              cfg["deal"]["window_days"])

                # Se nella watchlist hai fissato tu il prezzo di base,
                # quello vince su StockX e sullo storico.
                if product.get("reference"):
                    ref = (float(product["reference"]), "manuale")
                else:
                    ext = db.get_reference(con, lst.sku, lst.size_eu)
                    ref = pricing.compute_reference(
                        history, ext[0] if ext else None, cfg["deal"]["min_observations"]
                    )
                history_long = db.prices_in_window(con, lst.sku, lst.size_eu,
                                                   cfg["deal"]["grail_window_days"])

                if ref is not None:
                    deal = pricing.evaluate(lst, product, ref[0], history, cfg, budget,
                                            history_long=history_long)
                    if deal and pricing.should_notify(con, deal, cfg):
                        deals.append(deal)
                        print(f"   AFFARE {deal.price:.0f}€ (rif {deal.reference:.0f}€) "
                              f"EU{deal.size_eu:g} @ {deal.source}")

                # registrato solo ora, a valutazione conclusa
                db.record_observation(
                    con, sku=lst.sku, size_eu=lst.size_eu, source=lst.source,
                    price_eur=lst.price_eur, condition=lst.condition,
                    url=lst.url, title=lst.title, listing_id=lst.listing_id,
                )

        con.commit()

    # notifiche
    for deal in deals:
        if notify.send(notify.deal_message(deal), channel=deal.channel):
            db.record_alert(con, sku=deal.sku, size_eu=deal.size_eu, source=deal.source,
                            price_eur=deal.price, channel=deal.channel, url=deal.url)

    for src in sources:
        errors += src.errors

    db.prune(con)
    con.commit()
    con.close()

    print(f"\n=== {scanned} annunci esaminati, {len(deals)} affari, {len(errors)} problemi ===")
    for e in errors[:15]:
        print("  !", e)
    return 0


def cmd_setup(cfg, watch):
    """
    Collega il bot Telegram senza dover cercare il chat ID a mano.

    Serve solo TELEGRAM_BOT_TOKEN nel file .env: il resto lo trova da solo
    leggendo chi ha scritto al bot.
    """
    import os
    token = os.environ.get("TELEGRAM_BOT_TOKEN")

    if not token:
        print("Manca TELEGRAM_BOT_TOKEN.\n")
        print("  1. Su Telegram apri @BotFather e premi Start")
        print("  2. Scrivi /newbot, dai un nome e uno username che finisca per 'bot'")
        print("  3. Copia il token che ti risponde (tipo 7891234567:AAH...)")
        print(f"  4. Incollalo nel file  {ROOT / '.env'}  alla riga TELEGRAM_BOT_TOKEN=")
        print("  5. Rilancia questo comando")
        return 1

    # il token e' valido?
    try:
        r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15)
        info = r.json()
        if not info.get("ok"):
            print(f"Il token non e' valido: {info.get('description')}")
            return 1
        bot_name = info["result"].get("username")
        print(f"Bot riconosciuto: @{bot_name}")
    except Exception as e:
        print(f"Non riesco a contattare Telegram: {e}")
        return 1

    # chi ha scritto al bot? da li' si ricava il chat id
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        try:
            upd = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15).json()
        except Exception as e:
            print(f"Non riesco a leggere i messaggi: {e}")
            return 1

        chats = {}
        for u in upd.get("result", []):
            msg = u.get("message") or u.get("channel_post") or {}
            chat = msg.get("chat") or {}
            if chat.get("id"):
                label = chat.get("title") or " ".join(
                    filter(None, [chat.get("first_name"), chat.get("last_name")])
                ) or chat.get("username") or "chat"
                chats[chat["id"]] = f"{label} ({chat.get('type')})"

        if not chats:
            print(f"\nNessun messaggio ricevuto. Apri Telegram, cerca @{bot_name},")
            print("premi START e scrivigli qualsiasi cosa. Poi rilancia questo comando.")
            return 1

        print("\nChat trovate:")
        for cid, label in chats.items():
            print(f"   TELEGRAM_CHAT_ID={cid}     {label}")
        print(f"\nCopia la riga giusta nel file  {ROOT / '.env'}  e rilancia.")
        return 1

    print(f"Chat ID gia' configurato: {chat_id}")
    return cmd_telegram(cfg, watch)


def cmd_telegram(cfg, watch):
    ok = notify.send(
        "✅ <b>Sneaker Radar attivo</b>\n\n"
        f"Monitoro <b>{len(watch)}</b> scarpe in taglia EU "
        f"{', '.join(str(s) for s in cfg['sizes_eu'])}.\n"
        f"Budget: <b>{cfg['budget_eur']} €</b>\n\n"
        "Se leggi questo messaggio, le notifiche funzionano."
    )
    print("Inviato." if ok else "Invio fallito: controlla TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID.")
    return 0 if ok else 1


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="Sneaker Radar")
    ap.add_argument("command", choices=["setup", "doctor", "reference", "scan", "telegram"])
    args = ap.parse_args(argv)

    load_env()
    cfg = load("config.yaml")
    watch = load("watchlist.yaml")

    return {
        "setup": cmd_setup,
        "doctor": cmd_doctor,
        "reference": cmd_reference,
        "scan": cmd_scan,
        "telegram": cmd_telegram,
    }[args.command](cfg, watch)


if __name__ == "__main__":
    sys.exit(main())
