"""Configurazione centralizzata: legge da st.secrets o da variabili d'ambiente."""
from __future__ import annotations

import os

try:
    import streamlit as st
    _SECRETS = dict(st.secrets) if hasattr(st, "secrets") else {}
except Exception:  # streamlit non disponibile (es. script CLI)
    _SECRETS = {}


def _get(key: str, default: str = "") -> str:
    val = _SECRETS.get(key)
    if val:
        return str(val)
    return os.environ.get(key, default)


# --- Provider dati ---
DATAFORSEO_LOGIN = _get("DATAFORSEO_LOGIN")
DATAFORSEO_PASSWORD = _get("DATAFORSEO_PASSWORD")

# --- LLM (selezione automatica sorgente Topic / query di ricerca) ---
# Per ogni provider: `models` = modelli selezionabili in sidebar, il PIU' RECENTE
# per primo. Il modello di default resta quello dei secrets (es. OPENAI_MODEL),
# cosi' un aggiornamento del codice non cambia da solo costi e risultati.
OPENAI_API_KEY = _get("OPENAI_API_KEY")
OPENAI_MODEL = _get("OPENAI_MODEL", "gpt-4.1")

GEMINI_API_KEY = _get("GEMINI_API_KEY") or _get("GOOGLE_API_KEY")
GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-2.5-flash")

ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _get("ANTHROPIC_MODEL", "claude-sonnet-5")

XAI_API_KEY = _get("XAI_API_KEY") or _get("GROK_API_KEY")
XAI_MODEL = _get("XAI_MODEL", "grok-4.6")


def _models(default: str, *known: str) -> list[str]:
    """Elenco modelli senza doppioni; quello dei secrets resta comunque scelto."""
    out = list(dict.fromkeys(known))
    if default and default not in out:
        out.append(default)
    return out


# `pkg` = pacchetto pip da installare, mostrato nella UI quando manca.
# Grok usa l'API compatibile OpenAI (stesso pacchetto `openai`, base_url x.ai).
LLM_PROVIDERS = {
    "openai": {"label": "ChatGPT", "default": OPENAI_MODEL,
               "models": _models(OPENAI_MODEL, "gpt-6-astra", "gpt-5.6-sol",
                                 "gpt-5.6-luna", "gpt-4.1"),
               "key": OPENAI_API_KEY, "secret": "OPENAI_API_KEY", "pkg": "openai"},
    "gemini": {"label": "Gemini", "default": GEMINI_MODEL,
               "models": _models(GEMINI_MODEL, "gemini-3.8-flash", "gemini-2.5-flash"),
               "key": GEMINI_API_KEY, "secret": "GEMINI_API_KEY", "pkg": "google-genai"},
    "anthropic": {"label": "Claude", "default": ANTHROPIC_MODEL,
                  "models": _models(ANTHROPIC_MODEL, "claude-fable-5-1", "claude-opus-5",
                                    "claude-sonnet-5"),
                  "key": ANTHROPIC_API_KEY, "secret": "ANTHROPIC_API_KEY", "pkg": "anthropic"},
    "xai": {"label": "Grok", "default": XAI_MODEL,
            "models": _models(XAI_MODEL, "grok-4.6", "grok-4.3"),
            "key": XAI_API_KEY, "secret": "XAI_API_KEY", "pkg": "openai",
            "base_url": "https://api.x.ai/v1"},
}
DEFAULT_LLM_PROVIDER = _get("LLM_PROVIDER", "openai")
if DEFAULT_LLM_PROVIDER not in LLM_PROVIDERS:
    DEFAULT_LLM_PROVIDER = "openai"

# override fuori da Streamlit (script CLI: build_preview, ecc.)
_LLM_PROVIDER_OVERRIDE = ""
_LLM_MODEL_OVERRIDE = ""


def set_llm_provider(name: str, model: str = "") -> None:
    """Forza provider (e modello) negli script CLI, dove non c'e' session_state."""
    global _LLM_PROVIDER_OVERRIDE, _LLM_MODEL_OVERRIDE
    _LLM_PROVIDER_OVERRIDE = name if name in LLM_PROVIDERS else ""
    _LLM_MODEL_OVERRIDE = model or ""


def get_llm_provider() -> str:
    """Provider attivo: override CLI > scelta nella sidebar > default secrets."""
    if _LLM_PROVIDER_OVERRIDE:
        return _LLM_PROVIDER_OVERRIDE
    try:
        import streamlit as st
        chosen = st.session_state.get("llm_provider")
    except Exception:
        chosen = None
    return chosen if chosen in LLM_PROVIDERS else DEFAULT_LLM_PROVIDER


def get_llm_model(provider: str) -> str:
    """Modello scelto in sidebar per quel provider (default: quello dei secrets)."""
    conf = LLM_PROVIDERS[provider]
    if _LLM_MODEL_OVERRIDE and provider == _LLM_PROVIDER_OVERRIDE:
        return _LLM_MODEL_OVERRIDE
    try:
        import streamlit as st
        chosen = st.session_state.get(f"llm_model_{provider}")
    except Exception:
        chosen = None
    return chosen if chosen in conf["models"] else conf["default"]


def llm_conf(provider: str | None = None) -> dict:
    """Configurazione completa del provider, col modello effettivamente scelto.

    Va letta nel thread principale di Streamlit (usa session_state) e poi
    passata ai thread di lavoro: da li' session_state non e' accessibile.
    """
    name = provider or get_llm_provider()
    return {**LLM_PROVIDERS[name], "name": name, "model": get_llm_model(name)}


def llm_label(conf: dict | None = None) -> str:
    c = conf or llm_conf()
    return f"{c['label']} ({c['model']})"

# Contesto business passato all'LLM per allineare la scelta della sorgente
BUSINESS_CONTEXT = _get("BUSINESS_CONTEXT",
    "Gedshop.it e' un e-commerce B2B di gadget e articoli promozionali "
    "personalizzati (agende, penne, borracce, abbigliamento, ombrelli, zaini, "
    "portachiavi...). Ogni categoria e' un PRODOTTO FISICO da personalizzare.")

# --- Storage ---
DATABASE_URL = _get("DATABASE_URL")  # se vuoto -> JSON locale
JSON_STORAGE_PATH = _get("JSON_STORAGE_PATH", "data/store.json")


def has_llm(conf: dict | None = None) -> bool:
    """True se il provider (attivo o passato) ha una API key configurata."""
    return bool((conf or llm_conf())["key"])

# --- Default applicativi ---
DEFAULT_GEO = _get("DEFAULT_GEO", "IT")          # codice paese ISO-2
DEFAULT_LANGUAGE = _get("DEFAULT_LANGUAGE", "Italian")
YEARS_HISTORY = int(_get("YEARS_HISTORY", "5"))
PUBLISH_LEAD_MONTHS = int(_get("PUBLISH_LEAD_MONTHS", "1"))  # anticipo pubblicazione vs inizio salita

# Brand (dal profilo Dario / webinfermento)
BRAND_PRIMARY = "#317fd2"
BRAND_DARK = "#066aab"

# Mappa geo ISO-2 -> (location_name DataForSEO, language_name)
GEO_MAP = {
    "IT": ("Italy", "Italian"),
    "ES": ("Spain", "Spanish"),
    "FR": ("France", "French"),
    "DE": ("Germany", "German"),
    "GB": ("United Kingdom", "English"),
    "US": ("United States", "English"),
}


def has_provider_creds() -> bool:
    return bool(DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD)


def storage_kind() -> str:
    return "postgres" if DATABASE_URL else "json"
