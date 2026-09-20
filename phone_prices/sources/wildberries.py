"""Wildberries: JSON-поиск, который использует сам сайт. Запрашивается из контекста браузера."""
from __future__ import annotations

import json
from urllib.parse import quote_plus

from ..models import Model
from ..offers import Offer
from . import Source
from .common import make_offer

SHOP = "wildberries.ru"


def urls(model: Model) -> list[str]:
    q = quote_plus(f"{model.search_query} {model.config}")
    return [
        "https://search.wb.ru/exactmatch/ru/common/v9/search?appType=1&curr=rub&dest=-1257786"
        f"&query={q}&resultset=catalog&sort=priceup&spp=30&suppressSpellcheck=false",
        "https://search.wb.ru/exactmatch/ru/common/v5/search?appType=1&curr=rub&dest=-1257786"
        f"&query={q}&resultset=catalog&sort=priceup&spp=30",
    ]


def _price(p: dict) -> int | None:
    # v5+: sizes[].price.product (копейки); старые версии: salePriceU / priceU
    for s in p.get("sizes", []) or []:
        pr = s.get("price") or {}
        for k in ("product", "total", "basic"):
            if pr.get(k):
                return int(pr[k]) // 100
    for k in ("salePriceU", "priceU"):
        if p.get(k):
            return int(p[k]) // 100
    return None


def extract(text: str, model: Model, page_url: str) -> list[Offer]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    products = (data.get("data") or {}).get("products") or data.get("products") or []
    out: list[Offer] = []
    for p in products:
        price = _price(p)
        name = " ".join(x for x in (p.get("brand"), p.get("name")) if x)
        if not price or not name:
            continue
        out.append(make_offer(model, SHOP, name, price, p.get("supplier", ""),
                              f"https://www.wildberries.ru/catalog/{p.get('id')}/detail.aspx"))
    return out


SOURCE = Source(key="wb", shop=SHOP, home="https://www.wildberries.ru/", urls=urls, extract=extract, kind="json")
