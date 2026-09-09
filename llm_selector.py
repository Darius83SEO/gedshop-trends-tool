"""Selezione automatica della sorgente Google Trends piu' allineata al prodotto.

Per ogni categoria l'LLM legge la lista dei candidati (search term + Topic con il
loro `type`, come il menu di Google Trends) e sceglie quello che rappresenta la
DOMANDA reale del prodotto, scartando i significati fuori tema (es. 'penne'=pasta,
'shopper'=catena di farmacie, 'agende'=identita' di genere). Non fa conti e non
scarica dati: legge solo titolo+tipo. Una chiamata piccola per categoria.

Il modello e' intercambiabile (ChatGPT / Gemini Flash / Claude Sonnet): si sceglie
dalla sidebar, il prompt e la logica di parsing restano identici per tutti.

Fallback: se non c'e' la key o l'LLM fallisce, si usa la regola euristica di
resolver.decide().
"""
from __future__ import annotations

import json
import re
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
    alt_mid: str | None = None    # miglior Topic alternativo (per il confronto)
    alt_title: str | None = None
    alt_type: str | None = None


_SYSTEM = "Sei un analista SEO. Rispondi solo JSON valido."

# Schema della risposta: usato dove il provider sa vincolarla (Claude).
_SCHEMA = {
    "type": "object",
    "properties": {
        "choice": {"type": "integer"},
        "choice_title": {"type": "string"},
        "alt": {"type": "integer"},
        "confidence": {"type": "string", "enum": ["alta", "media", "bassa"]},
        "reason": {"type": "string"},
    },
    "required": ["choice", "choice_title", "alt", "confidence", "reason"],
    "additionalProperties": False,
}

# timeout stretto + poche retry: evita blocchi lunghi se l'API non risponde
_TIMEOUT_S = 25.0


