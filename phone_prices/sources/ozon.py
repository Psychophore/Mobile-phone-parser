"""Ozon: HTML-выдача поиска. Внутри страницы данные лежат в JSON состояния виджетов."""
from __future__ import annotations

import json
import re
from urllib.parse import quote_plus

from ..models import Model
from ..offers import Offer, parse_price
from . import Source
from .common import extract_generic, extract_jsonld, make_offer, strip_tags

SHOP = "ozon.ru"


def urls(model: Model) -> list[str]:
    q = quote_plus(f"{model.search_query} {model.config}")
    return [f"https://www.ozon.ru/search/?text={q}&from_global=true&category=15502"]


def _from_widget_states(html: str, model: Model, page_url: str) -> list[Offer]:
    """Найти JSON вида {"items":[{"action":{"link":"/product/..."},"mainState":[...]}]}."""
    out: list[Offer] = []
    for m in re.finditer(r"\"(searchResultsV2[^\"]*)\":\"(.*?)\"(?=,\"|\})", html):
        try:
            state = json.loads(m.group(2).encode().decode("unicode_escape"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for item in state.get("items", []):
            link = (item.get("action") or {}).get("link", "")
            title, price = "", None
            for atom in item.get("mainState", []) or []:
                a = atom.get("atom") or {}
                t = a.get("type")
                if t == "textAtom" and not title:
                    title = strip_tags(a.get("textAtom", {}).get("text", ""))
                if t == "priceV2" and price is None:
                    for p in a.get("priceV2", {}).get("price", []):
                        if p.get("textStyle") == "PRICE":
                            price = parse_price(p.get("text", "") + " ₽")
                            break
            if title and price and link:
                out.append(make_offer(model, SHOP, title, price, "", "https://www.ozon.ru" + link))
    return out


def extract(html: str, model: Model, page_url: str) -> list[Offer]:
    offers = _from_widget_states(html, model, page_url)
    if not offers:
        offers = extract_jsonld(html, model, page_url, SHOP)
    if not offers:
        offers = extract_generic(html, model, page_url, SHOP, link_pattern=r"/product/")
    return offers


SOURCE = Source(key="ozon", shop=SHOP, home="https://www.ozon.ru/", urls=urls, extract=extract)
