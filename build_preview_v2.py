import json, time
from datetime import date, timedelta
import config, seasonality as S, resolver
from providers.dataforseo import DataForSEOProvider
from gedshop_seed import GEDSHOP_CATEGORIES, SITE_URL

p = DataForSEOProvider(config.DATAFORSEO_LOGIN, config.DATAFORSEO_PASSWORD)
recent_from = (date.today() - timedelta(days=90)).isoformat()

def view_from_series(s):
    r = S.analyze(s.points, config.PUBLISH_LEAD_MONTHS)
    return {
        "peak": r.peak_month, "rise": r.rise_start_month, "pub": r.publish_month,
        "strength": round(r.strength, 3), "seasonal": r.is_seasonal, "advice": r.advice,
        "profile": [round(x, 1) for x in r.profile],
        "series": [[pt[0], round(pt[1], 1)] for pt in s.points],
        "top": [q["query"] for q in s.related_top[:6]],
        "rising": [q["query"] for q in s.related_rising[:6]],
    }

out = {}
for cat in GEDSHOP_CATEGORIES:
    name, q = cat["name"], cat["query_term"]
    rec = {"query_term": q, "candidates": [], "note": "", "mode": "term", "state": "auto", "term": None, "topic": None, "recent_rising": []}
    dec = resolver.resolve(q)
    rec["note"] = dec.note; rec["mode"] = dec.mode; rec["state"] = dec.state
    rec["candidates"] = [{"mid": c.mid, "title": c.title, "type": c.type, "kind": c.kind} for c in dec.candidates[:4]]
    # term (sempre)
    ts = p.fetch_series(q, "IT", 5)
    if ts.ok: rec["term"] = view_from_series(ts)
    # topic (se proposto)
    if dec.topic and dec.topic.mid:
        tp = p.fetch_series(dec.topic.mid, "IT", 5)
        if tp.ok:
            rec["topic"] = view_from_series(tp)
            rec["topic"]["mid"] = dec.topic.mid; rec["topic"]["title"] = dec.topic.title; rec["topic"]["ttype"] = dec.topic.type
    # rising recenti (ultimi 90 gg) sul termine attivo
    try:
        rr = p.fetch_series(q, "IT", date_from=recent_from)
        rec["recent_rising"] = [x["query"] for x in rr.related_rising[:6]]
    except Exception:
        pass
    out[name] = rec
    print(f"{name:22} mode={dec.mode:5} state={dec.state:6} term={'ok' if rec['term'] else '-'} topic={'ok' if rec['topic'] else '-'} recent={len(rec['recent_rising'])}")
    time.sleep(0.3)

json.dump(out, open("data/preview_data_v2.json", "w", encoding="utf-8"), ensure_ascii=False)
print("SALVATO data/preview_data_v2.json")
