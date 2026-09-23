"""Telegram-бот на долгом опросе (getUpdates), только стандартная библиотека.

Долгий опрос не требует белого адреса и домена: бот работает с домашнего компьютера, рядом с парсером.
Прокси берётся из переменных окружения HTTPS_PROXY, как у urllib.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

from .dialog import Advisor, Reply

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, token: str, opener=None, timeout: int = 60):
        self.token = token
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    def call(self, method: str, **params) -> dict | list | bool:
        body = json.dumps(params, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(API.format(token=self.token, method=method), data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with self._open(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                data = json.loads(e.read().decode("utf-8"))
            except Exception:
                raise TelegramError(f"{method}: HTTP {e.code}") from e
        if not data.get("ok"):
            raise TelegramError(f"{method}: {data.get('description', data)}")
        return data["result"]


def markup(reply: Reply) -> dict | None:
    if not reply.buttons:
        return None
    rows = []
    for row in reply.buttons:
        rows.append([{"text": b.text, "url": b.url} if b.url else {"text": b.text, "callback_data": b.data}
                     for b in row])
    return {"inline_keyboard": rows}


def send(client: TelegramClient, chat_id: int, replies: list[Reply]) -> None:
    for r in replies:
        params = {"chat_id": chat_id, "text": r.text, "parse_mode": "HTML",
                  "link_preview_options": {"is_disabled": True}}
        m = markup(r)
        if m:
            params["reply_markup"] = m
        client.call("sendMessage", **params)


def handle_update(client: TelegramClient, advisor: Advisor, upd: dict) -> None:
    if "message" in upd:
        msg = upd["message"]
        if msg.get("chat", {}).get("type") != "private" or "text" not in msg:
            return
        send(client, msg["chat"]["id"], advisor.handle_text(msg["chat"]["id"], msg["text"]))
    elif "callback_query" in upd:
        cq = upd["callback_query"]
        try:
            client.call("answerCallbackQuery", callback_query_id=cq["id"])
        except TelegramError:
            pass   # кнопка устарела — ответ всё равно отправим
        chat_id = cq.get("message", {}).get("chat", {}).get("id") or cq["from"]["id"]
        send(client, chat_id, advisor.handle_button(chat_id, cq.get("data", "")))


def run(client: TelegramClient, advisor: Advisor, log=lambda s: print(s, file=sys.stderr, flush=True)) -> None:
    me = client.call("getMe")
    log(f"Бот @{me.get('username')} запущен. Остановить: Ctrl+C")
    client.call("setMyCommands", commands=[{"command": "start", "description": "Подобрать смартфон"},
                                           {"command": "help", "description": "Как это работает"}])
    offset = 0
    while True:
        try:
            updates = client.call("getUpdates", offset=offset, timeout=50,
                                  allowed_updates=["message", "callback_query"])
        except (TelegramError, OSError) as e:
            log(f"getUpdates: {e}; повтор через 5 с")
            time.sleep(5)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            try:
                handle_update(client, advisor, upd)
            except Exception as e:   # один сломанный ответ не должен ронять бота
                log(f"ошибка обработки {upd.get('update_id')}: {e.__class__.__name__}: {e}")
