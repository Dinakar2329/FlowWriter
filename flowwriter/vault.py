"""OS secret storage for provider credentials and the history encryption key.

No automatic plaintext fallback: missing or locked keychain disables encrypted history
and persisted credentials, but a session key can still be used until exit.
"""
from __future__ import annotations
import os
from cryptography.fernet import Fernet, InvalidToken

SERVICE = "FlowWriterStudio"
HISTORY_SECRET = "history-master-key-v1"

class SecretVault:
    def __init__(self, backend=None) -> None:
        self._session: dict[str, str] = {}
        if backend is None:
            try:
                import keyring
                backend = keyring
            except ImportError:
                backend = None
        self.backend = backend

    def get(self, label: str) -> str:
        if label in self._session:
            return self._session[label]
        if self.backend is None:
            return ""
        try:
            return self.backend.get_password(SERVICE, label) or ""
        except Exception:
            return ""

    def put(self, label: str, value: str) -> bool:
        """Returns True only when the OS keychain confirmed persisted storage."""
        if not value:
            self.remove(label)
            return True
        self._session[label] = value
        if self.backend is None:
            return False
        try:
            self.backend.set_password(SERVICE, label, value)
            return self.backend.get_password(SERVICE, label) == value
        except Exception:
            return False

    def remove(self, label: str) -> None:
        self._session.pop(label, None)
        if self.backend is not None:
            try:
                self.backend.delete_password(SERVICE, label)
            except Exception:
                pass

    def history_cipher(self, existing_db=None):
        """Returns Fernet or None. Never rotate a missing key for existing history."""
        env_key = os.environ.get("FLOWWRITER_HISTORY_KEY", "").strip()
        if env_key:
            try:
                return Fernet(env_key.encode("ascii"))
            except (ValueError, UnicodeError) as exc:
                raise ValueError("FLOWWRITER_HISTORY_KEY must be a valid Fernet key.") from exc
        key = self.get(HISTORY_SECRET)
        if not key:
            if existing_db is not None:
                from pathlib import Path
                import sqlite3
                path = Path(existing_db)
                if path.exists():
                    try:
                        with sqlite3.connect(str(path)) as con:
                            count = con.execute("SELECT COUNT(*) FROM history WHERE input_enc IS NOT NULL").fetchone()[0]
                        if count:
                            # Refuse to rotate a missing key; the old history remains intact.
                            return None
                    except sqlite3.Error:
                        return None
            key = Fernet.generate_key().decode("ascii")
            if not self.put(HISTORY_SECRET, key):
                self._session.pop(HISTORY_SECRET, None)
                return None
        try:
            return Fernet(key.encode("ascii"))
        except (ValueError, InvalidToken):
            return None
