#!/usr/bin/env python3
"""Бот-консультант: подбор смартфона по трём вопросам и лучшая цена у проверенных продавцов.

Цены берутся из снимков парсера (CSV `parse_prices.py`) в каталоге data/prices.

Примеры:
  python bot.py --console                         # поговорить с ботом в терминале, без Telegram
  TELEGRAM_BOT_TOKEN=123:ABC python bot.py        # запустить в Telegram
  python bot.py --stats                           # сводка по журналу: сколько людей, подборов, бюджеты
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from advisor.affiliate import Affiliate
from advisor.catalog import load_catalog
from advisor.dialog import Advisor, Reply, plural
from advisor.events import EventLog, read_events, stats
from advisor.prices import PriceStore


def console(advisor: Advisor) -> int:
    """Диалог в терминале: цифра — нажать кнопку, иначе — отправить текст."""
    def show(replies: list[Reply]) -> list:
        flat = []
        for r in replies:
            print("\n" + re.sub(r"<[^>]+>", "", r.text).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
            for row in r.buttons:
                for b in row:
                    flat.append(b)
                    print(f"  [{len(flat)}] {b.text}" + (f"  → {b.url}" if b.url else ""))
        return flat

    buttons = show(advisor.handle_text("console", "/start"))
    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line.isdigit() and 1 <= int(line) <= len(buttons) and buttons[int(line) - 1].data:
            buttons = show(advisor.handle_button("console", buttons[int(line) - 1].data))
        else:
            buttons = show(advisor.handle_text("console", line))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prices", type=Path, nargs="*", default=[Path("data/prices")],
                    help="CSV парсера или каталоги с ними (по умолчанию data/prices)")
    ap.add_argument("--affiliate", type=Path, default=os.environ.get("AFFILIATE_CONFIG") or None,
                    help="JSON с шаблонами партнёрских ссылок и рекламной пометкой (см. advisor/affiliate.py)")
    ap.add_argument("--events", type=Path, default=Path("data/events.jsonl"), help="журнал событий")
    ap.add_argument("--console", action="store_true", help="диалог в терминале вместо Telegram")
    ap.add_argument("--stats", action="store_true", help="сводка по журналу событий и выход")
    a = ap.parse_args(argv)

    if a.stats:
        print(stats(read_events(a.events)))
        return 0

    prices = PriceStore.load(a.prices)
    newest = prices.newest()
    n = len(prices.models())
    print(f"Цены: {n} {plural(n, 'модель', 'модели', 'моделей')}, свежайший снимок {newest:%d.%m.%Y %H:%M} UTC" if newest
          else "Цен нет: запустите parse_prices.py --out data/prices/<дата>.csv", file=sys.stderr)
    advisor = Advisor(load_catalog(), prices, Affiliate.load(a.affiliate),
                      EventLog(None if a.console else a.events, salt=os.environ.get("EVENTS_SALT", "")))
    if a.console:
        return console(advisor)

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Нужен токен бота: TELEGRAM_BOT_TOKEN=... (выдаёт @BotFather). Для проверки без Telegram: --console",
              file=sys.stderr)
        return 2
    from advisor.telegram import TelegramClient, run
    try:
        run(TelegramClient(token), advisor)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
