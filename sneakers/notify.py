"""
Notifiche Telegram.

Tre canali distinti, cosi' le occasioni vere non vengono sepolte:
  main        -> affari sotto budget, quelli che ti interessano davvero
  grails      -> minimi storici sulle scarpe fuori budget (Mocha, SB Travis)
  suspicious  -> prezzi troppo bassi per essere veri: probabili fake
"""

import os
import html
import httpx

API = "https://api.telegram.org/bot{token}/sendMessage"

_EMOJI = {"main": "🔥", "grails": "👑", "suspicious": "⚠️"}


def _chat_id(channel: str) -> str | None:
    """
    I canali grails/suspicious possono avere una chat dedicata.
    Se non impostati, ricadono sulla chat principale.
    """
    specific = os.environ.get(f"TELEGRAM_CHAT_ID_{channel.upper()}")
    return specific or os.environ.get("TELEGRAM_CHAT_ID")


def send(text: str, channel: str = "main", disable_preview: bool = False) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = _chat_id(channel)
    if not token or not chat:
        print(f"[notify] TELEGRAM_BOT_TOKEN/CHAT_ID mancanti, notifica non inviata:\n{text}\n")
        return False
    try:
        r = httpx.post(
            API.format(token=token),
            json={
                "chat_id": chat,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": disable_preview,
            },
            timeout=20,
        )
        if r.status_code != 200:
            print(f"[notify] Telegram ha risposto {r.status_code}: {r.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"[notify] invio fallito: {type(e).__name__}: {e}")
        return False


def deal_message(deal) -> str:
    """Compone la notifica di un affare."""
    e = html.escape
    saving = deal.reference - deal.price
    pct = int(round(deal.discount * 100))

    lines = [
        f"{_EMOJI.get(deal.channel, '🔥')} <b>{e(deal.product_name)}</b>",
    ]

    # Il titolo con cui il negozio la vende. Va mostrato sempre: e' il
    # modo piu' rapido per accorgersi se il sistema ha preso la scarpa
    # sbagliata, senza dover aprire il link.
    if deal.listing_title:
        lines.append(f"<i>in vendita come: {e(deal.listing_title)}</i>")

    lines += [
        "",
        f"💶 <b>{deal.price:.0f} €</b>   <s>{deal.reference:.0f} €</s>   "
        f"<b>-{pct}%</b>  (risparmi {saving:.0f} €)",
        f"📏 Taglia <b>EU {deal.size_eu:g}</b>",
        f"🏪 {e(deal.source)}",
        f"🔖 <code>{e(deal.sku)}</code>",
    ]

    if deal.condition and deal.condition != "unknown":
        cond = {"new": "Nuove", "used": "Usate"}.get(deal.condition, deal.condition)
        lines.append(f"🏷️ {cond}")

    if deal.notes:
        lines.append("")
        lines += [f"<i>{e(n)}</i>" for n in deal.notes]

    lines += ["", f'<a href="{e(deal.url)}">➡️ Apri l\'annuncio</a>']
    return "\n".join(lines)


def summary_message(scanned: int, found: int, errors: list[str]) -> str:
    """Riepilogo tecnico, utile solo se qualcosa si e' rotto."""
    lines = [f"📊 Scansione completata — {scanned} annunci esaminati, {found} affari"]
    if errors:
        lines.append("")
        lines.append("<b>Problemi:</b>")
        lines += [f"• {html.escape(x)}" for x in errors[:10]]
    return "\n".join(lines)
