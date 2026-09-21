#!/usr/bin/env python3
"""Сбор актуальных цен на бюджетные смартфоны (market.yandex.ru, ozon.ru, wildberries.ru, dns-shop.ru).

Примеры:
  python parse_prices.py --ui                                     # веб-интерфейс: ключевые слова в браузере
  python parse_prices.py --models "POCO M7" --sources yandex     # проверка одной модели
  python parse_prices.py -q "чайник электрический" -s wb          # свободный поиск по ключевым словам
  python parse_prices.py                                          # все модели, все источники
  python parse_prices.py --from-html page.html --source yandex --model "POCO M7"   # разбор сохранённой страницы
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from phone_prices.collector import Collector, log
from phone_prices.models import MODELS, find_models
from phone_prices.offers import drop_outliers
from phone_prices.query import build_query
from phone_prices.report import summary, write_csv
from phone_prices.sources import all_sources
from phone_prices.sources.common import accept, read_page


def main(argv: list[str] | None = None) -> int:
    sources = all_sources()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", "-m", nargs="*", help="подстроки названий моделей; по умолчанию все")
    ap.add_argument("--query", "-q", help="свободный поиск по ключевым словам вместо списка моделей, "
                                          "напр. -q \"POCO M7 6/128\" или -q \"чайник электрический\"")
    ap.add_argument("--ram", type=int, default=0, help="для --query: целевая ОЗУ, ГБ")
    ap.add_argument("--rom", type=int, default=0, help="для --query: целевой накопитель, ГБ")
    ap.add_argument("--sources", "-s", nargs="*", default=list(sources), choices=list(sources),
                    help="источники по приоритету (по умолчанию все)")
    ap.add_argument("--out", "-o", type=Path, default=Path("prices.csv"))
    ap.add_argument("--dump", type=Path, default=Path("dumps"),
                    help="куда складывать сырые страницы и скриншоты капчи ('' — не сохранять)")
    ap.add_argument("--headed", action="store_true", help="показывать окно браузера")
    ap.add_argument("--profile", type=Path, help="каталог постоянного профиля Chromium (cookies переживают запуски)")
    ap.add_argument("--chromium", help="путь к бинарнику Chromium, если не тот, что ставит Playwright")
    ap.add_argument("--channel", choices=["chrome", "msedge", "chrome-beta", "msedge-beta"],
                    help="использовать установленный в системе Chrome/Edge вместо Chromium Playwright "
                         "(антибот Ozon хуже распознаёт настоящий браузер)")
    ap.add_argument("--stealth", action="store_true",
                    help="использовать patchright вместо playwright (pip install patchright): закрывает утечку "
                         "протокола отладки, по которой антибот Ozon распознаёт управляемый браузер")
    ap.add_argument("--proxy", help="прокси для браузера, напр. socks5://user:pass@host:1080 "
                                    "(или переменная PARSER_PROXY); нужен российский адрес для Ozon и DNS")
    ap.add_argument("--no-browser", action="store_true",
                    help="без Playwright/Chromium: только JSON-источники (WB); работает в Termux на телефоне")
    ap.add_argument("--pause", nargs=2, type=float, default=(3.0, 7.0), metavar=("MIN", "MAX"))
    ap.add_argument("--keep-outliers", action="store_true", help="не отбрасывать цены выше 2×медианы")
    ap.add_argument("--all-sellers", action="store_true",
                    help="не отсеивать трансграничных и непроверенных продавцов (по умолчанию только проверенные)")
    ap.add_argument("--from-html", type=Path, help="офлайн: разобрать сохранённую страницу вместо обхода")
    ap.add_argument("--source", choices=list(sources), help="для --from-html: какой магазин")
    ap.add_argument("--model", help="для --from-html: какая модель")
    ap.add_argument("--list", action="store_true", help="показать список моделей и выйти")
    ap.add_argument("--ui", action="store_true",
                    help="веб-интерфейс вместо консоли: ключевые слова вводятся в браузере "
                         "(http://127.0.0.1:8765, только с этого компьютера)")
    ap.add_argument("--port", type=int, default=8765, help="порт веб-интерфейса")
    a = ap.parse_args(argv)

    if a.ui:
        from phone_prices.webui import serve
        return serve(a.port)

    if a.list:
        for m in MODELS:
            print(f"{m.name:<26} {m.config:<6} {m.note}")
        return 0

    models = [build_query(a.query, ram=a.ram, rom=a.rom)] if a.query else find_models(a.models)

    if a.from_html:
        if not a.source or not (a.model or a.query):
            ap.error("--from-html требует --source и --model (или --query)")
        src = sources[a.source]
        model = models[0] if a.query else find_models([a.model])[0]
        raw = src.extract(read_page(a.from_html), model, src.home)
        offers = [o for o in raw if accept(o, model)]
        log(f"[{src.key}] {model.name}: карточек {len(raw)}, подходящих {len(offers)}")
        for o in raw:
            mark = "+" if o in offers else "-"
            trust = "✓" if o.trusted else ("×" if o.cross_border else "?")
            rating = f"{o.rating:.1f}({o.reviews})" if o.rating else f"—({o.reviews})"
            log(f"  {mark}{trust} {o.price_rub:>7} {o.config:<6} {o.version:<6} {rating:>10} {o.seller[:18]:<18} {o.title[:60]}")
        models = [model]
    else:
        offers = []
        dump = a.dump if str(a.dump) else None
        with Collector(headless=not a.headed, min_pause=a.pause[0], max_pause=a.pause[1],
                       dump_dir=dump, chromium=a.chromium, profile_dir=a.profile, proxy=a.proxy,
                       no_browser=a.no_browser, channel=a.channel,
                       stealth=a.stealth) as c:
            for key in a.sources:
                src = sources[key]
                log(f"== {src.shop}")
                for m in models:
                    offers.extend(c.collect(src, m))

    if not a.all_sellers:
        before = len(offers)
        offers = [o for o in offers if o.trusted]
        if before != len(offers):
            log(f"отброшено непроверенных продавцов: {before - len(offers)} (--all-sellers оставит их)")

    if not a.keep_outliers:
        before = len(offers)
        offers = drop_outliers(offers)
        if before != len(offers):
            log(f"отброшено выбросов: {before - len(offers)}")

    write_csv(offers, a.out)
    log(f"записано {len(offers)} строк в {a.out}")
    print()
    print(summary(offers, models))
    return 0


if __name__ == "__main__":
    sys.exit(main())
