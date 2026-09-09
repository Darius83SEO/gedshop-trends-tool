"""Storage pluggable: Postgres (Neon) se DATABASE_URL, altrimenti JSON locale.

Una riga per (sito, categoria, geo). La stagionalita' della vista ATTIVA e'
mirrorata su colonne (per calendario/tabella); il record completo (candidati,
vista term + vista topic, postilla) sta nel payload JSON. Tabelle prefissate gt_.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import config


def get_storage():
    if config.DATABASE_URL:
        return PostgresStorage(config.DATABASE_URL)
    return JsonStorage(config.JSON_STORAGE_PATH)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _mirror(record: dict) -> dict:
    """Estrae i campi di stagionalita' della vista attiva per le colonne."""
    mode = record.get("active_mode", "term")
    v = record.get(mode) or record.get("term") or {}
    return {
        "active_mode": mode,
        "source_note": record.get("note", ""),
        "via": record.get("via", ""),
        "portable_cross_market": bool(record.get("portable_cross_market")),
        "peak_month": v.get("peak"), "rise_start_month": v.get("rise"),
        "publish_month": v.get("pub"), "strength": v.get("strength"),
        "is_seasonal": v.get("seasonal"), "n_points": v.get("n"),
    }


# --------------------------------------------------------------------------
class PostgresStorage:
    kind = "postgres"

    def __init__(self, dsn: str):
        import psycopg2
        self._psycopg2 = psycopg2
        self.dsn = dsn
        self._ensure_schema()

    def _conn(self):
        # timeout esplicito: su Neon free il compute puo' essere sospeso e senza
        # timeout la connessione resta appesa finche' l'app non viene killata
        # (su Streamlit Cloud si vede come "Oh no. Error running app").
        return self._psycopg2.connect(self.dsn, connect_timeout=10)

    def _ensure_schema(self):
        ddl = """
        CREATE TABLE IF NOT EXISTS gt_categories (
            id SERIAL PRIMARY KEY,
            site_url TEXT NOT NULL, name TEXT NOT NULL, query_term TEXT NOT NULL,
            geo TEXT NOT NULL DEFAULT 'IT', url TEXT, status TEXT DEFAULT 'active',
            active_mode TEXT DEFAULT 'term', source_note TEXT, via TEXT,
            portable_cross_market BOOLEAN DEFAULT FALSE,
            peak_month INT, rise_start_month INT, publish_month INT,
            strength REAL, is_seasonal BOOLEAN, n_points INT,
            last_sync TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT now(),
            payload JSONB DEFAULT '{}'::jsonb,
            UNIQUE (site_url, name, geo)
        );
        CREATE TABLE IF NOT EXISTS gt_settings (
            key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMPTZ DEFAULT now()
        );
        """
        with self._conn() as c, c.cursor() as cur:
            cur.execute(ddl); c.commit()

    def get_setting(self, key, default=None):
        with self._conn() as c, c.cursor() as cur:
            cur.execute("SELECT value FROM gt_settings WHERE key=%s", (key,))
            row = cur.fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        sql = """
        INSERT INTO gt_settings (key, value) VALUES (%s,%s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
        """
        with self._conn() as c, c.cursor() as cur:
            cur.execute(sql, (key, str(value))); c.commit()

    def upsert_category(self, site_url, name, query_term, geo, url=None) -> int:
        sql = """
        INSERT INTO gt_categories (site_url, name, query_term, geo, url)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (site_url, name, geo) DO UPDATE
          SET query_term = EXCLUDED.query_term, url = EXCLUDED.url
        RETURNING id;
        """
        with self._conn() as c, c.cursor() as cur:
            cur.execute(sql, (site_url, name, query_term, geo, url))
            cid = cur.fetchone()[0]; c.commit()
        return cid

    def list_categories(self, site_url=None, geo=None) -> list[dict]:
        sql = "SELECT * FROM gt_categories WHERE 1=1"; args = []
        if site_url: sql += " AND site_url=%s"; args.append(site_url)
        if geo: sql += " AND geo=%s"; args.append(geo)
        sql += " ORDER BY name"
        with self._conn() as c, c.cursor() as cur:
            cur.execute(sql, args); cols = [d[0] for d in cur.description]
            return [self._row(dict(zip(cols, r))) for r in cur.fetchall()]

    def get_category(self, cat_id):
        with self._conn() as c, c.cursor() as cur:
            cur.execute("SELECT * FROM gt_categories WHERE id=%s", (cat_id,))
            row = cur.fetchone()
            if not row: return None
            cols = [d[0] for d in cur.description]
            return self._row(dict(zip(cols, row)))

    @staticmethod
    def _row(d):
        if isinstance(d.get("payload"), str):
            d["payload"] = json.loads(d["payload"])
        return d

    def delete_category(self, cat_id):
        with self._conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM gt_categories WHERE id=%s", (cat_id,)); c.commit()

    def save_record(self, cat_id, record):
        m = _mirror(record)
        sql = """
        UPDATE gt_categories SET active_mode=%s, source_note=%s, via=%s,
            portable_cross_market=%s, peak_month=%s, rise_start_month=%s,
            publish_month=%s, strength=%s, is_seasonal=%s, n_points=%s,
            last_sync=%s, payload=%s WHERE id=%s
        """
        with self._conn() as c, c.cursor() as cur:
            cur.execute(sql, (m["active_mode"], m["source_note"], m["via"],
                m["portable_cross_market"], m["peak_month"], m["rise_start_month"],
                m["publish_month"], m["strength"], m["is_seasonal"], m["n_points"],
                _now(), json.dumps(record, ensure_ascii=False), cat_id))
            c.commit()

    def set_active_mode(self, cat_id, mode):
        cat = self.get_category(cat_id)
        if not cat: return
        rec = cat["payload"]; rec["active_mode"] = mode
        rec["portable_cross_market"] = mode == "topic"
        self.save_record(cat_id, rec)


