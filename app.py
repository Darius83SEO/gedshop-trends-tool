"""Gedshop Trends — tool di stagionalita' editoriale.

Frontend = dashboard HTML/CSS/SVG (dashboard.html) embeddato, alimentato con i
dati reali dallo storage. La sidebar Streamlit tiene stato e comandi (crawl,
preset, analizza, override sorgente). Grafici e stile identici all'anteprima.
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import analysis
import config
import seasonality as S
from crawler import crawl_categories
from providers.dataforseo import DataForSEOProvider
from storage import get_storage

st.set_page_config(page_title="Gedshop Trends", page_icon="📈", layout="wide")
st.markdown("""
<style>
#MainMenu, footer, header {visibility: hidden;}
.block-container {padding-top: 1.2rem; padding-bottom: 0; max-width: 1250px;}
section[data-testid="stSidebar"] {border-right: 1px solid #263849;}
</style>
""", unsafe_allow_html=True)

storage = get_storage()
GEOS = list(config.GEO_MAP.keys())
DASHBOARD = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")


def provider():
    return DataForSEOProvider(config.DATAFORSEO_LOGIN, config.DATAFORSEO_PASSWORD)


def build_data(site_url, geo) -> dict:
    """DATA per il frontend: {nome: record} solo categorie analizzate."""
    out = {}
    for cat in storage.list_categories(site_url, geo):
        if cat.get("last_sync") and cat.get("payload"):
            out[cat["name"]] = cat["payload"]
    return out


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("### 📈 Gedshop Trends")
    st.caption("Quando partono le ricerche → quando pubblicare")
    geo = st.selectbox("Mercato", GEOS,
                       index=GEOS.index(config.DEFAULT_GEO) if config.DEFAULT_GEO in GEOS else 0)
    site_url = st.text_input("Sito", value="gedshop.it")

    st.divider()
    st.caption(
        ("🟢 " if config.has_provider_creds() else "🔴 ") + "DataForSEO   "
        + ("🟢 " if config.has_llm() else "🟡 ") + f"AI {config.OPENAI_MODEL if config.has_llm() else '(regole)'}   "
        + ("🟢 Neon" if storage.kind == "postgres" else "💾 JSON"))

    st.divider()
    with st.expander("⚙️ Amministrazione", expanded=False):
        a1, a2 = st.columns(2)
        if a1.button("🔍 Crawl", use_container_width=True):
            try:
                with st.spinner("Analizzo il menu…"):
                    st.session_state["cands"] = crawl_categories(site_url)
            except Exception as e:
                st.error(f"Crawl fallito: {e}")
        if a2.button("⚡ Preset", use_container_width=True):
            from gedshop_seed import GEDSHOP_CATEGORIES, SITE_URL
            for c in GEDSHOP_CATEGORIES:
                storage.upsert_category(SITE_URL, c["name"], c["query_term"], geo, url=c.get("url"))
            st.success(f"Caricate {len(GEDSHOP_CATEGORIES)} categorie."); st.rerun()

        cands = st.session_state.get("cands", [])
        if cands:
            picked = st.multiselect("Categorie trovate", [c["name"] for c in cands],
                                    default=[c["name"] for c in cands])
            if st.button("💾 Salva selezionate"):
                for c in cands:
                    if c["name"] in picked:
                        storage.upsert_category(site_url, c["name"], c["name"], geo, url=c.get("url"))
                st.session_state.pop("cands", None); st.success("Salvate."); st.rerun()

        cats = storage.list_categories(site_url, geo)
        pending = [c for c in cats if not c.get("last_sync")]
        st.write(f"Categorie: **{len(cats)}** · da analizzare: **{len(pending)}**")
        b1, b2 = st.columns(2)
        run_all = b1.button("⬇️ Analizza tutto", use_container_width=True, disabled=not config.has_provider_creds())
        run_new = b2.button("⬇️ Mancanti", use_container_width=True, disabled=not config.has_provider_creds())
        target = cats if run_all else (pending if run_new else None)
        if target:
            prov = provider(); prog = st.progress(0.0, "Analisi…"); errs = []
            for i, cat in enumerate(target):
                try:
                    rec = analysis.analyze_category(prov, cat["name"], cat["query_term"], geo)
                    if rec.get("term") or rec.get("topic"):
                        storage.save_record(cat["id"], rec)
                    else:
                        errs.append(cat["name"])
                except Exception as e:
                    errs.append(f"{cat['name']}: {e}")
                prog.progress((i + 1) / len(target), f"{cat['name']} ({i+1}/{len(target)})")
            if errs: st.warning("Problemi: " + ", ".join(errs))
            st.success("Analisi completata."); st.rerun()

    # --- validatore umano (solo casi ambigui) ---
    done_all = [c for c in storage.list_categories(site_url, geo) if c.get("last_sync")]
    review = [c for c in done_all if (c.get("payload") or {}).get("needs_review")]
    with st.expander(f"⚠️ Da validare ({len(review)})", expanded=bool(review)):
        if not review:
            st.caption("Nessuna sorgente ambigua da validare. 👍")
        for cat in review:
            rec = cat["payload"]; has_topic = bool(rec.get("topic"))
            st.markdown(f"**{cat['name']}** · confidenza {rec.get('confidence', '?')}")
            st.caption(rec.get("note", ""))
            opts = ["term"] + (["topic"] if has_topic else [])
            lbl = {"term": f"🔤 «{rec['query_term']}»",
                   "topic": f"🎯 «{rec['topic']['title']}»" if has_topic else ""}
            cur = rec.get("active_mode", "term")
            pick = st.radio("Sorgente", opts, index=opts.index(cur) if cur in opts else 0,
                            format_func=lambda x: lbl[x], key=f"val_{cat['id']}", horizontal=True)
            if st.button("✓ Valida", key=f"valbtn_{cat['id']}"):
                if pick != cur:
                    rec["active_mode"] = pick
                    rec["portable_cross_market"] = pick == "topic"
                rec["needs_review"] = False
                storage.save_record(cat["id"], rec); st.rerun()
            st.divider()

    # --- override sorgente (qualsiasi categoria) ---
    done = [c for c in storage.list_categories(site_url, geo) if c.get("last_sync")]
    if done:
        with st.expander("🧭 Cambia sorgente (override)", expanded=False):
            names = {c["name"]: c for c in done}
            selc = st.selectbox("Categoria", list(names.keys()))
            cat = names[selc]; rec = cat["payload"]; has_topic = bool(rec.get("topic"))
            opts = ["term"] + (["topic"] if has_topic else [])
            lbl = {"term": f"🔤 «{rec['query_term']}»",
                   "topic": f"🎯 «{rec['topic']['title']}»" if has_topic else ""}
            cur = rec.get("active_mode", "term")
            new = st.radio("Sorgente attiva", opts, index=opts.index(cur) if cur in opts else 0,
                           format_func=lambda x: lbl[x])
            if new != cur:
                storage.set_active_mode(cat["id"], new); st.rerun()
            cnds = [x for x in rec.get("candidates", []) if x.get("title") and x.get("mid")]
            if cnds:
                labs = [f"{x['title']} [{x['type']}]" for x in cnds]
                idx = st.selectbox("Cambia Topic (ricalcola)", range(len(cnds)), format_func=lambda i: labs[i])
                if st.button("🔄 Usa questo Topic", disabled=not config.has_provider_creds()):
                    ch = cnds[idx]
                    with st.spinner(f"Scarico «{ch['title']}»…"):
                        v = analysis._view(provider(), ch["mid"], geo)
                    if v:
                        v.update(mid=ch["mid"], title=ch["title"], ttype=ch["type"])
                        rec["topic"] = v; rec["active_mode"] = "topic"
                        rec["note"] = f"Topic «{ch['title']}» scelto manualmente."
                        storage.save_record(cat["id"], rec); st.rerun()
                    else:
                        st.warning("Nessun dato Trends per questo Topic.")


# ------------------------------------------------------------------ main
data = build_data(site_url, geo)
html = DASHBOARD.replace("__DATA__", json.dumps(data, ensure_ascii=False))
components.html(html, height=1500, scrolling=True)
