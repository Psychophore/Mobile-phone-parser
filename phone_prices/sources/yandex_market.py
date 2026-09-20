"""Яндекс Маркет: страницы категории модели (/search подменяет выдачу после 2–3 запросов)."""
from __future__ import annotations

import re
from urllib.parse import quote_plus

from ..models import Model
from ..offers import Offer
from . import Source
from .common import extract_generic, extract_jsonld

SHOP = "market.yandex.ru"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def urls(model: Model) -> list[str]:
    return [
        f"https://market.yandex.ru/category/smartfony-{_slug(model.name)}",
        f"https://market.yandex.ru/search?text={quote_plus(model.search_query + ' ' + model.config)}",
    ]


def extract(html: str, model: Model, page_url: str) -> list[Offer]:
    offers = extract_jsonld(html, model, page_url, SHOP)
    if not offers:
        offers = extract_generic(html, model, page_url, SHOP, link_pattern=r"/product--|/card/")
    return offers


SOURCE = Source(key="yandex", shop=SHOP, home="https://market.yandex.ru/", urls=urls, extract=extract)
