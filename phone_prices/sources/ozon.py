"""Ozon: выдача поиска.

Разметка (сентябрь 2026, по дампам с российского IP): выдача отрисована сервером в виджете
<div data-widget="tileGridDesktop">, каждая карточка — <div data-index="N" class="tile-root …">:
  ссылка <a href="/product/<slug>-<id>/?at=…">, цена <span class="… tsHeadline500Medium …">16 301 ₽</span>
  (следом зачёркнутая старая), название <span class="tsBody500Medium">…</span>, рейтинг и отзывы —
  <span class="tsBodyControl300XSmall" style="…">: «4.9» и «52 отзыва», либо «4.9», «3 835» и продавец
  («Ozon» — сам маркетплейс, считается официальным). Бейдж «Бренд проверен» есть почти у всех
  и относится к бренду, а не к продавцу.
Классы вида q3g_21 генерируются и меняются, опираемся только на tile-root, tsHeadline500Medium,
tsBody500Medium, tsBodyControl300XSmall.
Запасной путь — JSON состояния виджетов (widgetStates: searchResultsV2 / tileGridDesktop) из XHR-ответов
composer-api / entrypoint-api, которые коллектор перехватывает (Source.capture), либо из HTML.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote_plus

from ..models import Model
from ..offers import Offer, parse_count, parse_price, seller_is_cross_border, seller_is_official
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


_RE_TILE = re.compile(r'<div data-index="\d+" class="tile-root')
_RE_TILE_HREF = re.compile(r'href="(/product/[^"?]+)')
_RE_TILE_PRICE = re.compile(r'<span class="[^"]*tsHeadline500Medium[^"]*"[^>]*>(.*?)</span>', re.S)
_RE_TILE_TITLE = re.compile(r'<span class="[^"]*tsBody500Medium[^"]*"[^>]*>(.*?)</span>', re.S)
_RE_TILE_SMALL = re.compile(r'<span class="[^"]*tsBodyControl300XSmall[^"]*"[^>]*>(.*?)</span>', re.S)
_RE_TILE_REVIEWS = re.compile(r"^([\d\s\u2009\u00a0.,]+K?)\s*(?:отзыв\w*)?$", re.I)
_RE_TILE_RATING = re.compile(r"^\d(?:[.,]\d)?$")
_RE_CATEGORY_WORD = re.compile(r"\b(?:смартфон|мобильный телефон|телефон)\b", re.I)
_NOT_SELLER = {"стало дешевле", "рейтинг магазина", "магазин", "бренд проверен", "оригинал", "распродажа"}


def _from_tiles(html: str, model: Model, page_url: str) -> list[Offer]:
    out: list[Offer] = []
    for tile in _RE_TILE.split(html)[1:]:
        hm, pm, tm = _RE_TILE_HREF.search(tile), _RE_TILE_PRICE.search(tile), _RE_TILE_TITLE.search(tile)
        if not (hm and pm and tm):
            continue
        price = parse_price(strip_tags(pm.group(1)) + " ₽")
        # «Honor Смартфон X7d Ростест (EAC) 6/128 ГБ» — слово «Смартфон» стоит между брендом и моделью
        title = " ".join(_RE_CATEGORY_WORD.sub(" ", strip_tags(tm.group(1))).split())
        # Мелкие спаны плитки: «4.9», «52 отзыва» — либо «4.9», «3 835», «Ozon» (сразу после отзывов — продавец).
        # Прочие мелкие спаны («Стало дешевле», «рейтинг магазина») — бейджи, не продавец.
        rating, reviews, seller = None, 0, ""
        prev_was_reviews = False
        for sm in _RE_TILE_SMALL.finditer(tile):
            txt = strip_tags(sm.group(1))
            if not txt:
                continue
            if rating is None and _RE_TILE_RATING.match(txt):
                rating = float(txt.replace(",", "."))
                continue
            rm = _RE_TILE_REVIEWS.match(txt)
            if rm and not reviews:
                reviews = parse_count(re.sub(r"[\s\u2009\u00a0]", "", rm.group(1)))
                prev_was_reviews = True
                continue
            if prev_was_reviews and not seller and not re.search(r"\d", txt) and txt.lower() not in _NOT_SELLER:
                seller = txt
            prev_was_reviews = False
        if title and price:
            # «Бренд проверен» стоит почти на всех плитках — это про бренд, не про продавца.
            official = seller.lower() == "ozon" or seller_is_official(seller)
            out.append(make_offer(model, SHOP, title, price, seller, "https://www.ozon.ru" + hm.group(1),
                                  rating=rating, reviews=reviews, official=official,
                                  cross_border=seller_is_cross_border(seller)))
    return out


def extract(html: str, model: Model, page_url: str) -> list[Offer]:
    offers = _from_tiles(html, model, page_url)
    if not offers:
        offers = _from_widget_states(html, model, page_url)
    if not offers:
        offers = extract_jsonld(html, model, page_url, SHOP)
    if not offers:
        offers = extract_generic(html, model, page_url, SHOP, link_pattern=r"/product/")
    return offers


SOURCE = Source(key="ozon", shop=SHOP, home="https://www.ozon.ru/", urls=urls, extract=extract,
                capture=r"(entrypoint-api|composer-api)\.bx/page/json", wait_for=".tile-root")
