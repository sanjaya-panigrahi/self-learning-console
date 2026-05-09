from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from app.core.config.settings import get_settings


class FileBackedSessionStore:
    def __init__(self, path: Path, max_messages_per_session: int = 60) -> None:
        self._path = path
        self._lock = Lock()
        self._max_messages_per_session = max(10, max_messages_per_session)

    def _load(self) -> dict[str, list[dict[str, str]]]:
        if not self._path.exists():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        sessions = payload.get("sessions", {}) if isinstance(payload, dict) else {}
        return sessions if isinstance(sessions, dict) else {}

    def _save(self, sessions: dict[str, list[dict[str, str]]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now(UTC).isoformat(),
            "sessions": sessions,
        }
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def append(self, session_id: str, message: str, role: str = "user") -> None:
        sid = (session_id or "").strip()
        text = (message or "").strip()
        if not sid or not text:
            return

        role_clean = role.strip().lower() if role else "user"
        if role_clean not in {"user", "assistant", "system"}:
            role_clean = "user"

        entry = {
            "role": role_clean,
            "message": text,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        with self._lock:
            sessions = self._load()
            history = sessions.get(sid, [])
            if not isinstance(history, list):
                history = []
            history.append(entry)
            sessions[sid] = history[-self._max_messages_per_session :]
            self._save(sessions)

    def get(self, session_id: str) -> list[str]:
        sid = (session_id or "").strip()
        if not sid:
            return []
        with self._lock:
            sessions = self._load()
            history = sessions.get(sid, [])
        if not isinstance(history, list):
            return []
        messages: list[str] = []
        for item in history:
            if not isinstance(item, dict):
                continue
            text = str(item.get("message", "")).strip()
            if text:
                messages.append(text)
        return messages

    def get_recent_context(self, session_id: str, max_messages: int = 6) -> str:
        sid = (session_id or "").strip()
        if not sid:
            return ""
        with self._lock:
            sessions = self._load()
            history = sessions.get(sid, [])
        if not isinstance(history, list):
            return ""

        limited = history[-max(1, max_messages) :]
        lines: list[str] = []
        for item in limited:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "user")).strip().lower() or "user"
            label = "User" if role == "user" else "Assistant" if role == "assistant" else "System"
            text = str(item.get("message", "")).strip()
            if text:
                lines.append(f"{label}: {text}")
        return "\n".join(lines)


_SESSION_STORE: FileBackedSessionStore | None = None


def get_session_store() -> FileBackedSessionStore:
    global _SESSION_STORE
    if _SESSION_STORE is None:
        settings = get_settings()
        _SESSION_STORE = FileBackedSessionStore(Path(settings.session_store_path))
    return _SESSION_STORE
