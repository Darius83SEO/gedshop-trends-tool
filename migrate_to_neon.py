"""Migra i dati dallo store JSON locale a Neon Postgres.

Uso (una tantum, dopo aver creato il DB `gedshop_trends` su Neon e messo
DATABASE_URL in .streamlit/secrets.toml):

    python migrate_to_neon.py

Copia categorie + record (viste term/topic, stagionalita', postille, flag).
"""
from __future__ import annotations

import sys

import config
from storage import JsonStorage, PostgresStorage


def main():
    if not config.DATABASE_URL:
        sys.exit("DATABASE_URL non impostato: aggiungilo in .streamlit/secrets.toml (DB Neon 'gedshop_trends').")

    src = JsonStorage(config.JSON_STORAGE_PATH)
    dst = PostgresStorage(config.DATABASE_URL)

    cats = src.list_categories()
    if not cats:
        sys.exit(f"Nessuna categoria in {config.JSON_STORAGE_PATH}.")

    n = 0
    for c in cats:
        cid = dst.upsert_category(c["site_url"], c["name"], c["query_term"],
                                  c["geo"], url=c.get("url"))
        if c.get("payload"):
            dst.save_record(cid, c["payload"])
            n += 1
        print(f"  migrata: {c['name']} ({c['geo']})")
    print(f"\nOK — {len(cats)} categorie ({n} con analisi) migrate su Neon.")


if __name__ == "__main__":
    main()
