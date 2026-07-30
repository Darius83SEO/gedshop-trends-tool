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

## Fase 0 — da validare con le tue API

Nel tab **🔧 Debug** lancia una keyword di test (es. `agende`) e controlla il
*raw payload* DataForSEO: verifica il formato di `google_trends_graph` e delle
related/rising queries. Il parser è difensivo ma va confermato sulla risposta reale.
Da chiarire anche se l'endpoint accetta i **Topic** (`/m/...`) o solo keyword-stringa:
in v1 lavoriamo su search term nel mercato scelto.

## File

| File | Ruolo |
|------|-------|
| `app.py` | UI Streamlit (4 tab) |
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
