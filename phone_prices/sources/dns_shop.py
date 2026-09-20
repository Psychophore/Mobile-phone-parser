"""DNS: выдача поиска. Без браузера отвечает 401."""
from __future__ import annotations

import re
from urllib.parse import quote_plus

from ..models import Model
from ..offers import Offer, parse_price
from . import Source
from .common import extract_generic, extract_jsonld, make_offer, strip_tags

SHOP = "dns-shop.ru"


def urls(model: Model) -> list[str]:
    return [f"https://www.dns-shop.ru/search/?q={quote_plus(model.search_query + ' ' + model.config)}&category=17a8a01d16404e77"]


def _from_cards(html: str, model: Model, page_url: str) -> list[Offer]:
    out: list[Offer] = []
    for card in re.split(r"(?=<div[^>]+class=\"catalog-product\b)", html)[1:]:
        m = re.search(r"<a[^>]+class=\"catalog-product__name[^\"]*\"[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", card, re.S)
        if not m:
            continue
        title = strip_tags(m.group(2))
        pm = re.search(r"product-buy__price[^>]*>(.*?)</", card, re.S)
        price = parse_price(strip_tags(pm.group(1)) + " ₽") if pm else None
        if title and price:
            out.append(make_offer(model, SHOP, title, price, "DNS", "https://www.dns-shop.ru" + m.group(1),
                                  official=True))
    return out


def extract(html: str, model: Model, page_url: str) -> list[Offer]:
    offers = _from_cards(html, model, page_url)
    if not offers:
        offers = extract_jsonld(html, model, page_url, SHOP)
    if not offers:
        offers = extract_generic(html, model, page_url, SHOP, link_pattern=r"/product/")
    for o in offers:
        if o.version == "?":
            o.version = "EAC"  # DNS торгует только официальными поставками
    return offers


SOURCE = Source(key="dns", shop=SHOP, home="https://www.dns-shop.ru/", urls=urls, extract=extract)
