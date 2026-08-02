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

## Installazione

Le chiavi si incollano **una sola volta** nel file `.env` (gia' creato, vuoto).
Quel file resta solo sul tuo PC: e' escluso dal repository.

### Passo 1 — Bot Telegram (3 min, obbligatorio)

1. Su Telegram apri **@BotFather**, premi Start
2. Scrivi `/newbot`, dai un nome (es. `Sneaker Radar`) e uno username
   che finisca per `bot`
3. Copia il **token** che ti risponde e incollalo in `.env`, riga
   `TELEGRAM_BOT_TOKEN=`
4. Apri il bot appena creato e scrivigli un messaggio qualsiasi
5. Lancia:

```bash
python -m sneakers.run setup
```

Il comando trova da solo il tuo `TELEGRAM_CHAT_ID` e te lo stampa:
incollalo in `.env` e rilancia. Se tutto e' a posto ricevi un messaggio
di conferma sul telefono.

### Passo 2 — eBay (5 min, gratis)

E' la sorgente piu' importante: le scarpe di questa watchlist sono tutte
sold out nei negozi, eBay e' dove compaiono davvero.

1. **developer.ebay.com** -> registrati (va bene il tuo account eBay)
2. Crea un'applicazione **Production**
3. Copia **App ID** e **Cert ID** in `.env`

### Passo 3 — KicksDB (2 min, gratis, facoltativo)

1. **kicks.dev** -> registrati, nessuna carta richiesta
2. Copia la API key in `.env`

Senza questa chiave il sistema funziona lo stesso, ma impiega qualche
settimana a costruirsi da solo i prezzi di riferimento.

### Passo 4 — GitHub (10 min)

Serve solo per far girare tutto a PC spento. Il repository locale e'
**gia' pronto e committato**.

1. Registrati su **github.com** (nessuna carta richiesta)
2. Crea un repository **pubblico** vuoto chiamato `sneaker-radar`,
   senza README ne' .gitignore

   > Pubblico e' consigliato: sui repo pubblici i minuti di Actions non
   > vengono nemmeno conteggiati, quindi **non puoi essere addebitato**.
   > Le chiavi non stanno nel codice ma nei Secrets cifrati.

3. Collega e carica:

```bash
git remote add origin https://github.com/TUO-UTENTE/sneaker-radar.git
```

```bash
git push -u origin main
```

4. Su GitHub: **Settings -> Secrets and variables -> Actions ->
   New repository secret**, e aggiungi gli stessi valori del tuo `.env`:

   | Nome | Obbligatorio |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | si' |
   | `TELEGRAM_CHAT_ID` | si' |
   | `EBAY_CLIENT_ID` | consigliato |
   | `EBAY_CLIENT_SECRET` | consigliato |
   | `KICKSDB_API_KEY` | facoltativo |
   | `TELEGRAM_CHAT_ID_GRAILS` | facoltativo |
   | `TELEGRAM_CHAT_ID_SUSPICIOUS` | facoltativo |

5. Scheda **Actions** -> *Scansione affari* -> **Run workflow**

Da quel momento gira da solo, **ogni 3 ore**, anche a PC spento.

---

## Comandi

```bash
python -m sneakers.run setup
```

Collega il bot Telegram e trova il chat ID da solo.

```bash
python -m sneakers.run doctor
```

Dice quali chiavi mancano e quali siti rispondono.

```bash
python -m sneakers.run scan
```

Esegue una scansione completa e notifica gli affari.

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
