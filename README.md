# Gedshop Trends — tool di stagionalità editoriale

Strumento interno che dice ai copywriter **quando pubblicare** in base alla
stagionalità di Google Trends: per ogni categoria del sito calcola quando
storicamente **partono** le ricerche e quando arriva il **picco** (media 5 anni),
e suggerisce il mese entro cui pubblicare.

## Come funziona (in breve)

1. Inserisci l'URL del sito → il tool **crawla** e propone le categorie di primo livello
2. Selezioni/scarti i candidati (revisione manuale)
3. Per ogni categoria una **sola chiamata** DataForSEO scarica 5 anni di storico settimanale
4. Calcolo **deterministico** (nessun LLM): profilo mensile → mese di salita, picco, pubblicazione
5. Due viste: **per categoria** e **calendario editoriale** (cosa scrivere questo mese)

Niente forecasting predittivo, niente riscalatura incrementale, niente LLM nel core:
si fotografa la stagionalità ricorrente, che è il dato robusto e gratuito.

## Setup

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# compila DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD (e DATABASE_URL per Neon)
streamlit run app.py
```

### Credenziali

- **DataForSEO**: obbligatorie per scaricare i trend.
- **DATABASE_URL** (Neon): opzionale in locale. Se assente, i dati vanno in un
  file JSON locale (`data/store.json`). Online (Streamlit Cloud, filesystem
  effimero) serve Neon per la persistenza. Database consigliato: `gedshop_trends`
  (dedicato, tabelle con prefisso `gt_`).

### Modello AI

La scelta della sorgente Trends (Topic vs query di ricerca) la fa un LLM,
selezionabile al volo dalla sidebar (**🤖 AI**) fra ChatGPT, Gemini, Claude e
Grok, con il modello da usare (il primo dell'elenco è il più recente: GPT-6
Astra, Gemini 3.8 Flash, Claude Fable 5.1, Grok 4.6). Serve solo la key del
provider che usi; senza key si ricade sulle regole euristiche di
`resolver.py`. Preselezione via `LLM_PROVIDER` e `*_MODEL`.

## Aggiornamento dei dati

- **Manuale**: sidebar → *Aggiorna tutto* (tutte le categorie) o *Mancanti*
  (solo quelle mai analizzate, consuma meno crediti).
- **Nuova categoria**: sidebar → *➕ Aggiungi categoria*. Alla conferma parte
  la sincronizzazione DataForSEO **solo per quella categoria** e il calendario
  editoriale si aggiorna da solo.
- **Automatico mensile (in-app)**: l'interruttore in sidebar rilancia
  l'aggiornamento completo quando i dati superano i 30 giorni. Attenzione: si
  attiva solo *quando qualcuno apre la dashboard* — Streamlit non ha uno
  scheduler proprio.
- **Automatico vero (cron)**: `sync_monthly.py` gira senza interfaccia.
  ```bash
  0 4 1 * * cd /path/gedshop-trends-tool && python sync_monthly.py >> data/sync.log 2>&1
  ```
  Il `cd` nella cartella serve: da lì lo script legge lo stesso
  `.streamlit/secrets.toml` dell'app. Altrove servono le variabili d'ambiente.

## Le due versioni di Google Trends

Google Trends convive oggi in due varianti con numeri diversi:

- **Explore "classico"**, indice 0-100 **rinormalizzato a ogni richiesta**
  (dipende da intervallo di date e set di keyword confrontate). È quello che
  usa l'endpoint DataForSEO `keywords_data/google_trends/explore/live`, cioè
  questo tool.
- **API ufficiale Google Trends** (alpha su invito da luglio 2025): scala
  **costante** fra richieste, ~1800 giorni di storico, aggregazioni
  giorno/settimana/mese/anno. Valori assoluti diversi per costruzione.

Attenzione a non confonderli con il prodotto **DataForSEO Trends API**, che
non è Google: è dato clickstream proprietario, con numeri suoi.

Ogni record salva `data_source` e `fetched_at` (visibili nel tab *Sorgenti
AI*): se un giorno cambia l'endpoint, si vede subito da dove arriva ogni curva
invece di doverlo dedurre dai numeri.

## Fase 0 — da validare con le tue API

Nel tab **🔧 Debug** lancia una keyword di test (es. `agende`) e controlla il
*raw payload* DataForSEO: verifica il formato di `google_trends_graph` e delle
related/rising queries. Il parser è difensivo ma va confermato sulla risposta reale.
Da chiarire anche se l'endpoint accetta i **Topic** (`/m/...`) o solo keyword-stringa:
in v1 lavoriamo su search term nel mercato scelto.

## File

| File | Ruolo |
|------|-------|
| `app.py` | UI Streamlit (4 tab) + sidebar di comando |
| `dashboard.html` | frontend embeddato (grafici SVG, calendario editoriale) |
| `llm_selector.py` | scelta della sorgente Trends via LLM (ChatGPT/Gemini/Claude/Grok) |
| `analysis.py` | orchestratore: candidati → LLM → DataForSEO → stagionalità |
| `sync_monthly.py` | aggiornamento da cron, senza interfaccia |
| `seasonality.py` | cuore deterministico: profilo mensile, salita/picco/pubblicazione |
| `providers/base.py` | interfaccia astratta provider (switchabile) |
| `providers/dataforseo.py` | client DataForSEO → Google Trends |
| `crawler.py` | estrazione categorie primo livello |
| `storage.py` | persistenza pluggable Neon Postgres / JSON locale |
| `config.py` | secrets, geo map, default |

## Roadmap

- **Fase 2**: integrazione Semrush (keyword idea + volumi) → piano editoriale
- Eventuale narrazione LLM del consiglio (opzionale)
- Multi-mercato (il selettore geo è già predisposto)
