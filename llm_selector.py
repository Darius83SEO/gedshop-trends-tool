"""Selezione automatica della sorgente Google Trends piu' allineata al prodotto.

Per ogni categoria l'LLM legge la lista dei candidati (search term + Topic con il
loro `type`, come il menu di Google Trends) e sceglie quello che rappresenta la
DOMANDA reale del prodotto, scartando i significati fuori tema (es. 'penne'=pasta,
'shopper'=catena di farmacie, 'agende'=identita' di genere). Non fa conti e non
scarica dati: legge solo titolo+tipo. Una chiamata piccola per categoria.

Fallback: se non c'e' la key o l'LLM fallisce, si usa la regola euristica di
resolver.decide().
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import config
import resolver


@dataclass
class SourceChoice:
    mode: str                 # 'topic' | 'term'
    mid: str | None           # mid del topic scelto (None se term)
    title: str | None         # titolo topic scelto
    type: str | None          # type topic scelto
    reason: str               # postilla leggibile
    via: str                  # 'llm' | 'euristica'
    confidence: str = "media"     # 'alta' | 'media' | 'bassa'
    needs_review: bool = False    # True => va validato da un umano


def _client():
    from openai import OpenAI
    # timeout stretto + poche retry: evita blocchi lunghi se l'API non risponde
    return OpenAI(api_key=config.OPENAI_API_KEY, timeout=25.0, max_retries=1)


def _build_prompt(query_term, category_name, candidates):
    lines = [f"[0] Search term \"{query_term}\" (ricerca letterale: include TUTTI i "
             f"significati della parola)"]
    for i, c in enumerate(candidates, start=1):
        lines.append(f"[{i}] Topic \"{c.title}\" — tipo: {c.type}")
    opts = "\n".join(lines)
    return (
        f"{config.BUSINESS_CONTEXT}\n\n"
        f"Categoria da analizzare: \"{category_name}\" (prodotto cercato: "
        f"\"{query_term}\", mercato Italia).\n\n"
        f"Devi scegliere UNA sorgente Google Trends che rappresenti la domanda di "
        f"ricerca per QUESTO PRODOTTO FISICO. Scarta i significati fuori tema "
        f"(es. una parola che indica anche un cibo, un'azienda, un film, un concetto "
        f"astratto). Preferisci un Topic pertinente (piu' preciso e pulito); se "
        f"nessun Topic corrisponde davvero al prodotto, scegli il Search term [0].\n\n"
        f"Opzioni:\n{opts}\n\n"
        f"Indica anche la tua CONFIDENZA nella scelta: \"alta\" se una sola opzione "
        f"e' chiaramente giusta; \"media\" se plausibile ma con qualche dubbio; "
        f"\"bassa\" se la parola e' ambigua o nessuna opzione e' davvero pertinente.\n"
        f"Rispondi SOLO in JSON: {{\"choice\": <numero>, \"confidence\": "
        f"\"alta|media|bassa\", \"reason\": \"<breve motivazione in italiano, max 25 parole>\"}}"
    )


def choose_source(query_term: str, category_name: str,
                  candidates: list | None = None) -> SourceChoice:
    if candidates is None:
        try:
            candidates = resolver.autocomplete(query_term)
        except Exception:
            candidates = []
    candidates = candidates[:6]

    # senza key o senza candidati -> euristica
    if not config.has_llm() or not candidates:
        return _heuristic(query_term, candidates)

    try:
        prompt = _build_prompt(query_term, category_name, candidates)
        resp = _client().chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Sei un analista SEO. Rispondi solo JSON valido."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        idx = int(data.get("choice", 0))
        reason = str(data.get("reason", "")).strip()
        confidence = str(data.get("confidence", "media")).strip().lower()
        if confidence not in ("alta", "media", "bassa"):
            confidence = "media"
    except Exception as e:
        fb = _heuristic(query_term, candidates)
        fb.reason = f"LLM non disponibile ({e}); {fb.reason}"
        return fb

    # va rivisto da un umano se l'LLM non e' sicuro, oppure se la stringa e'
    # intrinsecamente ambigua (Google associa la parola prima a un'entita').
    entity_first = bool(candidates) and candidates[0].kind == "entity"
    needs_review = confidence != "alta" or entity_first

    if idx <= 0 or idx > len(candidates):
        return SourceChoice(mode="term", mid=None, title=None, type=None,
                            reason=reason or f"Search term «{query_term}»: nessun Topic pertinente.",
                            via="llm", confidence=confidence, needs_review=needs_review)
    c = candidates[idx - 1]
    return SourceChoice(mode="topic", mid=c.mid, title=c.title, type=c.type,
                        reason=reason or f"Topic «{c.title}» [{c.type}].", via="llm",
                        confidence=confidence, needs_review=needs_review)


def _heuristic(query_term, candidates) -> SourceChoice:
    dec = resolver.decide(query_term, candidates or [])
    review = dec.needs_review
    if dec.mode == "topic" and dec.topic:
        return SourceChoice(mode="topic", mid=dec.topic.mid, title=dec.topic.title,
                            type=dec.topic.type, reason=dec.note, via="euristica",
                            confidence=dec.confidence, needs_review=review)
    return SourceChoice(mode="term", mid=None, title=None, type=None,
                        reason=dec.note, via="euristica",
                        confidence=dec.confidence, needs_review=review)