# --------------------------------------------------------------------------
class JsonStorage:
    kind = "json"

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("settings", {})
            return data
        return {"seq": 0, "categories": {}, "settings": {}}

    def get_setting(self, key, default=None):
        return self._data.get("settings", {}).get(key, default)

    def set_setting(self, key, value):
        self._data.setdefault("settings", {})[key] = str(value)
        self._save()

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def upsert_category(self, site_url, name, query_term, geo, url=None) -> int:
        key = f"{site_url}|{name}|{geo}"
        for cid, cat in self._data["categories"].items():
            if cat["_key"] == key:
                cat.update(query_term=query_term, url=url); self._save(); return int(cid)
        self._data["seq"] += 1; cid = self._data["seq"]
        self._data["categories"][str(cid)] = {
            "_key": key, "id": cid, "site_url": site_url, "name": name,
            "query_term": query_term, "geo": geo, "url": url, "status": "active",
            "active_mode": "term", "source_note": None, "via": None,
            "portable_cross_market": False, "peak_month": None, "rise_start_month": None,
            "publish_month": None, "strength": None, "is_seasonal": None, "n_points": None,
            "last_sync": None, "created_at": _now(), "payload": {},
        }
        self._save(); return cid

    def list_categories(self, site_url=None, geo=None):
        out = [c for c in self._data["categories"].values()
               if (not site_url or c["site_url"] == site_url) and (not geo or c["geo"] == geo)]
        return sorted(out, key=lambda c: c["name"])

    def get_category(self, cat_id):
        return self._data["categories"].get(str(cat_id))

    def delete_category(self, cat_id):
        self._data["categories"].pop(str(cat_id), None); self._save()

    def save_record(self, cat_id, record):
        cat = self._data["categories"].get(str(cat_id))
        if not cat: return
        cat["payload"] = record; cat.update(_mirror(record)); cat["last_sync"] = _now()
        self._save()

    def set_active_mode(self, cat_id, mode):
        cat = self.get_category(cat_id)
        if not cat: return
        rec = cat["payload"]; rec["active_mode"] = mode
        rec["portable_cross_market"] = mode == "topic"
        self.save_record(cat_id, rec)
