"""Ozon: выдача поиска. Данные карточек лежат в JSON состояния виджетов (widgetStates) — в HTML страницы
и в XHR-ответах composer-api / entrypoint-api, которые сама страница запрашивает и которые коллектор
перехватывает (Source.capture). Ключ виджета выдачи — searchResultsV2 / tileGridDesktop.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote_plus

from ..models import Model
from ..offers import Offer, parse_count, parse_price
from . import Source
from .common import extract_generic, extract_jsonld, make_offer, strip_tags

SHOP = "ozon.ru"


def urls(model: Model) -> list[str]:
    q = quote_plus(f"{model.search_query} {model.config}")
    return [f"https://www.ozon.ru/search/?text={q}&from_global=true&category=15502"]


_WIDGET_KEYS = ("searchResultsV2", "tileGridDesktop", "tileGrid", "skuGrid")


def _items_from_state(state: dict, model: Model) -> list[Offer]:
    """{"items":[{"action":{"link":"/product/..."},"mainState":[...]}]} -> Offer."""
    out: list[Offer] = []
    for item in state.get("items", []) or []:
        link = (item.get("action") or {}).get("link", "") or item.get("link", "")
        title, price, rating, reviews = "", None, None, 0
        atoms = list(item.get("mainState", []) or []) + list(item.get("rightState", []) or [])
        for atom in atoms:
            a = atom.get("atom") or atom
            t = a.get("type")
            if t == "textAtom" and not title:
                title = strip_tags((a.get("textAtom") or {}).get("text", ""))
            elif t == "priceV2" and price is None:
                for p in (a.get("priceV2") or {}).get("price", []):
                    if p.get("textStyle") == "PRICE":
                        price = parse_price(p.get("text", "") + " ₽")
                        break
            elif t == "price" and price is None:
                price = parse_price((a.get("price") or {}).get("price", "") + " ₽")
            elif t == "labelList":
                for lab in (a.get("labelList") or {}).get("items", []):
                    txt = re.sub(r"(?<=\d)[\s\u00a0](?=\d)", "", strip_tags(lab.get("title", "")))  # «1 245» -> «1245»
                    is_star = "star" in json.dumps(lab.get("icon") or {})
                    m = re.match(r"([\d.,]+)", txt)
                    if is_star and m and rating is None:
                        rating = float(m.group(1).replace(",", "."))
                    elif "отзыв" in txt.lower() and m:
                        reviews = parse_count(m.group(1))
        if title and price and link:
            out.append(make_offer(model, SHOP, title, price, "", "https://www.ozon.ru" + link.split("?", 1)[0],
                                  rating=rating, reviews=reviews))
    return out


def _from_widget_states(text: str, model: Model, page_url: str) -> list[Offer]:
    """Состояния виджетов: из JSON composer-api (widgetStates) или из HTML страницы (та же структура, экранированная)."""
    out: list[Offer] = []
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return out
        for key, val in (data.get("widgetStates") or {}).items():
            if not key.startswith(_WIDGET_KEYS):
                continue
            try:
                state = json.loads(val) if isinstance(val, str) else val
            except json.JSONDecodeError:
                continue
            out += _items_from_state(state, model)
        return out
    for m in re.finditer(r"\"((?:%s)[^\"]*)\":\"(.*?)\"(?=,\"|\})" % "|".join(_WIDGET_KEYS), text):
        try:
            state = json.loads(m.group(2).encode().decode("unicode_escape"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        out += _items_from_state(state, model)
    return out


def extract(html: str, model: Model, page_url: str) -> list[Offer]:
    offers = _from_widget_states(html, model, page_url)
    if not offers:
        offers = extract_jsonld(html, model, page_url, SHOP)
    if not offers:
        offers = extract_generic(html, model, page_url, SHOP, link_pattern=r"/product/")
    return offers


SOURCE = Source(key="ozon", shop=SHOP, home="https://www.ozon.ru/", urls=urls, extract=extract,
                capture=r"(entrypoint-api|composer-api)\.bx/page/json")
