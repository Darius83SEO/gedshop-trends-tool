"""Orchestratore: da una categoria al record completo pronto per il DB.

Per ogni categoria:
  1. risolve i candidati Google Trends (resolver.autocomplete)
  2. l'LLM sceglie la sorgente allineata al prodotto (llm_selector)
  3. scarica la/le sorgente/i da DataForSEO (5 anni + finestra 90gg)
  4. calcola la stagionalita' deterministica (seasonality) per ogni vista
Restituisce sia la vista Search term sia la vista Topic (quando esiste), con
la sorgente attiva gia' decisa. Nessun LLM nei calcoli di stagionalita'.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import config
import llm_selector
import resolver
import seasonality as S


# sotto questa soglia la serie 5 anni e' troppo bucata per una stagionalita'
# affidabile (5 anni settimanali = ~263 punti; certi Topic ne restituiscono 2-3)
MIN_SERIES_POINTS = 40


def _view(provider, source_kw: str, geo: str) -> dict | None:
    """Costruisce una vista completa per una sorgente (query di ricerca o mid topic)."""
    s = provider.fetch_series(source_kw, geo, config.YEARS_HISTORY)
    if not s.ok or len(s.points) < MIN_SERIES_POINTS:
        return None
    r = S.analyze(s.points, config.PUBLISH_LEAD_MONTHS)

    rising_90d = []
    try:
        recent_from = (date.today() - timedelta(days=90)).isoformat()
        rr = provider.fetch_series(source_kw, geo, date_from=recent_from)
        rising_90d = [x["query"] for x in rr.related_rising[:8]]
    except Exception:
        pass

    return {
        "peak": r.peak_month, "rise": r.rise_start_month, "pub": r.publish_month,
        "strength": round(r.strength, 3), "seasonal": r.is_seasonal, "advice": r.advice,
        "n": r.n_points, "profile": [round(x, 1) for x in r.profile],
        "series": [[p[0], round(p[1], 1)] for p in s.points],
        "top": [x["query"] for x in s.related_top[:8]],
        "rising_5y": [x["query"] for x in s.related_rising[:8]],
        "rising_90d": rising_90d,
    }


def analyze_category(provider, name: str, query_term: str, geo: str = "IT") -> dict:
    try:
        cands = resolver.autocomplete(query_term)[:6]
    except Exception:
        cands = []

    choice = llm_selector.choose_source(query_term, name, cands)

    term = _view(provider, query_term, geo)

    # quale Topic scaricare: quello scelto, oppure - se la scelta e' dubbia e va
    # validata da un umano - il miglior concetto disponibile, cosi' il validatore
    # ha le due curve a confronto invece di un solo lato.
    want_alt = choice.mode != "topic" and choice.needs_review and choice.alt_mid
    mid = choice.mid if choice.mode == "topic" else (choice.alt_mid if want_alt else None)
    t_title = choice.title if choice.mode == "topic" else (choice.alt_title if want_alt else None)
    t_type = choice.type if choice.mode == "topic" else (choice.alt_type if want_alt else None)

    topic = _view(provider, mid, geo) if mid else None
    if topic:
        topic.update(mid=mid, title=t_title, ttype=t_type)

    if topic and choice.mode == "topic":
        active = "topic"
        note = choice.reason
    else:
        active = "term"
        if choice.mode == "topic":
            note = (f"(Topic «{choice.title}» senza dati Trends sufficienti → uso la "
                    f"query di ricerca) {choice.reason}")
        elif topic:
            note = f"{choice.reason} Topic «{t_title}» scaricato per il confronto."
        else:
            note = choice.reason

    return {
        "query_term": query_term, "geo": geo, "via": choice.via, "note": note,
        # provenienza: quale endpoint Trends ha prodotto questi numeri e quando
        "data_source": getattr(provider, "source_id", getattr(provider, "name", "?")),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "active_mode": active, "portable_cross_market": active == "topic",
        "confidence": choice.confidence, "needs_review": choice.needs_review,
        "candidates": [{"mid": c.mid, "title": c.title, "type": c.type, "kind": c.kind}
                       for c in cands],
        "term": term, "topic": topic,
    }


def active_view(record: dict) -> dict | None:
    """La vista attualmente selezionata (rispetta un eventuale override)."""
    mode = record.get("active_mode", "term")
    return record.get(mode) or record.get("term")
