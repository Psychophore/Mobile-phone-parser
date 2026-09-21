"""Wildberries: JSON-поиск, который использует сам сайт. Запрашивается из контекста браузера.

Особенности выдачи WB (сентябрь 2026): бренд лежит в отдельном поле `brand`, а `name` часто начинается
с категории и без бренда («Смартфон M7 8GB+256GB Blue» при brand=POCO), у части продавцов бренд пуст,
а конфигурация пишется через пробел («6 128ГБ», «6 128»). Цена — sizes[].price.product в копейках.
Рейтинг товара — reviewRating, число отзывов — feedbacks, рейтинг продавца — supplierRating.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote_plus

from ..models import Model
from ..offers import Offer, seller_is_cross_border, seller_is_official
from . import Source
from .common import make_offer

SHOP = "wildberries.ru"

# категория в начале названия WB: «Смартфон …», «Мобильный телефон …», «Телефон …»
_NO_BRAND = {"нет бренда", "без бренда", "no brand", "-"}
_RE_CATEGORY_PREFIX = re.compile(r"^\s*(?:мобильный\s+)?(?:смартфон|телефон)\s*[,:-]?\s*", re.I)


def urls(model: Model) -> list[str]:
    q = quote_plus(model.search_text)
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


def compose_title(brand: str, name: str) -> str:
    """«POCO» + «Смартфон M7 8GB+256GB Blue» -> «POCO M7 8GB+256GB Blue».

    Категорию в начале названия убираем, бренд подставляем перед моделью, если его в названии нет.
    """
    brand, name = (brand or "").strip(), (name or "").strip()
    if brand.lower() in _NO_BRAND:
        brand = ""
    core = _RE_CATEGORY_PREFIX.sub("", name)
    if brand and brand.lower() not in core.lower():
        core = f"{brand} {core}"
    return " ".join(core.split())


def extract(text: str, model: Model, page_url: str) -> list[Offer]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    products = (data.get("data") or {}).get("products") or data.get("products") or []
    out: list[Offer] = []
    for p in products:
        price = _price(p)
        name = compose_title(p.get("brand", ""), p.get("name", ""))
        if not price or not name:
            continue
        supplier = p.get("supplier", "") or ""
        rating = p.get("reviewRating") or p.get("rating") or None
        out.append(make_offer(model, SHOP, name, price, supplier,
                              f"https://www.wildberries.ru/catalog/{p.get('id')}/detail.aspx",
                              rating=float(rating) if rating else None, reviews=int(p.get("feedbacks") or 0),
                              seller_rating=float(p["supplierRating"]) if p.get("supplierRating") else None,
                              cross_border=seller_is_cross_border(supplier), official=seller_is_official(supplier)))
    return out


SOURCE = Source(key="wb", shop=SHOP, home="https://www.wildberries.ru/", urls=urls, extract=extract, kind="json")
