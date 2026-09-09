"""Aggiornamento periodico di tutte le categorie, da riga di comando.

Serve per la sincronizzazione mensile *vera*: l'interruttore nella sidebar
funziona solo quando qualcuno apre la dashboard (Streamlit non ha uno
scheduler proprio), questo script invece si pianifica con cron / Utilita' di
pianificazione e gira anche a tool chiuso.

Uso:
    python sync_monthly.py                  # tutte le categorie, geo di default
    python sync_monthly.py --geo ES
    python sync_monthly.py --max-age 30     # salta se aggiornate da meno di 30 gg
    python sync_monthly.py --only Agende --only Penne
    python sync_monthly.py --dry-run

Credenziali: se lanci lo script dalla cartella del progetto vale
.streamlit/secrets.toml come nell'app; altrove servono le variabili d'ambiente
(DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD, DATABASE_URL, chiave del provider LLM).
Nel cron conviene quindi fare `cd` nella cartella del progetto.

Esempio cron, ogni primo del mese alle 4:00:
    0 4 1 * * cd /path/gedshop-trends-tool && /usr/bin/python sync_monthly.py >> data/sync.log 2>&1
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

import analysis
import config
from providers.dataforseo import DataForSEOProvider
from storage import get_storage


def _as_dt(value):
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Aggiorna le categorie da DataForSEO.")
    ap.add_argument("--site", default="gedshop.it")
    ap.add_argument("--geo", default=config.DEFAULT_GEO)
    ap.add_argument("--max-age", type=int, default=0, metavar="GIORNI",
                    help="salta le categorie aggiornate da meno di N giorni (0 = aggiorna tutto)")
    ap.add_argument("--only", action="append", default=[], metavar="NOME",
                    help="limita a queste categorie (ripetibile)")
    ap.add_argument("--llm", choices=sorted(config.LLM_PROVIDERS), default=None,
                    help="provider LLM per la scelta della sorgente")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.llm:
        config.set_llm_provider(args.llm)
    if not config.has_provider_creds():
        print("ERRORE: DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD non impostate.", file=sys.stderr)
        return 2

    storage = get_storage()
    cats = storage.list_categories(args.site, args.geo)
    if args.only:
        wanted = {n.strip().lower() for n in args.only}
        cats = [c for c in cats if c["name"].strip().lower() in wanted]
    if args.max_age > 0:
        limite = datetime.now(timezone.utc) - timedelta(days=args.max_age)
        cats = [c for c in cats if not (_as_dt(c.get("last_sync")) or datetime.min.replace(tzinfo=timezone.utc)) > limite]

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    print(f"[{stamp}] {args.site} ({args.geo}) · {len(cats)} categorie da aggiornare "
          f"· storage {storage.kind} · AI {config.llm_label() if config.has_llm() else '(regole)'}")
    if args.dry_run:
        for c in cats:
            print("  -", c["name"])
        return 0

    prov = DataForSEOProvider(config.DATAFORSEO_LOGIN, config.DATAFORSEO_PASSWORD)
    ko = []
    for i, cat in enumerate(cats, start=1):
        try:
            rec = analysis.analyze_category(prov, cat["name"], cat["query_term"], args.geo)
            if rec.get("term") or rec.get("topic"):
                storage.save_record(cat["id"], rec)
                print(f"  {i}/{len(cats)} OK   {cat['name']}")
            else:
                ko.append(cat["name"])
                print(f"  {i}/{len(cats)} VUOTO {cat['name']} (nessun dato Trends)")
        except Exception as e:
            ko.append(f"{cat['name']}: {e}")
            print(f"  {i}/{len(cats)} KO   {cat['name']}: {e}")

    print(f"Fatto: {len(cats) - len(ko)} aggiornate, {len(ko)} con problemi.")
    return 1 if ko else 0


if __name__ == "__main__":
    raise SystemExit(main())
