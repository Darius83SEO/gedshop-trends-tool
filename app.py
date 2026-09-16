"""Gedshop Trends — tool di stagionalita' editoriale.

Frontend = dashboard HTML/CSS/SVG (dashboard.html) embeddato, alimentato con i
dati reali dallo storage. La sidebar Streamlit tiene stato e comandi (crawl,
preset, analizza, override sorgente). Grafici e stile identici all'anteprima.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import analysis
import config
from crawler import crawl_categories
from providers.dataforseo import DataForSEOProvider
from storage import get_storage

st.set_page_config(page_title="Gedshop Trends", page_icon="📈", layout="wide",
                   initial_sidebar_state="expanded")
# Nota: NON nascondere header e toolbar. Il pulsante che riapre la sidebar
# chiusa (stExpandSidebarButton) e' figlio di stToolbar dentro stHeader:
# nascondendo il contenitore la colonna sinistra sparisce e non si recupera
# piu'. Nascondiamo quindi solo i due elementi che davvero non servono, il
# menu hamburger e il bottone Deploy, lasciando la freccia di riapertura.
st.markdown("""
<style>
footer {visibility: hidden;}
[data-testid="stMainMenu"], [data-testid="stAppDeployButton"] {display: none !important;}
[data-testid="stHeader"] {background: transparent;}
[data-testid="stExpandSidebarButton"] {display: inline-flex !important; visibility: visible !important;}
.block-container {padding-top: 1.2rem; padding-bottom: 0; max-width: 1250px;}
section[data-testid="stSidebar"] {border-right: 1px solid #263849; min-width: 340px;}
/* etichette lunghe (categorie, Topic): vanno a capo invece di essere troncate */
section[data-testid="stSidebar"] [data-testid="stRadio"] label p,
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label p {white-space: normal; overflow-wrap: anywhere;}
</style>
""", unsafe_allow_html=True)


@st.cache_resource(show_spinner=False)
def _storage():
    """Una sola istanza per processo: pool di connessioni e schema creati una volta."""
    return get_storage()


storage = _storage()
GEOS = list(config.GEO_MAP.keys())
DASHBOARD = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")


def provider():
    return DataForSEOProvider(config.DATAFORSEO_LOGIN, config.DATAFORSEO_PASSWORD)


def build_data(cats) -> dict:
    """DATA per il frontend: {nome: record} solo categorie analizzate."""
    return {c["name"]: c["payload"] for c in cats
            if c.get("last_sync") and c.get("payload")}


# ------------------------------------------------------- sincronizzazione
SYNC_EVERY_DAYS = 30


def flash(msg: str, kind: str = "success"):
    """Messaggio che sopravvive al rerun (altrimenti st.success sparisce)."""
    st.session_state["_flash"] = (kind, msg)


def run_analysis(targets, geo, label="Analisi…") -> list[str]:
    """Scarica da DataForSEO e salva. Ritorna la lista dei problemi.

    Le categorie girano in parallelo (analysis.analyze_many); salvataggio e
    barra di avanzamento restano qui, nel thread di Streamlit.
    """
    if not targets:
        return []
    llm = config.llm_conf()  # letto qui: i thread di lavoro non vedono session_state
    prog = st.progress(0.0, f"{label} 0/{len(targets)}")
    errs = []
    for i, (cat, rec, err) in enumerate(
            analysis.analyze_many(provider(), targets, geo, llm), start=1):
        if err is not None:
            errs.append(f"{cat['name']}: {err}")
        elif rec.get("term") or rec.get("topic"):
            storage.save_record(cat["id"], rec)
        else:
            errs.append(f"{cat['name']}: Google Trends non ha dati sufficienti "
                        f"per «{cat['query_term']}»")
        prog.progress(i / len(targets), f"{label} {i}/{len(targets)} · {cat['name']} fatto")
    prog.empty()
    return errs


def _as_dt(value):
    """last_sync: datetime da Postgres, stringa ISO da JSON."""
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def sync_state(cats) -> dict:
    """Freschezza del dataset: ultimo aggiornamento, quante mancano, se e' scaduto."""
    stamps = [d for d in (_as_dt(c.get("last_sync")) for c in cats) if d]
    last = max(stamps) if stamps else None
    oldest = min(stamps) if stamps else None
    days = (datetime.now(timezone.utc) - oldest).days if oldest else None
    return {"last": last, "oldest": oldest, "days": days,
            "done": len(stamps), "missing": len(cats) - len(stamps),
            "stale": bool(days is not None and days >= SYNC_EVERY_DAYS)}


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("### 📈 Gedshop Trends")
    st.caption("Quando partono le ricerche → quando pubblicare")

    _fl = st.session_state.pop("_flash", None)
    if _fl:
        {"success": st.success, "warning": st.warning,
         "error": st.error, "info": st.info}[_fl[0]](_fl[1])

    geo = st.selectbox("Mercato", GEOS,
                       index=GEOS.index(config.DEFAULT_GEO) if config.DEFAULT_GEO in GEOS else 0)
    site_url = st.text_input("Sito", value="gedshop.it")

    st.divider()

    # --- scelta del modello AI ---
    _providers = list(config.LLM_PROVIDERS.keys())

    def _prov_option(key: str) -> str:
        c = config.LLM_PROVIDERS[key]
        return f"{'🟢' if c['key'] else '⚪'} {c['label']}"

    with st.popover(f"🤖 AI: {config.llm_label()}", use_container_width=True,
                    help="Quale LLM legge i candidati di Google Trends e sceglie la "
                         "sorgente (Topic o query di ricerca) per ogni categoria. "
                         "Vale dalla prossima analisi: le categorie già analizzate "
                         "restano come sono finché non le rianalizzi."):
        prov = st.radio("Provider", _providers, key="llm_provider",
                        index=_providers.index(config.DEFAULT_LLM_PROVIDER),
                        format_func=_prov_option, horizontal=True)
        _pc = config.LLM_PROVIDERS[prov]
        _mkey = f"llm_model_{prov}"
        if st.session_state.get(_mkey) not in _pc["models"]:
            st.session_state[_mkey] = _pc["default"]

        def _model_option(m, newest=_pc["models"][0], dflt=_pc["default"]):
            tags = (["più recente"] if m == newest else []) + (["predefinito"] if m == dflt else [])
            return m + (f"  · {', '.join(tags)}" if tags else "")

        st.selectbox("Modello", _pc["models"], key=_mkey, format_func=_model_option,
                     help="Il primo della lista è il più recente. Per scegliere la "
                          "sorgente basta anche un modello economico: i più nuovi "
                          "costano di più e rispondono più lentamente.")
        _cur = config.llm_conf()
        if _cur["key"]:
            st.caption(f"Attivo: **{config.llm_label(_cur)}**")
        else:
            st.warning(f"Manca `{_cur['secret']}` nei secrets: senza key si usano "
                       f"le regole euristiche.")
            st.caption(f"Richiede anche `pip install {_cur['pkg']}`.")

    st.caption(
        ("🟢 " if config.has_provider_creds() else "🔴 ") + "DataForSEO   "
        + ("🟢 " if config.has_llm() else "🟡 ") + f"AI {config.llm_label() if config.has_llm() else '(regole)'}   "
        + ("🟢 Neon" if storage.kind == "postgres" else "💾 JSON"))

    st.divider()

    # ---------------------------------------------- dati DataForSEO (in evidenza)
    # UNA sola lettura dal DB per rerun: tutto il resto della pagina usa `cats`
    cats = storage.list_categories(site_url, geo)
    pending = [c for c in cats if not c.get("last_sync")]
    sync = sync_state(cats)
    no_creds = not config.has_provider_creds()

    st.markdown("#### 🔄 Dati Google Trends")
    if not cats:
        st.caption("Nessuna categoria: caricale con **Preset** o **Crawl** qui sotto.")
    elif sync["last"]:
        st.caption(f"Ultimo aggiornamento: **{sync['last'].astimezone().strftime('%d/%m/%Y')}** · "
                   f"{sync['done']} categorie aggiornate"
                   + (f" · {sync['missing']} mai analizzate" if sync["missing"] else ""))
    else:
        st.caption(f"{len(cats)} categorie caricate, **nessuna ancora analizzata**.")

    if no_creds:
        st.error("Credenziali DataForSEO mancanti nei secrets: la sincronizzazione è disattivata.")
    elif sync["stale"]:
        st.warning(f"Dati vecchi di {sync['days']} giorni: conviene aggiornare "
                   f"volumi e stagionalità.", icon="⏰")

    s1, s2 = st.columns(2)
    run_all = s1.button("⬇️ Aggiorna tutto", use_container_width=True,
                        type="primary", disabled=no_creds or not cats,
                        help="Riscarica da DataForSEO tutte le categorie di questo mercato "
                             "e ricalcola stagionalità e calendario editoriale.")
    run_new = s2.button(f"⬇️ Mancanti ({len(pending)})", use_container_width=True,
                        disabled=no_creds or not pending,
                        help="Scarica solo le categorie mai analizzate. Consuma meno crediti.")
    target = cats if run_all else (pending if run_new else None)
    if target:
        errs = run_analysis(target, geo, "Aggiornamento da DataForSEO…")
        if errs:
            flash("Aggiornate con problemi su: " + "; ".join(errs), "warning")
        else:
            flash(f"{len(target)} categorie aggiornate.")
        st.rerun()

    auto = str(storage.get_setting("auto_sync_monthly", "0")) == "1"
    new_auto = st.toggle(
        "Aggiornamento automatico mensile", value=auto, disabled=no_creds,
        help=f"Quando i dati superano i {SYNC_EVERY_DAYS} giorni, il primo che apre "
             f"il tool fa ripartire da solo l'aggiornamento di tutte le categorie. "
             f"Serve che qualcuno apra la dashboard: per un aggiornamento davvero "
             f"automatico anche a tool chiuso usa sync_monthly.py con un cron.")
    if new_auto != auto:
        storage.set_setting("auto_sync_monthly", "1" if new_auto else "0")
        st.rerun()

    if (new_auto and cats and sync["stale"] and not no_creds
            and not st.session_state.get("_auto_sync_done")):
        st.session_state["_auto_sync_done"] = True
        errs = run_analysis(cats, geo, "Aggiornamento mensile automatico…")
        flash(f"Aggiornamento mensile automatico eseguito su {len(cats)} categorie."
              + (" Problemi su: " + "; ".join(errs) if errs else ""),
              "warning" if errs else "success")
        st.rerun()

    st.divider()

    # ---------------------------------------------- nuova categoria + sync mirata
    with st.expander("➕ Aggiungi categoria", expanded=False):
        st.caption("Appena salvata parte la sincronizzazione con DataForSEO **solo per "
                   "questa categoria**; badge, tabella e calendario editoriale si "
                   "aggiornano da soli.")
        with st.form("add_cat", clear_on_submit=True):
            nc_name = st.text_input("Nome categoria", placeholder="es. Borracce termiche",
                                    max_chars=80)
            nc_term = st.text_input("Parola da cercare su Google Trends",
                                    placeholder="vuoto = usa il nome della categoria",
                                    max_chars=80)
            nc_url = st.text_input("URL della categoria (facoltativo)",
                                   placeholder="https://www.gedshop.it/…")
            add = st.form_submit_button("➕ Aggiungi e sincronizza",
                                        use_container_width=True, type="primary",
                                        disabled=no_creds)
        if add:
            name = " ".join((nc_name or "").split())
            term = " ".join((nc_term or "").split()) or name.lower()
            if not name:
                st.error("Serve almeno il nome della categoria.")
            elif any(c["name"].strip().lower() == name.lower() for c in cats):
                st.error(f"«{name}» esiste già su {site_url} ({geo}).")
            else:
                cid = storage.upsert_category(site_url, name, term, geo,
                                              url=(nc_url or "").strip() or None)
                errs = run_analysis([{"id": cid, "name": name, "query_term": term}],
                                    geo, f"Sincronizzo «{name}»…")
                if errs:
                    flash(f"«{name}» salvata ma non analizzata ({errs[0].split(': ', 1)[-1]}). "
                          f"Resta tra le «Mancanti»: prova un termine più generico "
                          f"o riprova più tardi.", "warning")
                else:
                    st.session_state["_focus"] = name
                    flash(f"«{name}» aggiunta e sincronizzata: calendario aggiornato.")
                st.rerun()

    with st.expander("⚙️ Amministrazione", expanded=False):
        st.caption(f"Categorie su {site_url} ({geo}): **{len(cats)}** · "
                   f"da analizzare: **{len(pending)}**")
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
            flash(f"Caricate {len(GEDSHOP_CATEGORIES)} categorie: ora usa «Aggiorna tutto».")
            st.rerun()

        cands = st.session_state.get("cands", [])
        if cands:
            known = {c["name"].strip().lower() for c in cats}
            with st.form("crawl_pick"):
                st.caption(f"**{len(cands)} categorie trovate**: togli la spunta a "
                           f"quelle da scartare.")
                keep = []
                for i, c in enumerate(cands):
                    dup = c["name"].strip().lower() in known
                    if st.checkbox(c["name"] + ("  (già presente)" if dup else ""),
                                   value=not dup, key=f"crawl_{i}", help=c.get("url")):
                        keep.append(c)
                save = st.form_submit_button("💾 Salva selezionate", use_container_width=True)
            if save:
                for c in keep:
                    storage.upsert_category(site_url, c["name"], c["name"].lower(), geo,
                                            url=c.get("url"))
                st.session_state.pop("cands", None)
                flash(f"Salvate {len(keep)} categorie: ora usa «Mancanti».")
                st.rerun()

    # --- validatore umano (solo casi ambigui) ---
    done = [c for c in cats if c.get("last_sync") and c.get("payload")]
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

    # --- override sorgente (qualsiasi categoria) ---
    if done:
        with st.expander("🧭 Cambia sorgente (override)", expanded=False):
            names = {c["name"]: c for c in done}
            selc = st.radio("Categoria", list(names.keys()), key="ov_cat")
            cat = names[selc]; rec = cat["payload"]; has_topic = bool(rec.get("topic"))
            opts = ["term"] + (["topic"] if has_topic else [])
            lbl = {"term": f"🔤 Query di ricerca «{rec['query_term']}»",
                   "topic": f"🎯 Topic «{rec['topic']['title']}»" if has_topic else ""}
            cur = rec.get("active_mode", "term")
            new = st.radio("Sorgente attiva", opts, index=opts.index(cur) if cur in opts else 0,
                           format_func=lambda x: lbl[x], key=f"ov_mode_{cat['id']}")
            if new != cur:
                storage.set_active_mode(cat["id"], new); st.rerun()
            cnds = [x for x in rec.get("candidates", []) if x.get("title") and x.get("mid")]
            if cnds:
                cur_mid = (rec.get("topic") or {}).get("mid")
                idx = st.radio(
                    "Cambia Topic (ricalcola)", range(len(cnds)),
                    index=next((i for i, x in enumerate(cnds) if x["mid"] == cur_mid), 0),
                    format_func=lambda i: f"{cnds[i]['title']} — {cnds[i]['type'] or 'senza tipo'}"
                                          + ("  ✓ in uso" if cnds[i]["mid"] == cur_mid else ""),
                    key=f"ov_topic_{cat['id']}")
                if st.button("🔄 Usa questo Topic",
                             disabled=no_creds or cnds[idx]["mid"] == cur_mid):
                    ch = cnds[idx]
                    with st.spinner(f"Scarico «{ch['title']}»…"):
                        v = analysis._view(provider(), ch["mid"], geo)
                    if v:
                        v.update(mid=ch["mid"], title=ch["title"], ttype=ch["type"])
                        rec["topic"] = v; rec["active_mode"] = "topic"
                        rec["portable_cross_market"] = True
                        rec["note"] = f"Topic «{ch['title']}» scelto manualmente."
                        storage.save_record(cat["id"], rec)
                        st.session_state["_focus"] = cat["name"]
                        st.rerun()
                    else:
                        st.warning("Nessun dato Trends per questo Topic.")


# ------------------------------------------------------------------ main
data = build_data(cats)
# __FOCUS__: categoria da aprire subito (es. appena aggiunta), in JSON.
# __DATA__ per ultimo: i segnaposto non vanno cercati dentro il JSON dei dati.
focus = st.session_state.pop("_focus", None)
html = (DASHBOARD.replace("__GEO__", geo)
                 .replace("__AI__", config.llm_label() if config.has_llm() else "regole euristiche")
                 .replace("__FOCUS__", json.dumps(focus if focus in data else None, ensure_ascii=False))
                 .replace("__DATA__", json.dumps(data, ensure_ascii=False)))
components.html(html, height=1500, scrolling=True)
