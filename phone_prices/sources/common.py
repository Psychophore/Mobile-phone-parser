"""Общие приёмы извлечения карточек из HTML: JSON-LD и текстовый фолбэк."""
from __future__ import annotations

import email
import json
import re
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

from ..models import Model
from ..offers import Offer, is_5g, parse_config, parse_price, parse_version

_RE_JSONLD = re.compile(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I)
_RE_TAG = re.compile(r"<[^>]+>")


def strip_tags(s: str) -> str:
    return " ".join(unescape(_RE_TAG.sub(" ", s)).split())


def _iter_products(obj):
    """Рекурсивно найти узлы schema.org Product."""
    if isinstance(obj, dict):
        t = obj.get("@type")
        if t == "Product" or (isinstance(t, list) and "Product" in t):
            yield obj
        for v in obj.values():
            yield from _iter_products(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_products(v)


def _offer_price(offers) -> int | None:
    if isinstance(offers, list):
        prices = [p for p in (_offer_price(o) for o in offers) if p]
        return min(prices) if prices else None
    if isinstance(offers, dict):
        for k in ("lowPrice", "price"):
            v = offers.get(k)
            if v not in (None, ""):
                try:
                    return int(float(str(v).replace(" ", "").replace(",", ".")))
                except ValueError:
                    pass
    return None


def extract_jsonld(html: str, model: Model, page_url: str, shop: str) -> list[Offer]:
    out: list[Offer] = []
    for block in _RE_JSONLD.findall(html):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for p in _iter_products(data):
            title = strip_tags(str(p.get("name", "")))
            price = _offer_price(p.get("offers"))
            if not title or not price:
                continue
            url = p.get("url") or ""
            if isinstance(p.get("offers"), dict) and p["offers"].get("url"):
                url = p["offers"]["url"]
            seller = ""
            offers = p.get("offers")
            if isinstance(offers, dict) and isinstance(offers.get("seller"), dict):
                seller = offers["seller"].get("name", "")
            out.append(make_offer(model, shop, title, price, seller, urljoin(page_url, url) if url else page_url))
    return out


def make_offer(model: Model, shop: str, title: str, price: int, seller: str, url: str,
               extra_text: str = "", **extra) -> Offer:
    """extra: rating, reviews, seller_rating, cross_border, official (см. Offer)."""
    return Offer(
        model=model.name,
        config=parse_config(title),
        shop=shop,
        price_rub=price,
        version=parse_version(title + " " + extra_text),
        seller=seller,
        title=title,
        url=url,
        **extra,
    )


_RE_ACCESSORY = re.compile(r"чехол|стекло|пл[её]нк|защитн|аккумулятор|батаре[яи] для|кабель|зарядн|"
                           r"держатель|бампер|накладк|подставк|наушник|запчаст|дисплей для|корпус для", re.I)


def accept(o: Offer, model: Model) -> bool:
    """Оставить карточку: относится к модели, не аксессуар, не 5G, конфигурация целевая или не определена.

    Какие из правил применять, решает сама модель (см. `Model.skip_accessories`, `skip_5g`,
    `min_price`): у моделей из списка включены все, свободный запрос может их снять.
    """
    if not model.matches_title(o.title):
        return False
    if model.skip_accessories and _RE_ACCESSORY.search(o.title):
        return False
    if model.skip_5g and is_5g(o.title):
        return False
    if model.config and o.config not in ("?", model.config):
        return False
    return o.price_rub >= model.min_price


def extract_generic(html: str, model: Model, page_url: str, shop: str,
                    link_pattern: str, window: int = 2500) -> list[Offer]:
    """Фолбэк: ссылки на карточки + ближайшая цена в тексте после ссылки."""
    out: list[Offer] = []
    seen: set[str] = set()
    pat = r"<a[^>]+href=[\"']([^\"']*(?:" + link_pattern + r")[^\"']*)[\"'][^>]*>(.*?)</a>"
    for m in re.finditer(pat, html, re.S | re.I):
        href, inner = m.group(1), strip_tags(m.group(2))
        if not inner or len(inner) < 8 or href in seen:
            continue
        chunk = strip_tags(html[m.end(): m.end() + window])
        price = parse_price(chunk)
        if not price:
            continue
        seen.add(href)
        out.append(make_offer(model, shop, inner, price, "", urljoin(page_url, unescape(href)), chunk[:300]))
    return out


def read_page(path: Path) -> str:
    """Прочитать сохранённую страницу: обычный HTML/JSON или .mhtml (так сохраняет Chrome на Android:
    меню → «Скачать»; внутри multipart с quoted-printable, берём часть text/html)."""
    data = path.read_bytes()
    head = data[:4096].lower()
    if path.suffix.lower() in (".mhtml", ".mht") or (b"mime-version:" in head and b"multipart/related" in head):
        msg = email.message_from_bytes(data)
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    return data.decode("utf-8", errors="replace")
