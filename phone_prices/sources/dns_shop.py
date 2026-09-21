"""DNS: выдача поиска. Без браузера отвечает 401 (Qrator), с IP дата-центра — 403.

Разметка (сентябрь 2026, по дампам с российского IP): карточка <div class="catalog-product …">,
название — <a class="catalog-product__name" title="6.9" Смартфон POCO M7 128 ГБ черный [ядер - 8x(2.8 ГГц),
6 ГБ, 2 SIM, …]"> (накопитель перед скобкой, ОЗУ внутри скобки), цена <div class="product-buy__price">15 999 ₽</div>,
рейтинг <a class="catalog-product__rating"><b>4.66 </b><span>|</span>521 отзыв</a>. У товаров не в наличии
ссылка абсолютная и ведёт на /product/analog/… (список аналогов) — такие карточки пропускаются.
В скриптах страницы есть словарь формы обратной связи со словом «Вы не робот» — не капча.
"""
from __future__ import annotations

import re
from urllib.parse import quote_plus, urljoin

from ..models import Model
from ..offers import Offer, parse_count, parse_price
from . import Source
from .common import extract_generic, extract_jsonld, make_offer, strip_tags

SHOP = "dns-shop.ru"


def urls(model: Model) -> list[str]:
    return [f"https://www.dns-shop.ru/search/?q={quote_plus(model.search_text)}&category=17a8a01d16404e77"]


_RE_NAME = re.compile(r'<a[^>]+class="catalog-product__name[^"]*"[^>]+href="([^"]+)"([^>]*)>(.*?)</a>', re.S)
_RE_TITLE_ATTR = re.compile(r'title="([^"]*)"')
_RE_RATING = re.compile(r'catalog-product__rating[^>]*>.*?<b>\s*([\d.,]+)\s*</b>(?:.*?</span>)?\s*([\d\s\u00a0]+)\s*отзыв', re.S)
# «… 128 ГБ черный [ядер - 8x(2.8 ГГц), 6 ГБ, 2 SIM, …]» -> 6/128
_RE_DNS_CFG = re.compile(r"(?<!\d)(64|128|256|512|1024)\s*ГБ[^\[]*\[[^\]]*?(?<!\d)(2|3|4|6|8|12|16)\s*ГБ", re.I)


def _from_cards(html: str, model: Model, page_url: str) -> list[Offer]:
    out: list[Offer] = []
    for card in re.split(r'(?=<div[^>]+class="catalog-product\b)', html)[1:]:
        m = _RE_NAME.search(card)
        if not m:
            continue
        href = urljoin("https://www.dns-shop.ru/", m.group(1))
        if "/product/analog/" in href or 'data-avail-status="out_of_stock"' in card[:600]:
            continue                        # нет в наличии: DNS ведёт на список аналогов
        ta = _RE_TITLE_ATTR.search(m.group(2))
        title = strip_tags(ta.group(1)) if ta else strip_tags(m.group(3))   # в title полная спецификация
        pm = re.search(r'class="product-buy__price"[^>]*>(.*?)</div>', card, re.S)
        price = parse_price(strip_tags(pm.group(1)) + " ₽") if pm else None
        if not (title and price):
            continue
        rm = _RE_RATING.search(card)
        o = make_offer(model, SHOP, title, price, "DNS", href, official=True,
                       rating=float(rm.group(1).replace(",", ".")) if rm else None,
                       reviews=parse_count(re.sub(r"\s", "", rm.group(2))) if rm else 0)
        cm = _RE_DNS_CFG.search(title)
        if o.config == "?" and cm:
            o.config = f"{cm.group(2)}/{cm.group(1)}"
        out.append(o)
    return out


def extract(html: str, model: Model, page_url: str) -> list[Offer]:
    offers = _from_cards(html, model, page_url)
    if not offers and "catalog-product" not in html:   # разметка сменилась — запасные способы
        offers = extract_jsonld(html, model, page_url, SHOP)
        if not offers:
            offers = extract_generic(html, model, page_url, SHOP, link_pattern=r"/product/")
    for o in offers:
        if o.version == "?":
            o.version = "EAC"  # DNS торгует только официальными поставками
    return offers


SOURCE = Source(key="dns", shop=SHOP, home="https://www.dns-shop.ru/", urls=urls, extract=extract,
                wait_for=".product-buy__price")
