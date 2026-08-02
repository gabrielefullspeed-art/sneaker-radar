# Sneaker Radar

Monitora automaticamente 16 paia di Nike/Jordan su piu' siti e manda una
notifica Telegram quando una scende sotto il suo prezzo di mercato,
indicando **sito, taglia, prezzo e link**.

Gira su GitHub Actions: **a costo zero e con il PC spento**.

---

## Come decide cos'e' un affare

Non usa una soglia fissa. Un annuncio diventa "affare" quando:

1. il prezzo entra nel **10% piu' basso degli ultimi 30 giorni** per quella
   scarpa **in quella taglia**, e
2. e' comunque almeno **15% sotto il prezzo di riferimento**.

Il riferimento e' la **mediana** dello storico (non la media: un annuncio
fake a 60 € rovinerebbe una media, non una mediana). Finche' lo storico
e' scarso usa i prezzi StockX/GOAT via KicksDB, cosi' funziona dal primo
giorno.

**Tre canali Telegram separati:**

| Canale | Cosa ci finisce |
|---|---|
| **main** | affari veri sotto il budget di 1.000 € |
| **grails** | minimi di mercato su Travis Scott Mocha e SB Dunk TS, che stanno stabilmente sopra budget |
| **suspicious** | prezzi sotto il 50% del mercato: quasi sempre repliche, mai mescolati agli affari veri |

---

## Installazione (una volta sola, ~20 minuti)

### 1. Bot Telegram — 3 minuti

1. Su Telegram cerca **@BotFather**, premi Start
2. Scrivi `/newbot`, dai un nome (es. `Sneaker Radar`) e uno username che
   finisca per `bot` (es. `gabriele_sneaker_bot`)
3. BotFather risponde con un **token** tipo `7891234567:AAH...` — copialo
4. Cerca il tuo bot appena creato, aprilo e premi **Start**
5. Per trovare il tuo `chat_id`, cerca **@userinfobot** e premi Start:
   ti risponde con un numero. Quello e' il `TELEGRAM_CHAT_ID`

*(Per i canali separati grails/suspicious: crea due gruppi Telegram,
aggiungici il bot, e usa i loro id. Se non lo fai, tutto arriva nella
chat principale.)*

### 2. eBay — 5 minuti, gratis

1. Vai su **developer.ebay.com**, registrati (account eBay normale va bene)
2. Crea un'applicazione di tipo **Production**
3. Copia **App ID (Client ID)** e **Cert ID (Client Secret)**

### 3. KicksDB — 2 minuti, gratis, senza carta

1. Vai su **kicks.dev**, registrati
2. Copia la **API key** dal pannello
3. Piano free: 1.000 richieste/mese — bastano, il riferimento si aggiorna
   una volta al giorno

### 4. GitHub — 10 minuti

1. Registrati su **github.com** (nessuna carta richiesta)
2. Crea un repository **pubblico** chiamato `sneaker-radar`

   > Pubblico e' consigliato: sui repo pubblici i minuti di Actions non
   > vengono nemmeno conteggiati, quindi **non puoi essere addebitato**.
   > Il token Telegram non finisce nel codice, sta nei Secrets cifrati.
   > L'unica cosa visibile e' la lista delle scarpe.

3. Carica questa cartella nel repository
4. Vai su **Settings -> Secrets and variables -> Actions -> New repository secret**
   e aggiungi:

   | Nome | Valore |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | il token di BotFather |
   | `TELEGRAM_CHAT_ID` | il tuo id numerico |
   | `EBAY_CLIENT_ID` | App ID eBay |
   | `EBAY_CLIENT_SECRET` | Cert ID eBay |
   | `KICKSDB_API_KEY` | chiave KicksDB |
   | `TELEGRAM_CHAT_ID_GRAILS` | *(opzionale)* gruppo separato |
   | `TELEGRAM_CHAT_ID_SUSPICIOUS` | *(opzionale)* gruppo separato |

5. Vai sulla scheda **Actions**, apri *Scansione affari* e premi
   **Run workflow** per il primo giro manuale

Da quel momento gira da solo: **ogni 3 ore**.

---

## Uso da PC (facoltativo)

```bash
pip install -r requirements.txt
```

```bash
python -m sneakers.run doctor
```

Dice quali chiavi mancano e quali siti rispondono.

```bash
python -m sneakers.run telegram
```

Manda un messaggio di prova.

```bash
python -m sneakers.run scan
```

Esegue una scansione completa.

---

## Modificare la watchlist

Apri `watchlist.yaml` e copia un blocco. L'unico campo davvero critico e'
lo **SKU**: e' cio' che permette di riconoscere la stessa scarpa su siti
diversi. Attenzione a `gender` — le uscite WMNS hanno numerazione diversa,
la EU 42 diventa US W 10 invece di US M 8.5.

Soglie, budget e siti si cambiano in `config.yaml`.

---

## Aggiungere un sito

Serve una classe che eredita da `Source` e implementa `search()`.
Se il sito gira su Shopify (moltissime boutique lo fanno) basta
aggiungere una riga in `config.yaml` sotto `sources.shopify.stores`.

Per capire se un sito e' Shopify:

```bash
curl -s "https://IL-SITO/search/suggest.json?q=dunk&resources[type]=product" | head -c 200
```

Se risponde JSON, funziona.

---

## Struttura

```
sneakers/
  run.py          comandi: doctor / reference / scan / telegram
  pricing.py      decide cos'e' un affare (percentile, anti-fake, budget)
  sizes.py        conversione taglie EU/US/UK/cm, uomo e donna
  db.py           storico prezzi SQLite
  notify.py       Telegram, tre canali
  sources/
    shopify.py    boutique europee (verificato: Slam Jam, Asphaltgold,
                  Overkill, Foot District)
    ebay.py       API Browse ufficiale, mercati IT/DE/GB/FR
    kicksdb.py    riferimento StockX/GOAT
```

---

## Limiti noti

- **StockX e GOAT non sono raschiabili** da un server: bloccano per
  fingerprint e IP, non per login. Per questo il riferimento passa da
  KicksDB, che li aggrega legalmente.
- Il piano free KicksDB copre il **mercato US**: ottimo come ancora,
  ma i prezzi europei possono differire. Lo storico interno corregge
  questo scarto nel giro di qualche settimana.
- Alcuni siti (43einhalb, Sivasdescalzo, Oqium) rispondono 403 da IP
  datacenter. Sono marcati `probe: true` in `config.yaml`: al primo giro
  su GitHub si vedra' se dal cloud passano.
- I prezzi **non includono la spedizione**, come richiesto.
