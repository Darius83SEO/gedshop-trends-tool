"""Risoluzione Topic vs Search term con decisione automatica + postilla.

Idea: Google Trends restituisce, per ogni stringa, dei candidati Topic con un
campo `type` (es. 'Capo di abbigliamento', 'Cancelleria', 'Catena di farmacie').
Il `type` e' il segnale: i concetti generici/di prodotto -> Topic affidabile;
le entita' specifiche (aziende, film, personaggi, catene, linee di prodotto)
-> la stringa e' ambigua, meglio il search term.

Per ogni categoria il sistema:
  1. risolve i candidati Topic (autocomplete Google Trends)
  2. sceglie il miglior candidato NON-entita'
  3. assegna una confidenza e decide se attivare Topic o Search term
  4. genera una postilla leggibile ("abbiamo scelto ... perche' ...")
Entrambe le viste restano disponibili: quella non pertinente e' marcata come
'scartata', ma consultabile.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import quote

import requests

AUTOCOMPLETE_URL = "https://trends.google.it/trends/api/autocomplete/{q}"

# type che indicano un'ENTITA' specifica (non un concetto merceologico)
ENTITY_TYPES = [
    "catena", "farmac", "film", "serie tv", "personaggio", "character", "azienda",
    "company", "marca", "marchio", "brand", "squadra", "persona", "cantante",
    "attore", "attrice", "musicale", "band", "videogioco", "video game", "programma",
    "canzone", "album", "linea di prodotti", "modello", "applicazione", "sito web",
    "website", "citta", "città", "stato", "nazione", "organizzazione", "franchise",
    "rivista", "giornale", "libro", "emittente", "politico", "atleta", "youtuber",
]
# type che indicano chiaramente un PRODOTTO/merceologia -> Topic molto affidabile
PRODUCT_TYPES = [
    "abbigliamento", "capo di", "indument", "calzatur", "cancelleria", "aliment",
    "bevand", "strumento", "accessorio", "elettrodomestico", "mobil", "veicolo",
    "cibo", "gioco", "giocattolo", "tessuto", "materiale", "utensile", "arredo",
]
_STOP = {"di", "da", "e", "la", "il", "lo", "gli", "le", "un", "una", "per", "a"}


@dataclass
class TopicCandidate:
    mid: str
    title: str
    type: str

    @property
    def kind(self) -> str:
        tl = (self.type or "").lower()
        if any(k in tl for k in ENTITY_TYPES):
            return "entity"
        if any(k in tl for k in PRODUCT_TYPES):
            return "product"
        return "generic"


@dataclass
class Decision:
    mode: str                 # 'topic' | 'term'  (vista attiva proposta)
    state: str                # 'auto' | 'review' (review = da confermare)
    confidence: str           # 'alta' | 'media' | 'bassa'
    note: str                 # postilla leggibile
    topic: TopicCandidate | None = None
    candidates: list = field(default_factory=list)
    portable_cross_market: bool = False

    @property
    def needs_review(self) -> bool:
        return self.state == "review"


def autocomplete(query: str, hl: str = "it", timeout: int = 20) -> list[TopicCandidate]:
    """Risolve i candidati Topic da Google Trends (endpoint non ufficiale)."""
    url = AUTOCOMPLETE_URL.format(q=quote(query))
    r = requests.get(url, params={"hl": hl, "tz": "-120"}, timeout=timeout,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    txt = r.text
    # la risposta e' prefissata da )]}',
    start = txt.find("{")
    data = json.loads(txt[start:])
    out = []
    for t in data.get("default", {}).get("topics", []):
        out.append(TopicCandidate(mid=t.get("mid", ""), title=t.get("title", ""),
                                  type=t.get("type", "")))
    return out


def _tokens(s: str) -> set:
    return {w for w in re.findall(r"\w+", (s or "").lower()) if w not in _STOP and len(w) > 2}


def _token_match(query: str, title: str) -> bool:
    return bool(_tokens(query) & _tokens(title))


def _fmt_cands(cands: list[TopicCandidate], k: int = 3) -> str:
    return "; ".join(f"«{c.title}» [{c.type}]" for c in cands[:k] if c.title)


def decide(query: str, candidates: list[TopicCandidate]) -> Decision:
    """Sceglie topic vs term in 3 stati e genera la postilla.

    - auto TOPIC: il primo suggerimento di Google e' un concetto di prodotto
      (type merceologico) -> deciso da solo, confidenza alta.
    - auto TERM: nessun candidato utile (solo entita').
    - review: esiste un Topic plausibile ma la stringa e' ambigua (Google la
      associa prima a un'entita', oppure il concetto e' solo 'generico') ->
      va confermato dall'operatore (o da un LLM), con entrambe le viste a fronte.
    """
    if not candidates:
        return Decision(mode="term", state="auto", confidence="alta", candidates=candidates,
                        note=f"Nessun Topic trovato per «{query}»: uso il termine di ricerca.")

    first = candidates[0]
    best = next((c for c in candidates if c.kind != "entity"), None)

    # nessun concetto: solo entita' specifiche
    if best is None:
        return Decision(
            mode="term", state="auto", confidence="alta", topic=None, candidates=candidates,
            note=(f"Nessun Topic pertinente: i candidati sono entita' specifiche "
                  f"({_fmt_cands(candidates)}). Uso il termine di ricerca «{query}»."))

    entity_first = first.kind == "entity"
    is_top = best is first

    # CASO NETTO: il primo suggerimento di Google e' un concetto di prodotto
    if best.kind == "product" and is_top:
        coer = " e coerente col termine" if _token_match(query, best.title) else ""
        return Decision(
            mode="topic", state="auto", confidence="alta", topic=best,
            candidates=candidates, portable_cross_market=True,
            note=(f"Scelto Topic «{best.title}» [{best.type}]: e' il primo suggerimento "
                  f"di Google ed e' un concetto di prodotto{coer}, valido cross-mercato. "
                  f"Confidenza alta."))

    # CASI DA CONFERMARE
    if entity_first:
        return Decision(
            mode="term", state="review", confidence="bassa", topic=best,
            candidates=candidates, portable_cross_market=False,
            note=(f"Stringa ambigua: Google associa «{query}» prima a «{first.title}» "
                  f"[{first.type}] (un'entita'). Ho lasciato attivo il search term; il "
                  f"Topic piu' vicino e' «{best.title}» [{best.type}]. Da confermare. "
                  f"Candidati: {_fmt_cands(candidates)}."))

    # concetto 'generico': plausibile ma non certo (es. agende->agender)
    return Decision(
        mode="topic", state="review", confidence="media", topic=best,
        candidates=candidates, portable_cross_market=True,
        note=(f"Topic proposto «{best.title}» [{best.type}] per «{query}»: e' un concetto "
              f"generico, verifica che sia il significato giusto. Da confermare. "
              f"Candidati: {_fmt_cands(candidates)}."))


def resolve(query: str, hl: str = "it") -> Decision:
    try:
        cands = autocomplete(query, hl=hl)
    except Exception as e:
        return Decision(mode="term", confidence="alta", candidates=[],
                        note=f"Risoluzione Topic non riuscita ({e}): uso il search term.")
    return decide(query, cands)
