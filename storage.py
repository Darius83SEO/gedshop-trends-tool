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
        from psycopg2.pool import ThreadedConnectionPool
        self._psycopg2 = psycopg2
        self.dsn = dsn
        # Pool di connessioni riusate: aprire una connessione TLS verso Neon
        # costa 0,3-1 s e prima succedeva a ogni query di ogni rerun.
        # connect_timeout: su Neon free il compute puo' essere sospeso e senza
        # timeout la connessione resta appesa finche' l'app non viene killata
        # (su Streamlit Cloud si vede come "Oh no. Error running app").
        self._pool = ThreadedConnectionPool(1, 4, dsn, connect_timeout=10)
        self._ensure_schema()

    def _run(self, fn, write: bool = False):
        """Esegue fn(cursor) con una connessione del pool.

        Neon chiude le connessioni inattive quando sospende il compute: se quella
        presa dal pool e' morta la si scarta e si riprova una volta con una nuova.
        """
        dead = (self._psycopg2.OperationalError, self._psycopg2.InterfaceError)
        for attempt in (0, 1):
            conn = self._pool.getconn()
            broken = False
            try:
                with conn.cursor() as cur:
                    out = fn(cur)
                if write:
                    conn.commit()
                else:
                    conn.rollback()  # chiude la transazione implicita di lettura
                return out
            except dead:
                broken = True
                if attempt:
                    raise
            except Exception:
                try:
                    conn.rollback()
                except dead:
                    broken = True
                raise
            finally:
                self._pool.putconn(conn, close=broken or bool(conn.closed))

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
        self._run(lambda cur: cur.execute(ddl), write=True)

    def get_setting(self, key, default=None):
        def q(cur):
            cur.execute("SELECT value FROM gt_settings WHERE key=%s", (key,))
            return cur.fetchone()
        row = self._run(q)
        return row[0] if row else default

    def set_setting(self, key, value):
        sql = """
        INSERT INTO gt_settings (key, value) VALUES (%s,%s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
        """
        self._run(lambda cur: cur.execute(sql, (key, str(value))), write=True)

    def upsert_category(self, site_url, name, query_term, geo, url=None) -> int:
        sql = """
        INSERT INTO gt_categories (site_url, name, query_term, geo, url)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (site_url, name, geo) DO UPDATE
          SET query_term = EXCLUDED.query_term, url = EXCLUDED.url
        RETURNING id;
        """
        def q(cur):
            cur.execute(sql, (site_url, name, query_term, geo, url))
            return cur.fetchone()[0]
        return self._run(q, write=True)

    def list_categories(self, site_url=None, geo=None) -> list[dict]:
        sql = "SELECT * FROM gt_categories WHERE 1=1"; args = []
        if site_url: sql += " AND site_url=%s"; args.append(site_url)
        if geo: sql += " AND geo=%s"; args.append(geo)
        sql += " ORDER BY name"

        def q(cur):
            cur.execute(sql, args); cols = [d[0] for d in cur.description]
            return [self._row(dict(zip(cols, r))) for r in cur.fetchall()]
        return self._run(q)

    def get_category(self, cat_id):
        def q(cur):
            cur.execute("SELECT * FROM gt_categories WHERE id=%s", (cat_id,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return self._row(dict(zip(cols, row)))
        return self._run(q)

    @staticmethod
    def _row(d):
        if isinstance(d.get("payload"), str):
            d["payload"] = json.loads(d["payload"])
        return d

    def delete_category(self, cat_id):
        self._run(lambda cur: cur.execute("DELETE FROM gt_categories WHERE id=%s", (cat_id,)),
                  write=True)

    def save_record(self, cat_id, record, synced: bool = True):
        """synced=False per override e validazioni: cambiano la vista attiva ma
        non i dati, quindi non devono far sembrare aggiornato un dataset vecchio."""
        m = _mirror(record)
        sql = """
        UPDATE gt_categories SET active_mode=%s, source_note=%s, via=%s,
            portable_cross_market=%s, peak_month=%s, rise_start_month=%s,
            publish_month=%s, strength=%s, is_seasonal=%s, n_points=%s,
            last_sync=COALESCE(%s, last_sync), payload=%s WHERE id=%s
        """
        args = (m["active_mode"], m["source_note"], m["via"],
                m["portable_cross_market"], m["peak_month"], m["rise_start_month"],
                m["publish_month"], m["strength"], m["is_seasonal"], m["n_points"],
                _now() if synced else None, json.dumps(record, ensure_ascii=False), cat_id)
        self._run(lambda cur: cur.execute(sql, args), write=True)

    def set_active_mode(self, cat_id, mode):
        cat = self.get_category(cat_id)
        if not cat: return
        rec = cat["payload"]; rec["active_mode"] = mode
        rec["portable_cross_market"] = mode == "topic"
        self.save_record(cat_id, rec, synced=False)


# --------------------------------------------------------------------------
class JsonStorage:
    kind = "json"

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._mtime = None
        self._data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            self._mtime = os.path.getmtime(self.path)
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("settings", {})
            return data
        return {"seq": 0, "categories": {}, "settings": {}}

    def _fresh(self):
        """Ricarica se il file e' stato cambiato da fuori (script, altra sessione):
        l'istanza e' condivisa tra i rerun."""
        try:
            if os.path.getmtime(self.path) != self._mtime:
                self._data = self._load()
        except OSError:
            pass

    def get_setting(self, key, default=None):
        self._fresh()
        return self._data.get("settings", {}).get(key, default)

    def set_setting(self, key, value):
        self._fresh()
        self._data.setdefault("settings", {})[key] = str(value)
        self._save()

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)  # scrittura atomica: mai un file a meta'
        self._mtime = os.path.getmtime(self.path)

    def upsert_category(self, site_url, name, query_term, geo, url=None) -> int:
        self._fresh()
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
        self._fresh()
        out = [c for c in self._data["categories"].values()
               if (not site_url or c["site_url"] == site_url) and (not geo or c["geo"] == geo)]
        return sorted(out, key=lambda c: c["name"])

    def get_category(self, cat_id):
        self._fresh()
        return self._data["categories"].get(str(cat_id))

    def delete_category(self, cat_id):
        self._fresh()
        self._data["categories"].pop(str(cat_id), None); self._save()

    def save_record(self, cat_id, record, synced: bool = True):
        self._fresh()
        cat = self._data["categories"].get(str(cat_id))
        if not cat: return
        cat["payload"] = record; cat.update(_mirror(record))
        if synced:
            cat["last_sync"] = _now()
        self._save()

    def set_active_mode(self, cat_id, mode):
        cat = self.get_category(cat_id)
        if not cat: return
        rec = cat["payload"]; rec["active_mode"] = mode
        rec["portable_cross_market"] = mode == "topic"
        self.save_record(cat_id, rec, synced=False)
