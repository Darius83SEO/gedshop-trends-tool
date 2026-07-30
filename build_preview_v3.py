import json, time
from datetime import date, timedelta
import config, seasonality as S, resolver, llm_selector
from providers.dataforseo import DataForSEOProvider
from gedshop_seed import GEDSHOP_CATEGORIES

p = DataForSEOProvider(config.DATAFORSEO_LOGIN, config.DATAFORSEO_PASSWORD)
recent_from = (date.today() - timedelta(days=90)).isoformat()

def build_view(source_kw):
    """source_kw = search term o mid. Ritorna view completa o None."""
    s = p.fetch_series(source_kw, "IT", 5)
    if not s.ok:
        return None
    r = S.analyze(s.points, config.PUBLISH_LEAD_MONTHS)
    # rising recenti (90gg) sulla STESSA sorgente
    rising_recent = []
    try:
        rr = p.fetch_series(source_kw, "IT", date_from=recent_from)
        rising_recent = [x["query"] for x in rr.related_rising[:6]]
    except Exception:
        pass
    return {
        "peak": r.peak_month, "rise": r.rise_start_month, "pub": r.publish_month,
        "strength": round(r.strength, 3), "seasonal": r.is_seasonal, "advice": r.advice,
        "profile": [round(x, 1) for x in r.profile],
        "series": [[pt[0], round(pt[1], 1)] for pt in s.points],
        "top": [x["query"] for x in s.related_top[:6]],
        "rising": rising_recent or [x["query"] for x in s.related_rising[:6]],
    }

out = {}
for cat in GEDSHOP_CATEGORIES:
    name, q = cat["name"], cat["query_term"]
    cands = resolver.autocomplete(q)
    ch = llm_selector.choose_source(q, name, cands)
    rec = {"query_term": q, "note": ch.reason, "via": ch.via,
           "candidates": [{"mid": c.mid, "title": c.title, "type": c.type, "kind": c.kind} for c in cands[:5]],
           "term": None, "topic": None, "active_mode": "term"}
    # term view (sempre, per confronto/override)
    rec["term"] = build_view(q)
    # topic view (se LLM ha scelto un topic)
    if ch.mode == "topic" and ch.mid:
        tv = build_view(ch.mid)
        if tv:
            tv["mid"] = ch.mid; tv["title"] = ch.title; tv["ttype"] = ch.type
            rec["topic"] = tv
            rec["active_mode"] = "topic"
        else:
            rec["note"] = f"(Topic «{ch.title}» senza dati Trends → uso il search term) {ch.reason}"
    out[name] = rec
    am = rec["active_mode"]
    print(f'{name:24} {am:5} via={ch.via:9} term={"ok" if rec["term"] else "-"} topic={"ok" if rec["topic"] else "-"}')
    time.sleep(0.2)

json.dump(out, open("data/preview_data_v3.json", "w", encoding="utf-8"), ensure_ascii=False)
print("SALVATO data/preview_data_v3.json")
