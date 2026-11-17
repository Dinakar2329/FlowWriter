"""SQLite persistence: encrypted content, prepared statements, migrations, WAL."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any
from cryptography.fernet import Fernet, InvalidToken
from .domain import Action, Provider, PRESETS, PROMPT_ACTION, make_id
from .insights import InsightRecord

SCHEMA_VERSION = 2

class Store:
    def __init__(self, path: Path, cipher: Fernet | None) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            try:
                path.parent.chmod(0o700)
            except OSError:
                pass
        self.path = path
        self.cipher = cipher
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute("PRAGMA busy_timeout=10000")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self._migrate()
        if os.name == "posix":
            try:
                path.chmod(0o600)
            except OSError:
                pass

    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError("This database was created by a newer FlowWriter Studio version.")
        if version == 0:
            with self.conn:
                self.conn.executescript("""
                    CREATE TABLE IF NOT EXISTS profiles (
                      id TEXT PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL,
                      model TEXT NOT NULL, stream INTEGER NOT NULL DEFAULT 1,
                      updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS actions (
                      id TEXT PRIMARY KEY, name TEXT NOT NULL, prompt TEXT NOT NULL,
                      face INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS history (
                      id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                      action TEXT NOT NULL, source_app TEXT NOT NULL DEFAULT '',
                      provider_name TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
                      instruction_enc BLOB, input_enc BLOB, output_enc BLOB,
                      status TEXT NOT NULL, latency_ms INTEGER NOT NULL DEFAULT 0,
                      is_favorite INTEGER NOT NULL DEFAULT 0, error_type TEXT NOT NULL DEFAULT ''
                    );
                    CREATE INDEX IF NOT EXISTS idx_history_created ON history(created_at DESC, id DESC);
                    CREATE INDEX IF NOT EXISTS idx_history_status ON history(status);
                    CREATE TABLE IF NOT EXISTS preferences (
                      name TEXT PRIMARY KEY, value TEXT NOT NULL
                    );
                """)
                self.conn.execute("PRAGMA user_version=1")
                for i, (name, prompt) in enumerate(PRESETS):
                    self.conn.execute(
                        "INSERT INTO actions (id, name, prompt, face, position) VALUES (?,?,?,?,?)",
                        (f"built-in-{i}", name, prompt, 0 if i < 6 else 1, i % 6),
                    )
                self.conn.execute(
                    "INSERT INTO profiles VALUES (?,?,?,?,?,?)",
                    ("local-default", "Local Ollama", "http://localhost:11434/v1", "llama3.2", 1, self.now()),
                )
                self.conn.execute("INSERT INTO preferences VALUES ('active_profile','local-default')")
                self.conn.execute("INSERT INTO preferences VALUES ('save_history','true')")
                self.conn.execute("INSERT INTO preferences VALUES ('private_mode','false')")
            version = 1
        if version < 2:
            # Version 2 adds the Prompt action to the front of the wheel, once. It is skipped when an
            # action with that name already exists, and never comes back if the user deletes it later.
            with self.conn:
                names = [r[0].casefold() for r in self.conn.execute("SELECT name FROM actions")]
                if PROMPT_ACTION[0].casefold() not in names:
                    position = self.conn.execute("SELECT COALESCE(MAX(position)+1, 0) FROM actions WHERE face=0").fetchone()[0]
                    self.conn.execute(
                        "INSERT INTO actions (id, name, prompt, face, position) VALUES (?,?,?,?,?)",
                        ("built-in-prompt", *PROMPT_ACTION, 0, position),
                    )
                self.conn.execute("PRAGMA user_version=2")

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _encrypt(self, text: str | None) -> bytes | None:
        if text is None or self.cipher is None:
            return None
        return self.cipher.encrypt(text.encode("utf-8"))

    def _decrypt(self, data: bytes | None) -> str:
        if not data:
            return ""
        if self.cipher is None:
            return "[Encrypted history unavailable: unlock the original keychain]"
        try:
            return self.cipher.decrypt(data).decode("utf-8")
        except (InvalidToken, UnicodeError):
            return "[Unable to decrypt: original history key is missing or changed]"

    def get_pref(self, name: str, fallback: str = "") -> str:
        with self._lock:
            row = self.conn.execute("SELECT value FROM preferences WHERE name=?", (name,)).fetchone()
        return row[0] if row else fallback

    def set_pref(self, name: str, value: str) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO preferences(name,value) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                (name, value),
            )

    def profiles(self) -> list[Provider]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM profiles ORDER BY updated_at DESC").fetchall()
        return [Provider(r["id"], r["name"], r["base_url"], r["model"], bool(r["stream"])) for r in rows]

    def active_profile(self) -> Provider:
        profiles = self.profiles()
        active_id = self.get_pref("active_profile")
        return next((p for p in profiles if p.id == active_id), profiles[0])

    def save_profile(self, profile: Provider) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO profiles VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "name=excluded.name,base_url=excluded.base_url,model=excluded.model,"
                "stream=excluded.stream,updated_at=excluded.updated_at",
                (profile.id, profile.name, profile.base_url, profile.model, int(profile.stream), self.now()),
            )

    def delete_profile(self, profile_id: str) -> None:
        if len(self.profiles()) <= 1:
            raise ValueError("Keep at least one provider profile.")
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
        if self.get_pref("active_profile") == profile_id:
            self.set_pref("active_profile", self.profiles()[0].id)

    def actions(self) -> list[Action]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM actions ORDER BY face,position,name").fetchall()
        return [Action(r["id"], r["name"], r["prompt"], r["face"], r["position"]) for r in rows]

    def save_action(self, action: Action) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO actions VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "name=excluded.name,prompt=excluded.prompt,face=excluded.face,position=excluded.position",
                (action.id, action.name, action.prompt, action.face, action.position),
            )

    def delete_action(self, action_id: str) -> None:
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM actions WHERE id=?", (action_id,))

    def log_action(
        self, action: str, *, source_app: str = "", provider_name: str = "", model: str = "",
        instruction: str = "", input_text: str = "", output_text: str = "",
        status: str = "generated", latency_ms: int = 0, error_type: str = ""
    ) -> int | None:
        if self.get_pref("save_history", "true") != "true" or self.get_pref("private_mode") == "true":
            return None
        # Never store raw inputs if the encryption key isn't available.
        if self.cipher is None:
            return None
        with self._lock, self.conn:
            cursor = self.conn.execute(
                """INSERT INTO history
                (created_at,action,source_app,provider_name,model,instruction_enc,input_enc,output_enc,status,latency_ms,error_type)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (self.now(), action, self._encrypt(source_app[:150]).decode("ascii"), provider_name[:120], model[:160],
                 self._encrypt(instruction), self._encrypt(input_text), self._encrypt(output_text),
                 status, max(latency_ms, 0), error_type[:60]),
            )
            return int(cursor.lastrowid)

    def update_history(self, row_id: int | None, status: str, output_text: str | None = None) -> None:
        if row_id is None:
            return
        with self._lock, self.conn:
            if output_text is None:
                self.conn.execute("UPDATE history SET status=? WHERE id=?", (status, row_id))
            else:
                self.conn.execute(
                    "UPDATE history SET status=?, output_enc=? WHERE id=?",
                    (status, self._encrypt(output_text), row_id),
                )

    def recent(self, limit: int = 500, query: str = "", status: str = "All") -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 2000))
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM history ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        needle = query.casefold().strip()
        for r in rows:
            item = dict(r)
            item["source_app"] = self._decrypt(item["source_app"].encode("ascii")) if item["source_app"] else ""
            item["instruction"] = self._decrypt(item.pop("instruction_enc"))
            item["input_text"] = self._decrypt(item.pop("input_enc"))
            item["output_text"] = self._decrypt(item.pop("output_enc"))
            if status != "All" and item["status"] != status:
                continue
            if needle and needle not in " ".join(str(item.get(k, "")) for k in (
                "action", "source_app", "model", "input_text", "output_text", "instruction"
            )).casefold():
                continue
            out.append(item)
        return out

    def favorite(self, row_id: int, flag: bool) -> None:
        with self._lock, self.conn:
            self.conn.execute("UPDATE history SET is_favorite=? WHERE id=?", (int(flag), row_id))

    def history_count(self, status: str = "All") -> int:
        with self._lock:
            if status == "All":
                row = self.conn.execute("SELECT COUNT(*) FROM history").fetchone()
            else:
                row = self.conn.execute("SELECT COUNT(*) FROM history WHERE status=?", (status,)).fetchone()
        return int(row[0])

    def _open_row(self, row) -> dict[str, Any]:
        item = dict(row)
        item["source_app"] = self._decrypt(item["source_app"].encode("ascii")) if item["source_app"] else ""
        for source, target in (("instruction_enc", "instruction"), ("input_enc", "input_text"), ("output_enc", "output_text")):
            item[target] = self._decrypt(item.pop(source))
        return item

    def history_page(
        self, before: tuple[str, int] | None = None, limit: int = 30, offset: int = 0,
        status: str = "All",
    ) -> list[dict[str, Any]]:
        """Read entries newest-first, without the search-screen cap.

        Use `before` (a stable cursor) to continue after a known row, or `offset`
        to jump to a numbered page. `status` narrows the list to one outcome.
        Only the rows of the requested page are decrypted.
        """
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        clauses, args = [], []
        if before:
            clauses.append("(created_at,id)<(?,?)")
            args.extend(before)
        if status != "All":
            clauses.append("status=?")
            args.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            rows = self.conn.execute(
                f"SELECT * FROM history {where} ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
        return [self._open_row(row) for row in rows]

    def history_rows(self, ids: list[int]) -> list[dict[str, Any]]:
        """Decrypt exactly these entries, in the order given (missing ones are skipped)."""
        ids = [int(i) for i in ids][:100]
        if not ids:
            return []
        with self._lock:
            rows = self.conn.execute(
                f"SELECT * FROM history WHERE id IN ({','.join('?' * len(ids))})", ids
            ).fetchall()
        by_id = {row["id"]: row for row in rows}
        return [self._open_row(by_id[i]) for i in ids if i in by_id]

    def search_history_ids(self, query: str, status: str = "All", cancel=None, progress=None) -> list[int] | None:
        """Ids of every saved entry that matches, newest first, with no record limit.

        Text is encrypted, so matching has to decrypt. It works in small batches so
        it can run on a background thread, report progress and stop when `cancel`
        is set (returns None then). Nothing readable is kept after it returns.
        """
        needle = query.casefold().strip()
        total, scanned, cursor, found = self.history_count(status), 0, None, []
        while True:
            if cancel is not None and cancel.is_set():
                return None
            clauses, args = [], []
            if cursor:
                clauses.append("(created_at,id)<(?,?)")
                args.extend(cursor)
            if status != "All":
                clauses.append("status=?")
                args.append(status)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            with self._lock:
                rows = self.conn.execute(
                    "SELECT id,created_at,action,model,source_app,instruction_enc,input_enc,output_enc "
                    f"FROM history {where} ORDER BY created_at DESC,id DESC LIMIT 100", args,
                ).fetchall()
            if not rows:
                return found
            for row in rows:
                scanned += 1
                if not needle:
                    found.append(row["id"])
                    continue
                item = self._open_row(row)
                haystack = " ".join(str(item[k]) for k in ("action", "source_app", "model", "input_text", "output_text", "instruction"))
                if needle in haystack.casefold():
                    found.append(row["id"])
            cursor = (rows[-1]["created_at"], rows[-1]["id"])
            if progress is not None:
                progress(scanned, total)

    def daily_counts(self, days: int = 7) -> dict:
        """Entries per local calendar day. Reads only timestamps, so nothing is decrypted."""
        since = (datetime.now(timezone.utc) - timedelta(days=days + 1)).isoformat(timespec="seconds")
        with self._lock:
            rows = self.conn.execute("SELECT created_at FROM history WHERE created_at>=?", (since,)).fetchall()
        counts: dict = {}
        for (stamp,) in rows:
            try:
                day = datetime.fromisoformat(stamp).astimezone().date()
            except ValueError:
                continue
            counts[day] = counts.get(day, 0) + 1
        return counts

    def insight_boundary(self) -> int:
        """Pin a refresh to saved rows that exist when the page is opened."""
        with self._lock:
            return self.conn.execute("SELECT COALESCE(MAX(id),0) FROM history").fetchone()[0]

    def insight_batch(self, after_id: int, through_id: int) -> list[InsightRecord]:
        """Read bounded batches without the history-search limit or plaintext cache."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id,created_at,action,status,source_app,output_enc FROM history "
                "WHERE id>? AND id<=? ORDER BY id LIMIT 128", (after_id, through_id),
            ).fetchall()
        records = []
        for row in rows:
            source = words = None
            if self.cipher is not None:
                try:
                    source = self.cipher.decrypt(row["source_app"].encode("ascii")).decode("utf-8") if row["source_app"] else ""
                    output = self.cipher.decrypt(row["output_enc"]).decode("utf-8") if row["output_enc"] else ""
                    words = len(output.split())
                except (InvalidToken, UnicodeError):
                    source = words = None
            records.append(InsightRecord(row["id"], row["created_at"], row["action"], row["status"], source, words))
        return records

    def delete_history(self, row_id: int) -> None:
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM history WHERE id=?", (row_id,))

    def clear_history(self) -> None:
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM history")
        # Best effort to compact; secure deletion on SSD cannot be guaranteed.
        with self._lock:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.execute("VACUUM")

    def stats(self) -> dict:
        with self._lock:
            r = self.conn.execute("""SELECT COUNT(*) AS total,
                SUM(CASE WHEN status='replaced' THEN 1 ELSE 0 END) AS applied,
                SUM(CASE WHEN status='copied' THEN 1 ELSE 0 END) AS copied,
                SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) AS rejected,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS errors
                FROM history""").fetchone()
        return {k: int(r[k] or 0) for k in r.keys()}

    def close(self) -> None:
        with self._lock:
            self.conn.close()
