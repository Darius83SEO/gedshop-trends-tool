"""Interfaccia comune dei provider di dati Google Trends.

Astrarre qui significa poter passare da DataForSEO all'API ufficiale Google
Trends (quando disponibile) o ad altri, senza toccare crawler/seasonality/UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TrendsSeries:
    keyword: str
    geo: str
    # serie storica: lista di (data ISO 'YYYY-MM-DD', valore 0-100)
    points: list[tuple] = field(default_factory=list)
    granularity: str = "weekly"
    related_top: list[dict] = field(default_factory=list)     # [{query, value}]
    related_rising: list[dict] = field(default_factory=list)  # [{query, value}]
    raw: dict | None = None  # payload grezzo per debug (Fase 0)

    @property
    def ok(self) -> bool:
        return bool(self.points)


class TrendsProvider:
    """Contratto minimo che ogni provider deve rispettare."""

    name: str = "base"

    def fetch_series(self, keyword: str, geo: str = "IT", years: int = 5) -> TrendsSeries:
        raise NotImplementedError
