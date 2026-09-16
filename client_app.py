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
from storage import get_storage

st.set_page_config(page_title="Gedshop Trends", page_icon="📈", layout="wide",
                   initial_sidebar_state="expanded")
# Nota: NON nascondere header e toolbar. Il pulsante che riapre la sidebar
# chiusa (stExpandSidebarButton) e' figlio di stToolbar dentro stHeader:
# nascondendo il contenitore la colonna sinistra sparisce e non si recupera
# piu'. Nascondiamo solo hamburger e bottone Deploy.
st.markdown("""
<style>
footer {visibility: hidden;}
[data-testid="stMainMenu"], [data-testid="stAppDeployButton"] {display: none !important;}
[data-testid="stHeader"] {background: transparent;}
[data-testid="stExpandSidebarButton"] {display: inline-flex !important; visibility: visible !important;}
.block-container {padding-top: 1.2rem; padding-bottom: 0; max-width: 1250px;}
section[data-testid="stSidebar"] {border-right: 1px solid #263849; min-width: 320px;}
/* etichette lunghe (categorie, Topic): vanno a capo invece di essere troncate */
section[data-testid="stSidebar"] [data-testid="stRadio"] label p {white-space: normal; overflow-wrap: anywhere;}
</style>
""", unsafe_allow_html=True)

# categoria bloccata: il cliente non puo' crawlare altri siti
SITE_URL = config._get("CLIENT_SITE", "gedshop.it")
GEO = config.DEFAULT_GEO
DASHBOARD = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")

@st.cache_resource(show_spinner=False)
def _storage():
    """Una sola istanza per processo: pool di connessioni e schema creati una volta."""
    return get_storage()


try:
    storage = _storage()
except Exception as e:  # DB irraggiungibile: messaggio chiaro, non schermata di errore
    st.error("Non riesco a collegarmi al database dei trend. Riprova tra un minuto; "
             "se il problema resta, avvisa l'amministratore.")
    st.caption(f"Dettaglio tecnico: {type(e).__name__}: {e}")
    st.stop()


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


# una sola lettura dal DB per rerun
cats = storage.list_categories(SITE_URL, GEO)
done = [c for c in cats if c.get("last_sync") and c.get("payload")]


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("### 📈 Gedshop Trends")
    st.caption("Quando partono le ricerche → quando pubblicare")
    st.write(f"**Sito:** {SITE_URL}  ·  **Mercato:** {GEO}")
    st.divider()

    review = [c for c in done if c["payload"].get("needs_review")]

    with st.expander(f"⚠️ Da validare ({len(review)})", expanded=bool(review)):
        st.caption(
            "**Cosa validi:** non i numeri (Google Trends è quello), ma **quale curva** "
            "stiamo guardando. Ogni parola si può misurare come *query di ricerca* "
            "(letterale, tutti i significati: «penne» include la pasta) o come *Topic* "
            "(il concetto, sinonimi e lingue incluse). Qui finiscono solo i casi ambigui: "
            "confermi che il concetto scelto è davvero il prodotto. Non ricalcola nulla, "
            "decide solo quale vista alimenta badge, calendario e consigli. Reversibile.")
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
                            format_func=lambda x: lbl[x], key=f"val_{cat['id']}")
            if st.button("✓ Valida", key=f"valbtn_{cat['id']}"):
                if pick != cur:
                    rec["active_mode"] = pick
                    rec["portable_cross_market"] = pick == "topic"
                rec["needs_review"] = False
                storage.save_record(cat["id"], rec, synced=False); st.rerun()
            st.divider()

    if done:
        with st.expander("✏️ Cambia sorgente", expanded=False):
            names = {c["name"]: c for c in done}
            selc = st.radio("Categoria", list(names.keys()), key="ov_cat")
            cat = names[selc]; rec = cat["payload"]; has_topic = bool(rec.get("topic"))
            opts = ["term"] + (["topic"] if has_topic else [])
            lbl = {"term": f"🔤 Query di ricerca «{rec['query_term']}»",
                   "topic": f"🎯 Topic «{rec['topic']['title']}»" if has_topic else "🎯 Topic non disponibile"}
            cur = rec.get("active_mode", "term")
            new = st.radio("Sorgente attiva", opts, index=opts.index(cur) if cur in opts else 0,
                           format_func=lambda x: lbl[x], key=f"ov_mode_{cat['id']}")
            if new != cur:
                rec["active_mode"] = new
                rec["portable_cross_market"] = new == "topic"
                storage.save_record(cat["id"], rec, synced=False); st.rerun()
            st.caption("Le modifiche vengono salvate e restano condivise.")


# ------------------------------------------------------------------ main
data = {c["name"]: c["payload"] for c in done}
if not data:
    st.info("Nessun dato disponibile. Contatta l'amministratore per l'analisi iniziale.")
else:
    # __AI__: nella vista cliente resta generico. La chiave LLM qui non c'e'
    # (l'analisi gira sulla app admin), quindi il nome del modello non sarebbe
    # quello che ha davvero scelto le sorgenti gia' salvate.
    # __DATA__ per ultimo: i segnaposto non vanno cercati dentro il JSON.
    html = (DASHBOARD.replace("__GEO__", GEO)
                     .replace("__AI__", "AI")
                     .replace("__FOCUS__", "null")
                     .replace("__DATA__", json.dumps(data, ensure_ascii=False)))
    components.html(html, height=1500, scrolling=True)
