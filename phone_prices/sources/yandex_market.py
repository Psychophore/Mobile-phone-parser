"""Яндекс Маркет: поисковая выдача (/search) в категории «Смартфоны», отсортированная по цене.

Разметка выдачи (сентябрь 2026): карточка — <div data-auto="searchOrganic">, внутри
  <span data-auto="snippet-title" title="…">, ссылка <a href="/card/…/<id>?…"> и
  <span data-auto="snippet-price-current"><span>14 503</span><span> ₽</span></span>;
  рейтинг — скрытый текст «Рейтинг товара: 4.9 из 5», «Оценок: (2.8K) · 10K купили»;
  у трансграничных продавцов в блоке доставки текст «Из-за рубежа».
Рекламные врезки (data-auto="searchIncut", iPhone и т.п.) отсеиваются по названию модели.
Прямые адреса категорий вида /category/smartfony-<slug> отдают страницу «Что-то пошло не так».
"""
from __future__ import annotations

import re
from html import unescape
from urllib.parse import quote_plus, urljoin

from ..models import Model
from ..offers import Offer, parse_count, parse_price
from . import Source
from .common import extract_generic, extract_jsonld, make_offer, strip_tags

SHOP = "market.yandex.ru"
HID_SMARTPHONES = 91491   # hid категории «Смартфоны»
LR_MOSCOW = 213

# Маркер страницы с ошибкой («Что-то пошло не так» / «Тут ничего нет»), приходит с HTTP 200
_RE_FAILURE = re.compile(r'data-auto="failure"')

_RE_TITLE = re.compile(r'<[^>]+data-auto="snippet-title"[^>]*\btitle="([^"]*)"', re.I)
_RE_CARD_HREF = re.compile(r'href="(/card/[^"]+|/product--[^"]+)"', re.I)
_RE_PRICE = re.compile(r'data-auto="snippet-price-current"[^>]*>(.*?)</span>\s*</span>', re.S | re.I)
_RE_RATING = re.compile(r"Рейтинг товара:\s*([\d.,]+)\s*из\s*5", re.I)
_RE_REVIEWS = re.compile(r"Оценок:\s*\(([^)]*)\)", re.I)
_RE_ABROAD = re.compile(r"Из-за рубежа", re.I)


def urls(model: Model) -> list[str]:
    q = quote_plus(model.search_query)
    qc = quote_plus(model.search_text)
    return [
        f"https://market.yandex.ru/search?text={q}&hid={HID_SMARTPHONES}&how=aprice&lr={LR_MOSCOW}",
        f"https://market.yandex.ru/search?text={qc}&how=aprice&lr={LR_MOSCOW}",
    ]


def is_error_page(html: str) -> bool:
    return bool(_RE_FAILURE.search(html))


def _from_snippets(html: str, model: Model, page_url: str) -> list[Offer]:
    """Карточки выдачи по data-auto-атрибутам: заголовок → ссылка → текущая цена."""
    out: list[Offer] = []
    titles = list(_RE_TITLE.finditer(html))
    for i, tm in enumerate(titles):
        title = " ".join(unescape(tm.group(1)).split())
        end = titles[i + 1].start() if i + 1 < len(titles) else len(html)
        block = html[tm.end():end]
        pm = _RE_PRICE.search(block)
        price = parse_price(strip_tags(pm.group(1)) + " ₽") if pm else None
        if not title or not price:
            continue
        hm = _RE_CARD_HREF.search(block)
        href = unescape(hm.group(1)).split("?", 1)[0] if hm else ""
        rm, cm = _RE_RATING.search(block), _RE_REVIEWS.search(block)
        rating = float(rm.group(1).replace(",", ".")) if rm else None
        text = strip_tags(block[:6000])
        out.append(make_offer(model, SHOP, title, price, "", urljoin(page_url, href) if href else page_url,
                              rating=rating, reviews=parse_count(cm.group(1)) if cm else 0,
                              cross_border=bool(_RE_ABROAD.search(text))))
    return out


def extract(html: str, model: Model, page_url: str) -> list[Offer]:
    if is_error_page(html):
        return []
    offers = _from_snippets(html, model, page_url)
    if not offers:
        offers = extract_jsonld(html, model, page_url, SHOP)
    if not offers:
        offers = extract_generic(html, model, page_url, SHOP, link_pattern=r"/product--|/card/")
    return offers


SOURCE = Source(key="yandex", shop=SHOP, home="https://market.yandex.ru/", urls=urls, extract=extract,
                is_error=is_error_page, wait_for='[data-auto="snippet-price-current"]')
