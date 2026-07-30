"""Gedshop Trends — VISTA CLIENTE (sola consultazione + validazione).

Versione da condividere via URL: bloccata sul set Gedshop gia' analizzato,
NIENTE crawl / analisi / chiamate API. Il cliente puo' solo cambiare la sorgente
(Search term <-> Topic) e validare; la scelta viene salvata su DB (Neon).

Deploy: Streamlit Cloud con secret DATABASE_URL (Neon) + opz. CLIENT_PASSWORD.
Non richiede DataForSEO/OpenAI.
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import config
import seasonality as S  # noqa: F401  (month names usati indirettamente lato UI)
from storage import get_storage

st.set_page_config(page_title="Gedshop Trends", page_icon="📈", layout="wide")
st.markdown("""
<style>
#MainMenu, footer, header {visibility: hidden;}
.block-container {padding-top: 1.2rem; padding-bottom: 0; max-width: 1250px;}
section[data-testid="stSidebar"] {border-right: 1px solid #263849;}
</style>
""", unsafe_allow_html=True)

# categoria bloccata: il cliente non puo' crawlare altri siti
SITE_URL = config._get("CLIENT_SITE", "gedshop.it")
GEO = config.DEFAULT_GEO
DASHBOARD = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")
storage = get_storage()


def check_password() -> bool:
    pw = ""
    try:
        pw = st.secrets.get("CLIENT_PASSWORD", "")
    except Exception:
        pw = config._get("CLIENT_PASSWORD", "")
    if not pw:
        return True  # nessuna password impostata -> accesso libero
    if st.session_state.get("auth_ok"):
        return True
    st.markdown("### 📈 Gedshop Trends")
    with st.form("login"):
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Entra"):
            if p == pw:
                st.session_state["auth_ok"] = True
                st.rerun()
            else:
                st.error("Password errata.")
    return False


if not check_password():
    st.stop()


def build_data():
    out = {}
    for cat in storage.list_categories(SITE_URL, GEO):
        if cat.get("last_sync") and cat.get("payload"):
            out[cat["name"]] = cat["payload"]
    return out


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("### 📈 Gedshop Trends")
    st.caption("Quando partono le ricerche → quando pubblicare")
    st.write(f"**Sito:** {SITE_URL}  ·  **Mercato:** {GEO}")
    st.divider()

    done = [c for c in storage.list_categories(SITE_URL, GEO) if c.get("last_sync")]
    review = [c for c in done if (c.get("payload") or {}).get("needs_review")]

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

    if done:
        with st.expander("✏️ Cambia sorgente", expanded=False):
            names = {c["name"]: c for c in done}
            selc = st.selectbox("Categoria", list(names.keys()))
            cat = names[selc]; rec = cat["payload"]; has_topic = bool(rec.get("topic"))
            opts = ["term"] + (["topic"] if has_topic else [])
            lbl = {"term": f"🔤 Search term «{rec['query_term']}»",
                   "topic": f"🎯 Topic «{rec['topic']['title']}»" if has_topic else "🎯 Topic non disponibile"}
            cur = rec.get("active_mode", "term")
            new = st.radio("Sorgente attiva", opts, index=opts.index(cur) if cur in opts else 0,
                           format_func=lambda x: lbl[x])
            if new != cur:
                rec["active_mode"] = new
                rec["portable_cross_market"] = new == "topic"
                storage.save_record(cat["id"], rec); st.rerun()
            st.caption("Le modifiche vengono salvate e restano condivise.")


# ------------------------------------------------------------------ main
data = build_data()
if not data:
    st.info("Nessun dato disponibile. Contatta l'amministratore per l'analisi iniziale.")
else:
    html = DASHBOARD.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    components.html(html, height=1500, scrolling=True)
