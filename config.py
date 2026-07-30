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

# Contesto business passato all'LLM per allineare la scelta della sorgente
BUSINESS_CONTEXT = _get("BUSINESS_CONTEXT",
    "Gedshop.it e' un e-commerce B2B di gadget e articoli promozionali "
    "personalizzati (agende, penne, borracce, abbigliamento, ombrelli, zaini, "
    "portachiavi...). Ogni categoria e' un PRODOTTO FISICO da personalizzare.")

# --- Storage ---
DATABASE_URL = _get("DATABASE_URL")  # se vuoto -> JSON locale
JSON_STORAGE_PATH = _get("JSON_STORAGE_PATH", "data/store.json")


def has_llm() -> bool:
    return bool(OPENAI_API_KEY)

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
