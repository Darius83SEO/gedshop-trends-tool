"""Cuore deterministico del tool: nessun LLM.

Da una serie storica (data, valore) settimanale su ~5 anni calcola:
  - il profilo stagionale medio mensile (12 valori normalizzati 0-100)
  - il mese di picco
  - il mese in cui le ricerche iniziano a salire
  - il mese entro cui pubblicare (inizio salita meno un anticipo)
  - un indice di forza della stagionalita' (per distinguere categorie piatte)
  - una frase-consiglio generata da template (niente LLM)
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from statistics import mean
from typing import Iterable

MESI = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]
MESI_ABBR = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu",
             "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

# Sotto questa soglia di forza consideriamo la categoria "poco stagionale".
FLAT_THRESHOLD = 0.22


@dataclass
class SeasonalityResult:
    profile: list[float]          # 12 valori 0-100 (indice 0 = gennaio)
    peak_month: int               # 1-12
    rise_start_month: int         # 1-12
    publish_month: int            # 1-12
    strength: float               # 0..1 (0 = piatto)
    is_seasonal: bool
    n_points: int
    advice: str

    def to_dict(self) -> dict:
        return asdict(self)


def _month_of(d) -> int:
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return d.month


def monthly_profile(points: Iterable[tuple]) -> list[float]:
    """Media per mese-del-calendario su tutti gli anni, normalizzata a max=100."""
    buckets: list[list[float]] = [[] for _ in range(12)]
    for d, v in points:
        if v is None:
            continue
        buckets[_month_of(d) - 1].append(float(v))
    profile = [mean(b) if b else 0.0 for b in buckets]
    peak = max(profile) if any(profile) else 0.0
    if peak > 0:
        profile = [round(p / peak * 100, 1) for p in profile]
    return profile


def _strength(profile: list[float]) -> float:
    """Ampiezza relativa del ciclo: (max-min)/max, 0=piatto 1=molto stagionale."""
    hi = max(profile)
    lo = min(profile)
    if hi <= 0:
        return 0.0
    return round((hi - lo) / hi, 3)


def _find_rise_start(profile: list[float], peak_idx: int) -> int:
    """Mese in cui la domanda inizia a superare stabilmente la media annuale,
    salendo verso il picco.

    Non usiamo il minimo assoluto (troppo presto e poco azionabile): a un
    copywriter interessa quando l'interesse comincia a costruirsi sopra il
    livello medio. Prendiamo quindi il tratto contiguo sopra la media che
    culmina nel picco e ne restituiamo il primo mese, gestendo il wrap-around.
    """
    threshold = mean(profile)
    start = peak_idx
    for _ in range(11):  # al massimo un giro completo
        prev = (start - 1) % 12
        if profile[prev] >= threshold:
            start = prev
        else:
            break
    return start


def analyze(points, publish_lead_months: int = 1) -> SeasonalityResult:
    pts = [(d, v) for d, v in points if v is not None]
    profile = monthly_profile(pts)

    if not any(profile):
        return SeasonalityResult(
            profile=profile, peak_month=0, rise_start_month=0, publish_month=0,
            strength=0.0, is_seasonal=False, n_points=len(pts),
            advice="Dati insufficienti per stimare la stagionalita'.",
        )

    peak_idx = max(range(12), key=lambda i: profile[i])
    strength = _strength(profile)
    is_seasonal = strength >= FLAT_THRESHOLD

    rise_idx = _find_rise_start(profile, peak_idx)
    publish_idx = (rise_idx - publish_lead_months) % 12

    peak_m = peak_idx + 1
    rise_m = rise_idx + 1
    pub_m = publish_idx + 1

    advice = _advice(rise_m, peak_m, pub_m, is_seasonal)

    return SeasonalityResult(
        profile=profile, peak_month=peak_m, rise_start_month=rise_m,
        publish_month=pub_m, strength=strength, is_seasonal=is_seasonal,
        n_points=len(pts), advice=advice,
    )


def _a(mese: str) -> str:
    """Preposizione eufonica: 'ad aprile' ma 'a marzo'."""
    return f"ad {mese}" if mese[:1] in "aeiou" else f"a {mese}"


def _advice(rise_m: int, peak_m: int, pub_m: int, is_seasonal: bool) -> str:
    if not is_seasonal:
        return ("Categoria poco stagionale: l'interesse resta abbastanza costante "
                "tutto l'anno, senza un picco marcato. Puoi pubblicare quando vuoi.")
    return (f"Le ricerche iniziano a salire {_a(MESI[rise_m - 1])}, con il picco "
            f"{_a(MESI[peak_m - 1])}. Pubblica entro {MESI[pub_m - 1]} per arrivare "
            f"indicizzato prima che la domanda cresca.")


def month_name(m: int, abbr: bool = False) -> str:
    if not m or m < 1 or m > 12:
        return "-"
    return (MESI_ABBR if abbr else MESI)[m - 1].capitalize()
