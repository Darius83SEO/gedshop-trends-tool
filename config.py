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

# --- LLM (selezione automatica sorgente Topic/Search term) ---
OPENAI_API_KEY = _get("OPENAI_API_KEY")
OPENAI_MODEL = _get("OPENAI_MODEL", "gpt-4.1")

GEMINI_API_KEY = _get("GEMINI_API_KEY") or _get("GOOGLE_API_KEY")
GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-2.5-flash")

ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _get("ANTHROPIC_MODEL", "claude-sonnet-5")

# Provider disponibili per la scelta della sorgente. `pkg` = pacchetto pip da
# installare, mostrato nella UI quando manca.
LLM_PROVIDERS = {
    "openai": {"label": "ChatGPT", "model": OPENAI_MODEL,
               "key": OPENAI_API_KEY, "secret": "OPENAI_API_KEY", "pkg": "openai"},
    "gemini": {"label": "Gemini Flash", "model": GEMINI_MODEL,
               "key": GEMINI_API_KEY, "secret": "GEMINI_API_KEY", "pkg": "google-genai"},
    "anthropic": {"label": "Claude Sonnet", "model": ANTHROPIC_MODEL,
                  "key": ANTHROPIC_API_KEY, "secret": "ANTHROPIC_API_KEY", "pkg": "anthropic"},
}
DEFAULT_LLM_PROVIDER = _get("LLM_PROVIDER", "openai")
if DEFAULT_LLM_PROVIDER not in LLM_PROVIDERS:
    DEFAULT_LLM_PROVIDER = "openai"

# override fuori da Streamlit (script CLI: build_preview, ecc.)
_LLM_PROVIDER_OVERRIDE = ""


def set_llm_provider(name: str) -> None:
    """Forza il provider (usato dagli script CLI, senza session_state)."""
    global _LLM_PROVIDER_OVERRIDE
    _LLM_PROVIDER_OVERRIDE = name if name in LLM_PROVIDERS else ""


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


def llm_conf() -> dict:
    return LLM_PROVIDERS[get_llm_provider()]


def llm_label() -> str:
    c = llm_conf()
    return f"{c['label']} ({c['model']})"

# Contesto business passato all'LLM per allineare la scelta della sorgente
BUSINESS_CONTEXT = _get("BUSINESS_CONTEXT",
    "Gedshop.it e' un e-commerce B2B di gadget e articoli promozionali "
    "personalizzati (agende, penne, borracce, abbigliamento, ombrelli, zaini, "
    "portachiavi...). Ogni categoria e' un PRODOTTO FISICO da personalizzare.")

# --- Storage ---
DATABASE_URL = _get("DATABASE_URL")  # se vuoto -> JSON locale
JSON_STORAGE_PATH = _get("JSON_STORAGE_PATH", "data/store.json")


def has_llm() -> bool:
    """True se il provider attivo ha una API key configurata."""
    return bool(llm_conf()["key"])

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
