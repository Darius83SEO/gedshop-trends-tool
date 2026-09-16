"""Provider DataForSEO -> Google Trends (endpoint explore/live).

Doc: POST /v3/keywords_data/google_trends/explore/live
Auth: Basic (login:password).

NOTA Fase 0: l'endpoint explore lavora su keyword-stringa. La risoluzione dei
Topic (mid '/m/...') non e' garantita qui: in v1 usiamo search term nel geo
scelto, con revisione umana. Il parser e' difensivo e conserva il raw payload
cosi' da poter verificare la struttura reale con le tue API.
"""
from __future__ import annotations

import base64
import threading
import time
from datetime import date, timedelta

import requests

from config import GEO_MAP
from .base import TrendsProvider, TrendsSeries

API_URL = "https://api.dataforseo.com/v3/keywords_data/google_trends/explore/live"

# codici task DataForSEO: 20000 = ok, 40102 = nessun risultato (serie vuota,
# non un errore). Tutto il resto (crediti finiti, rate limit, ...) va segnalato
# invece di passare per "Google Trends non ha dati".
_TASK_OK = {20000, 40102}
_RETRY_HTTP = {429, 500, 502, 503, 504}


class DataForSEOProvider(TrendsProvider):
    name = "dataforseo"
    # Da tracciare nel record: Google Trends convive in due varianti (Explore
    # "classico" con indice 0-100 rinormalizzato a ogni richiesta, e la nuova
    # API ufficiale con scala costante). Questo endpoint e' il primo. Salvando
    # la sorgente di ogni scarico, il giorno in cui cambia si vede da dove
    # arriva ciascuna curva invece di dover indovinare.
    source_id = "dataforseo:google_trends/explore/live (indice 0-100)"

    def __init__(self, login: str, password: str, timeout: int = 60):
        self.login = login
        self.password = password
        self.timeout = timeout
        token = base64.b64encode(f"{login}:{password}".encode()).decode()
        self._headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        }
        # una Session per thread: riusa la connessione TLS tra le chiamate
        # (le analisi girano in parallelo, e Session non e' thread-safe)
        self._local = threading.local()

    def _session(self) -> requests.Session:
        sess = getattr(self._local, "session", None)
        if sess is None:
            sess = self._local.session = requests.Session()
            sess.headers.update(self._headers)
        return sess

    def _post(self, payload, attempts: int = 3) -> dict:
        """POST con retry su errori di rete e 429/5xx (backoff 2s, 4s)."""
        for i in range(attempts):
            try:
                resp = self._session().post(API_URL, json=payload, timeout=self.timeout)
                if resp.status_code in _RETRY_HTTP and i < attempts - 1:
                    time.sleep(2 ** (i + 1)); continue
                resp.raise_for_status()
                return resp.json()
            except (requests.ConnectionError, requests.Timeout):
                if i == attempts - 1:
                    raise
                time.sleep(2 ** (i + 1))
        raise RuntimeError("DataForSEO non raggiungibile")

    # -- API ---------------------------------------------------------------
    def fetch_series(self, keyword: str, geo: str = "IT", years: int = 5,
                     date_from: str | None = None, date_to: str | None = None) -> TrendsSeries:
        location_name, language_name = GEO_MAP.get(geo, ("Italy", "Italian"))
        date_to = date.fromisoformat(date_to) if date_to else date.today()
        date_from = (date.fromisoformat(date_from) if date_from
                     else date_to - timedelta(days=365 * years + 7))

        payload = [{
            "keywords": [keyword],
            "location_name": location_name,
            "language_name": language_name,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "type": "web",
            "item_types": ["google_trends_graph", "google_trends_queries_list"],
        }]

        data = self._post(payload)
        task = (data.get("tasks") or [{}])[0]
        code = task.get("status_code")
        if code is not None and code not in _TASK_OK:
            raise RuntimeError(f"DataForSEO {code}: {task.get('status_message', '')}")
        return self._parse(keyword, geo, data)

    # -- Parsing (difensivo) ----------------------------------------------
    def _parse(self, keyword: str, geo: str, data: dict) -> TrendsSeries:
        series = TrendsSeries(keyword=keyword, geo=geo, raw=data)

        task = (data.get("tasks") or [{}])[0]
        results = task.get("result") or []
        if not results:
            return series
        items = results[0].get("items") or []

        for item in items:
            itype = item.get("type")
            if itype == "google_trends_graph":
                series.points = self._parse_graph(item)
            elif itype == "google_trends_queries_list":
                top, rising = self._parse_queries(item)
                series.related_top = top
                series.related_rising = rising
        return series

    @staticmethod
    def _parse_graph(item: dict) -> list[tuple]:
        points: list[tuple] = []
        for row in item.get("data") or []:
            # ogni row ha date_from/date_to (settimana) e values (una per keyword)
            d = row.get("date_from") or row.get("date_to")
            vals = row.get("values") or []
            val = None
            for v in vals:
                if v is not None:
                    val = v
                    break
            if d and val is not None:
                points.append((str(d)[:10], float(val)))
        return points

    @staticmethod
    def _parse_queries(item: dict):
        """Restituisce (top, rising).

        Formato reale DataForSEO: item['data'] e' un dict {'top': [...], 'rising': [...]}
        con voci {'query', 'value'}. Gestiamo anche la forma a lista per sicurezza.
        """
        top: list[dict] = []
        rising: list[dict] = []

        def _pull(entries, dest):
            for e in entries or []:
                if not isinstance(e, dict):
                    continue
                q = e.get("query") or e.get("keyword")
                if q:
                    dest.append({"query": q, "value": e.get("value")})

        data = item.get("data")
        if isinstance(data, dict):
            _pull(data.get("top"), top)
            _pull(data.get("rising"), rising)
        elif isinstance(data, list):
            for block in data:
                if not isinstance(block, dict):
                    continue
                btype = (block.get("type") or "").lower()
                entries = block.get("data") or block.get("keywords") or []
                if "rising" in btype:
                    _pull(entries, rising)
                else:
                    _pull(entries, top)
        return top, rising
