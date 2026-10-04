"""Реестр задач в SQLite — внешняя система, в которую агент пишет (гейт курса: действие с записью).

Три защиты, каждая из своей поломки:
- замок на данные, а не на кнопку (02.10.26: из 10 одновременных правок протокола 7 терялись молча);
- ключ идемпотентности у встречи, задачи и карточки (повтор прогона не плодит дубли);
- история статусов с цитатой и встречей-основанием (без цитаты статус не меняется).
"""

import hashlib
import json
import sqlite3
import threading
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
  id INTEGER PRIMARY KEY, date TEXT NOT NULL, title TEXT, source_digest TEXT UNIQUE NOT NULL,
  source_name TEXT, status TEXT NOT NULL DEFAULT 'processed', protocol_md TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY, description TEXT NOT NULL, responsible_id TEXT, responsible_text TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','done','dropped')),
  due TEXT, date_set TEXT NOT NULL, date_closed TEXT, source_meeting_id INTEGER, source_line INTEGER,
  quote TEXT, idem_key TEXT UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_history (
  id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, field TEXT NOT NULL, old TEXT, new TEXT,
  quote TEXT, meeting_id INTEGER, source TEXT NOT NULL, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cards (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, meeting_id INTEGER, task_id INTEGER, title TEXT NOT NULL,
  payload TEXT, quote TEXT, status TEXT NOT NULL DEFAULT 'open', idem_key TEXT UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, meeting_id INTEGER, source_name TEXT, started_at TEXT NOT NULL, finished_at TEXT,
  outcome TEXT, model TEXT, calls INTEGER, steps INTEGER, tokens_in INTEGER, tokens_out INTEGER,
  seconds REAL, cost_usd REAL, error TEXT
);
CREATE TABLE IF NOT EXISTS run_steps (
  id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, n INTEGER NOT NULL, name TEXT NOT NULL, ok INTEGER NOT NULL,
  seconds REAL, tokens_in INTEGER, tokens_out INTEGER, detail TEXT
);
"""

_WRITE_LOCK = threading.Lock()


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def key(*parts) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:32]


class Registry:
    def __init__(self, path: str):
        self.path = path
        self._local = threading.local()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            # транзакциями управляем сами (BEGIN IMMEDIATE в write), неявные транзакции модуля выключены
            conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def close(self):
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # --- запись: только под замком и в одной транзакции ---
    def write(self, fn):
        with _WRITE_LOCK:
            conn = self._conn()
            try:
                conn.execute("BEGIN IMMEDIATE")
                result = fn(conn)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def meeting_by_digest(self, digest: str):
        return self._conn().execute("SELECT * FROM meetings WHERE source_digest=?", (digest,)).fetchone()

    def create_meeting(self, date: str, title: str, digest: str, source_name: str) -> int:
        def tx(c):
            row = c.execute("SELECT id FROM meetings WHERE source_digest=?", (digest,)).fetchone()
            if row:
                return row["id"]
            cur = c.execute(
                "INSERT INTO meetings(date,title,source_digest,source_name,status,created_at) VALUES(?,?,?,?,?,?)",
                (date, title, digest, source_name, "processing", now()),
            )
            return cur.lastrowid
        return self.write(tx)

    def active_tasks(self) -> list:
        return [dict(r) for r in self._conn().execute("SELECT * FROM tasks WHERE status='active' ORDER BY id")]

    def all_tasks(self) -> list:
        return [dict(r) for r in self._conn().execute("SELECT * FROM tasks ORDER BY id")]

    def open_cards(self) -> list:
        return [dict(r) for r in self._conn().execute("SELECT * FROM cards WHERE status='open' ORDER BY id")]

    def runs(self) -> list:
        return [dict(r) for r in self._conn().execute("SELECT * FROM runs ORDER BY id")]

    def run_steps(self, run_id: int) -> list:
        return [dict(r) for r in self._conn().execute("SELECT * FROM run_steps WHERE run_id=? ORDER BY n", (run_id,))]

    def apply_meeting_result(self, meeting_id: int, date: str, new_tasks: list, closures: list, cards: list, protocol_md: str):
        """Всё, что меняет реестр по встрече, — одной транзакцией. Частично записанной встречи не бывает."""
        def tx(c):
            created, closed, carded = [], [], []
            for t in new_tasks:
                k = key("task", meeting_id, t["description"].lower(), t.get("responsible_id") or t.get("responsible_text"))
                if c.execute("SELECT 1 FROM tasks WHERE idem_key=?", (k,)).fetchone():
                    continue
                cur = c.execute(
                    "INSERT INTO tasks(description,responsible_id,responsible_text,status,due,date_set,source_meeting_id,"
                    "source_line,quote,idem_key,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (t["description"], t.get("responsible_id"), t.get("responsible_text"), "active", t.get("due"), date,
                     meeting_id, t.get("line"), t.get("quote"), k, now()),
                )
                c.execute(
                    "INSERT INTO task_history(task_id,field,old,new,quote,meeting_id,source,at) VALUES(?,?,?,?,?,?,?,?)",
                    (cur.lastrowid, "status", None, "active", t.get("quote"), meeting_id, "meeting", now()),
                )
                created.append(cur.lastrowid)
            for cl in closures:
                row = c.execute("SELECT status, source_meeting_id, date_set FROM tasks WHERE id=?", (cl["task_id"],)).fetchone()
                if not row or row["status"] != "active" or row["source_meeting_id"] == meeting_id or (row["date_set"] or "") > date:
                    continue  # своя встреча не закрывает свои задачи (Планёрка 21.09.26); ранняя — поставленные позже
                c.execute("UPDATE tasks SET status=?, date_closed=? WHERE id=?", (cl["status"], date, cl["task_id"]))
                c.execute(
                    "INSERT INTO task_history(task_id,field,old,new,quote,meeting_id,source,at) VALUES(?,?,?,?,?,?,?,?)",
                    (cl["task_id"], "status", "active", cl["status"], cl["quote"], meeting_id, "meeting", now()),
                )
                closed.append(cl["task_id"])
            for cd in cards:
                k = cd.get("idem_key") or key("card", meeting_id, cd["kind"], cd["title"])
                if c.execute("SELECT 1 FROM cards WHERE idem_key=?", (k,)).fetchone():
                    continue
                cur = c.execute(
                    "INSERT INTO cards(kind,meeting_id,task_id,title,payload,quote,status,idem_key,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (cd["kind"], meeting_id, cd.get("task_id"), cd["title"], json.dumps(cd.get("payload", {}), ensure_ascii=False),
                     cd.get("quote"), "open", k, now()),
                )
                carded.append(cur.lastrowid)
            c.execute("UPDATE meetings SET status='processed', protocol_md=? WHERE id=?", (protocol_md, meeting_id))
            return {"created": created, "closed": closed, "cards": carded}
        return self.write(tx)

    def add_card(self, kind: str, title: str, meeting_id=None, payload=None, quote=None):
        def tx(c):
            k = key("card", meeting_id, kind, title)
            if c.execute("SELECT id FROM cards WHERE idem_key=?", (k,)).fetchone():
                return None
            return c.execute(
                "INSERT INTO cards(kind,meeting_id,title,payload,quote,status,idem_key,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (kind, meeting_id, title, json.dumps(payload or {}, ensure_ascii=False), quote, "open", k, now()),
            ).lastrowid
        return self.write(tx)

    def set_meeting_status(self, meeting_id: int, status: str):
        self.write(lambda c: c.execute("UPDATE meetings SET status=? WHERE id=?", (status, meeting_id)))

    # --- журнал прогонов: мониторинг по конкретному запуску (шаги, стоимость, ошибки) ---
    def start_run(self, source_name: str, model: str) -> int:
        return self.write(lambda c: c.execute(
            "INSERT INTO runs(source_name,started_at,model) VALUES(?,?,?)", (source_name, now(), model)).lastrowid)

    def log_step(self, run_id: int, n: int, name: str, ok: bool, seconds: float, tokens_in=0, tokens_out=0, detail=""):
        self.write(lambda c: c.execute(
            "INSERT INTO run_steps(run_id,n,name,ok,seconds,tokens_in,tokens_out,detail) VALUES(?,?,?,?,?,?,?,?)",
            (run_id, n, name, int(ok), round(seconds, 3), tokens_in, tokens_out, detail[:2000])))

    def finish_run(self, run_id: int, meeting_id, outcome: str, budget, error: str = ""):
        self.write(lambda c: c.execute(
            "UPDATE runs SET meeting_id=?, finished_at=?, outcome=?, calls=?, steps=?, tokens_in=?, tokens_out=?, "
            "seconds=?, cost_usd=?, error=? WHERE id=?",
            (meeting_id, now(), outcome, budget.calls, budget.steps, budget.tokens_in, budget.tokens_out,
             round(budget.elapsed(), 3), round(budget.cost_usd, 6), error[:2000], run_id)))
