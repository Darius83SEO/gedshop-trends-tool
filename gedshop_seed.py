"""Preset categorie di primo livello di Gedshop.it (lette dal menu live, lug 2026).

`query_term` = il termine di ricerca generico da interrogare su Google Trends.
NOTA (Fase 0): usiamo il termine GENERICO (es. 'agende', 'felpe') e non quello
promozionale ('agende personalizzate'), perche' su Trends il long-tail B2B ha
volume troppo basso per una curva stagionale pulita. La stagionalita' del
termine generico e' comunque quella che guida il timing editoriale.
Modificabile a mano nel tool se un termine risulta poco significativo.
"""

SITE_URL = "gedshop.it"

GEDSHOP_CATEGORIES = [
    # Agende e Calendari stanno sulla stessa pagina di categoria ma hanno
    # stagionalita' diverse: due chiamate Trends distinte, due schede separate.
    {"name": "Agende",                  "query_term": "agende",              "url": "https://www.gedshop.it/gadget-agende-calendari"},
    {"name": "Calendari",               "query_term": "calendari",           "url": "https://www.gedshop.it/gadget-agende-calendari"},
    {"name": "Abbigliamento Sportivo",  "query_term": "abbigliamento sportivo", "url": "https://www.gedshop.it/abbigliamento-sportivo"},
    {"name": "Abbigliamento da Lavoro", "query_term": "abbigliamento da lavoro", "url": "https://www.gedshop.it/abbigliamento-da-lavoro"},
    {"name": "Magliette",               "query_term": "magliette",           "url": "https://www.gedshop.it/magliette-personalizzate"},
    {"name": "Felpe",                   "query_term": "felpe",               "url": "https://www.gedshop.it/felpe"},
    {"name": "Cappelli",                "query_term": "cappelli",            "url": "https://www.gedshop.it/cappelli-personalizzati"},
    {"name": "Penne",                   "query_term": "penne",               "url": "https://www.gedshop.it/gadget-penne"},
    {"name": "Borracce",                "query_term": "borracce",            "url": "https://www.gedshop.it/gadget-borracce"},
    {"name": "Shopper",                 "query_term": "shopper",             "url": "https://www.gedshop.it/gadget-shopper-personalizzate"},
    {"name": "Sacche e Borse",          "query_term": "zaini",               "url": "https://www.gedshop.it/gadget-borse"},
    {"name": "Ombrelli",                "query_term": "ombrelli",            "url": "https://www.gedshop.it/gadget"},
    {"name": "Portachiavi",             "query_term": "portachiavi",         "url": "https://www.gedshop.it/gadget"},
]
