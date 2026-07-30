"""Estrazione delle categorie di PRIMO LIVELLO da un sito e-commerce.

Strategia: analizza il menu di navigazione (header/nav) della home e, in
appoggio, la sitemap. Restituisce candidati {name, url} da far poi validare
manualmente all'operatore (menu JS o tassonomie sporche -> revisione umana).
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; GedshopTrendsTool/1.0)"}

# link di servizio da scartare (non sono categorie merceologiche)
_STOP = re.compile(
    r"(carrello|cart|checkout|login|account|wishlist|contatt|chi-siamo|about|"
    r"privacy|cookie|termini|condizioni|spedizion|resi|faq|blog|news|assistenza|"
    r"newsletter|preventivo|area-clienti|lang|/it/?$|/en/?$|javascript:|mailto:|tel:)",
    re.I,
)


def _same_domain(base: str, href: str) -> bool:
    try:
        return urlparse(base).netloc == urlparse(href).netloc
    except Exception:
        return False


def _clean_name(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def crawl_categories(site_url: str, max_items: int = 60, timeout: int = 20) -> list[dict]:
    """Ritorna una lista di candidati categoria di primo livello: [{name, url}]."""
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    resp = requests.get(site_url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    candidates: dict[str, dict] = {}

    # 1) Menu di navigazione: nav, elementi con classi 'menu'/'nav'
    nav_scopes = soup.find_all("nav")
    nav_scopes += soup.find_all(attrs={"class": re.compile(r"(menu|nav|category|categorie)", re.I)})

    for scope in nav_scopes:
        for a in scope.find_all("a", href=True):
            _add_candidate(candidates, site_url, a)

    # 2) Fallback: se il menu ha prodotto poco, guarda tutti i link della home
    if len(candidates) < 5:
        for a in soup.find_all("a", href=True):
            _add_candidate(candidates, site_url, a)

    items = list(candidates.values())
    # ordina per lunghezza nome (le voci di menu tendono a essere brevi e pulite)
    items.sort(key=lambda c: len(c["name"]))
    return items[:max_items]


def _add_candidate(store: dict, base: str, a) -> None:
    href = a.get("href", "").strip()
    name = _clean_name(a.get_text())
    if not href or not name:
        return
    if len(name) < 2 or len(name) > 40:
        return
    if _STOP.search(href) or _STOP.search(name):
        return
    full = urljoin(base, href)
    if not _same_domain(base, full):
        return
    path = urlparse(full).path.strip("/")
    if not path:  # link alla home
        return
    # euristica primo livello: percorso poco profondo
    depth = path.count("/")
    if depth > 2:
        return
    key = name.lower()
    if key not in store:
        store[key] = {"name": name, "url": full}
