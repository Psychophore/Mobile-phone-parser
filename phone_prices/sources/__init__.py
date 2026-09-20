"""Источники цен. Каждый модуль предоставляет SOURCE: Source."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..models import Model
from ..offers import Offer

# Функция извлечения: (html_или_json, model, page_url) -> список Offer
Extractor = Callable[[str, Model, str], list[Offer]]


@dataclass(frozen=True)
class Source:
    key: str                          # короткий ключ для CLI: yandex, ozon, wb, dns
    shop: str                         # имя магазина в CSV
    home: str                         # стартовая страница для прогрева cookies
    urls: Callable[[Model], list[str]]  # адреса, которые надо открыть для модели (по приоритету)
    extract: Extractor
    kind: str = "html"                # "html" — страница в браузере, "json" — запрос через fetch


def all_sources() -> dict[str, Source]:
    from . import yandex_market, ozon, wildberries, dns_shop
    out = {}
    for mod in (yandex_market, ozon, wildberries, dns_shop):
        out[mod.SOURCE.key] = mod.SOURCE
    return out
