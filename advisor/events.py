"""Журнал событий бота (JSON Lines) и сводка для проверки спроса.

Идентификатор Telegram не пишется: вместо него короткий хэш с солью, этого хватает, чтобы считать
уникальных людей и повторные визиты.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


class EventLog:
    def __init__(self, path: Path | None, salt: str = ""):
        self.path = Path(path) if path else None
        self.salt = salt

    def user(self, chat_id: int | str) -> str:
        return hashlib.sha256(f"{self.salt}:{chat_id}".encode()).hexdigest()[:12]

    def write(self, event: str, chat_id: int | str, **fields) -> None:
        if not self.path:
            return
        rec = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "event": event, "user": self.user(chat_id), **fields}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def stats(events: list[dict]) -> str:
    """Короткая сводка: сколько людей пришло, сколько дошло до подбора, какие бюджеты и модели."""
    users = {e["user"] for e in events}
    started = {e["user"] for e in events if e["event"] == "start"}
    results = [e for e in events if e["event"] == "result"]
    finished = {e["user"] for e in results}
    empty = sum(1 for e in results if not e.get("models"))
    returning = sum(1 for u, n in Counter(e["user"] for e in results).items() if n > 1)
    budgets = Counter(e.get("budget") for e in results)
    shown = Counter(m for e in results for m in e.get("models", []))
    lines = [
        f"Людей: {len(users)}, начали: {len(started)}, получили подбор: {len(finished)}",
        f"Подборов: {len(results)}, из них пустых: {empty}, людей с повторным подбором: {returning}",
        "Бюджеты: " + (", ".join(f"{b} — {n}" for b, n in budgets.most_common()) or "—"),
        "Чаще всего советовали: " + (", ".join(f"{m} — {n}" for m, n in shown.most_common(5)) or "—"),
    ]
    return "\n".join(lines)