def _extract_json(text: str) -> dict:
    """JSON dalla risposta, tollerante a ```json ... ``` o testo attorno."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def _ask_openai(conf: dict, prompt: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=conf["key"], timeout=_TIMEOUT_S, max_retries=1)
    resp = client.chat.completions.create(
        model=conf["model"],
        messages=[{"role": "system", "content": _SYSTEM},
                  {"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content


def _ask_gemini(conf: dict, prompt: str) -> str:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=conf["key"],
                          http_options=types.HttpOptions(timeout=int(_TIMEOUT_S * 1000)))
    resp = client.models.generate_content(
        model=conf["model"],
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            temperature=0,
            response_mime_type="application/json",
            # compito di sola classificazione: niente ragionamento, meno costo
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return resp.text


def _ask_anthropic(conf: dict, prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=conf["key"], timeout=_TIMEOUT_S, max_retries=1)
    # niente temperature: i modelli Sonnet 5 / 4.6 la rifiutano (400)
    kwargs = dict(model=conf["model"], max_tokens=4096, system=_SYSTEM,
                  messages=[{"role": "user", "content": prompt}])
    try:
        resp = client.messages.create(
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": _SCHEMA}},
            **kwargs)
    except Exception:
        # SDK vecchio o modello senza structured outputs: il JSON e' gia'
        # richiesto nel prompt, _extract_json fa il resto.
        resp = client.messages.create(**kwargs)
    return next((b.text for b in resp.content if b.type == "text"), "")


_ASK = {"openai": _ask_openai, "gemini": _ask_gemini, "anthropic": _ask_anthropic}


def _ask_llm(prompt: str) -> str:
    return _ASK[config.get_llm_provider()](config.llm_conf(), prompt)


def _build_prompt(query_term, category_name, candidates):
    lines = [f"[0] Query di ricerca \"{query_term}\" (ricerca letterale: include TUTTI i "
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
        f"astratto). Scarta SEMPRE i singoli prodotti di marca e le linee di prodotto "
        f"(es. \"Levi's Felpa ... - Blu\"): servono concetti generici di categoria. "
        f"Preferisci un Topic pertinente (piu' preciso e pulito); se nessun Topic "
        f"corrisponde davvero al prodotto, scegli la Query di ricerca [0].\n\n"
        f"Opzioni:\n{opts}\n\n"
        f"Indica anche la tua CONFIDENZA nella scelta: \"alta\" se una sola opzione "
        f"e' chiaramente giusta; \"media\" se plausibile ma con qualche dubbio; "
        f"\"bassa\" se la parola e' ambigua o nessuna opzione e' davvero pertinente.\n"
        f"Indica infine \"alt\": il numero del Topic piu' plausibile DIVERSO da quello "
        f"scelto, da mostrare come confronto a chi valida (0 se nessun altro Topic ha "
        f"senso per questo prodotto).\n"
        f"Rispondi SOLO in JSON: {{\"choice\": <numero>, \"choice_title\": \"<il titolo "
        f"ESATTO dell'opzione scelta, copiato carattere per carattere>\", \"alt\": <numero>, "
        f"\"confidence\": \"alta|media|bassa\", "
        f"\"reason\": \"<breve motivazione in italiano, max 25 parole>\"}}"
    )


def _resolve_choice(idx: int, title: str, candidates: list) -> int:
    """Indice del candidato scelto (0 = query di ricerca), coerente col titolo.

    Il numero e il titolo restituiti dall'LLM possono divergere (capitato con
    'felpe': motivazione su «Sweatshirts & Hoodies» ma indice del prodotto Levi's).
    Il titolo e' il segnale piu' affidabile: se corrisponde a un candidato, vince lui.
    """
    t = (title or "").strip().lower()
    if t:
        for i, c in enumerate(candidates, start=1):
            if (c.title or "").strip().lower() == t:
                return i
        if t.startswith("query di ricerca") or t.strip('"') == "":
            return 0
    return idx


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
        data = _extract_json(_ask_llm(prompt))
        idx = _resolve_choice(int(data.get("choice", 0)),
                              str(data.get("choice_title", "")), candidates)
        reason = str(data.get("reason", "")).strip()
        confidence = str(data.get("confidence", "media")).strip().lower()
        if confidence not in ("alta", "media", "bassa"):
            confidence = "media"
        try:
            alt_i = int(data.get("alt", 0))
        except (TypeError, ValueError):
            alt_i = 0
        alt = candidates[alt_i - 1] if 0 < alt_i <= len(candidates) and alt_i != idx else None
    except Exception as e:
        fb = _heuristic(query_term, candidates)
        fb.reason = f"{config.llm_label()} non disponibile ({e}); {fb.reason}"
        return fb

    # va rivisto da un umano se l'LLM non e' sicuro, oppure se la stringa e'
    # intrinsecamente ambigua (Google associa la parola prima a un'entita').
    entity_first = bool(candidates) and candidates[0].kind == "entity"
    needs_review = confidence != "alta" or entity_first

    def _alt_fields(exclude_mid=None):
        a = alt if (alt and alt.mid != exclude_mid) else None
        return {"alt_mid": a.mid if a else None, "alt_title": a.title if a else None,
                "alt_type": a.type if a else None}

    if idx <= 0 or idx > len(candidates):
        return SourceChoice(mode="term", mid=None, title=None, type=None,
                            reason=reason or f"Query di ricerca «{query_term}»: nessun Topic pertinente.",
                            via="llm", confidence=confidence, needs_review=needs_review,
                            **_alt_fields())
    c = candidates[idx - 1]

    # rete di sicurezza: un'entita' specifica (linea di prodotti, marca, film...)
    # non e' mai la categoria merceologica. Se esiste un concetto generico, usa quello.
    if c.kind == "entity":
        sub = next((x for x in candidates if x.kind != "entity"), None)
        if sub is not None:
            reason = (f"{reason} (corretto: «{c.title}» [{c.type}] e' un prodotto "
                      f"specifico, uso il concetto «{sub.title}»)").strip()
            c, needs_review = sub, True
        else:
            return SourceChoice(mode="term", mid=None, title=None, type=None,
                                reason=(f"{reason} (i Topic disponibili sono entita' "
                                        f"specifiche: uso la query di ricerca)").strip(),
                                via="llm", confidence=confidence, needs_review=True,
                                **_alt_fields())

    return SourceChoice(mode="topic", mid=c.mid, title=c.title, type=c.type,
                        reason=reason or f"Topic «{c.title}» [{c.type}].", via="llm",
                        confidence=confidence, needs_review=needs_review,
                        **_alt_fields(exclude_mid=c.mid))


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
