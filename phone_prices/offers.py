"""Общие структуры и разбор названий карточек."""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

CSV_FIELDS = ["model", "config", "shop", "price_rub", "version", "seller", "title", "url", "fetched_at"]


@dataclass
class Offer:
    model: str
    config: str          # найденная конфигурация "6/128" или "?"
    shop: str
    price_rub: int
    version: str         # "EAC", "Global" или "?"
    seller: str
    title: str
    url: str
    fetched_at: str = ""

    def __post_init__(self) -> None:
        if not self.fetched_at:
            self.fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def as_row(self) -> dict:
        return asdict(self)


# "6/128", "6 / 128 ГБ", "6GB/128GB", "8+256", "6 128ГБ", "6 128" (WB пишет через пробел)
_RE_CFG = re.compile(r"(?<!\d)(3|4|6|8|12|16)\s*(?:гб|gb)?\s*(?:[/+]\s*|\s+)(64|128|256|512|1024)\s*(?:гб|gb|тб|tb)?(?![\d,.])", re.I)
# "6 ГБ ... 128 ГБ" в свободной форме
_RE_CFG_LOOSE = re.compile(r"(?<!\d)(3|4|6|8|12|16)\s*(?:гб|gb)\b.*?(?<!\d)(64|128|256|512|1024)\s*(?:гб|gb)\b", re.I | re.S)
_RE_5G = re.compile(r"(?<![\w-])5g(?![\w])", re.I)
_RE_EAC = re.compile(r"ростест|рст\b|eac\b|российск|рф\b|ru\b|официальн", re.I)
_RE_GLOBAL = re.compile(r"global|глобал|\beu\b|европ|международн|китайск|\bcn\b", re.I)
_RE_PRICE = re.compile(r"(\d[\d\s  ]{2,})\s*(?:₽|руб|р\.)", re.I)


def parse_config(title: str) -> str:
    m = _RE_CFG.search(title) or _RE_CFG_LOOSE.search(title)
    return f"{m.group(1)}/{m.group(2)}" if m else "?"


def is_5g(title: str) -> bool:
    return bool(_RE_5G.search(title))


def parse_version(text: str) -> str:
    if _RE_EAC.search(text):
        return "EAC"
    if _RE_GLOBAL.search(text):
        return "Global"
    return "?"


def parse_price(text: str) -> int | None:
    """Первое число в рублях из текста, например «12 990 ₽» -> 12990."""
    m = _RE_PRICE.search(text)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else None


def drop_outliers(offers: list[Offer], factor: float = 2.0) -> list[Offer]:
    """Убрать карточки дороже factor × медианы по модели (на Маркете бывают по 50–128 тыс.)."""
    by_model: dict[str, list[int]] = {}
    for o in offers:
        by_model.setdefault(o.model, []).append(o.price_rub)
    keep: list[Offer] = []
    for o in offers:
        med = statistics.median(by_model[o.model])
        if o.price_rub <= med * factor:
            keep.append(o)
    return keep
