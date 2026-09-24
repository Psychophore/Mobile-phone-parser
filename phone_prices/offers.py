"""Общие структуры и разбор названий карточек."""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

CSV_FIELDS = ["model", "config", "shop", "price_rub", "version", "seller", "rating", "reviews", "seller_rating",
              "cross_border", "trusted", "title", "url", "fetched_at"]

MIN_REVIEWS = 3               # меньше оценок — карточка считается непроверенной
MIN_RATING = 4.3              # обычный продавец
MIN_RATING_CROSS_BORDER = 4.8 # трансграничные продавцы и перекупы


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
    rating: float | None = None      # рейтинг товара/карточки, 0–5
    reviews: int = 0                 # число оценок карточки
    seller_rating: float | None = None
    cross_border: bool = False       # доставка из-за рубежа / трансграничный продавец
    official: bool = False           # официальный магазин бренда

    def __post_init__(self) -> None:
        if not self.fetched_at:
            self.fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @property
    def trusted(self) -> bool:
        """Проверенное предложение: официальный магазин бренда, либо у карточки не меньше
        MIN_REVIEWS оценок с рейтингом не ниже MIN_RATING (для трансграничных продавцов
        и перекупов — не ниже MIN_RATING_CROSS_BORDER).
        Рейтинг магазина сам по себе не учитывается: у перекупов он тоже 4.9."""
        if self.official:
            return True
        need = MIN_RATING_CROSS_BORDER if self.cross_border else MIN_RATING
        return self.reviews >= MIN_REVIEWS and self.rating is not None and self.rating >= need

    def as_row(self) -> dict:
        d = asdict(self)
        d["trusted"] = int(self.trusted)
        d["cross_border"] = int(self.cross_border)
        d.pop("official")
        return {k: d[k] for k in CSV_FIELDS}


# "6/128", "6 / 128 ГБ", "6GB/128GB", "8+256", "6 128ГБ", "6 128" (WB пишет через пробел)
_RE_CFG = re.compile(r"(?<!\d)(3|4|6|8|12|16)\s*(?:гб|gb)?\s*(?:[/+]\s*|\s+)(64|128|256|512|1024)\s*(?:гб|gb|тб|tb)?(?![\d,.])", re.I)
# Маркет пишет накопитель раньше памяти: "128 ГБ, 4 ГБ", "128Gb 4Gb" — обе величины с единицами
_RE_CFG_REV = re.compile(r"(?<!\d)(64|128|256|512|1024)\s*(?:гб|gb|тб|tb)\s*[,/]?\s*(3|4|6|8|12|16)\s*(?:гб|gb)(?![\wа-яё])", re.I)
# "6 ГБ ... 128 ГБ" в свободной форме
_RE_CFG_LOOSE = re.compile(r"(?<!\d)(3|4|6|8|12|16)\s*(?:гб|gb)\b.*?(?<!\d)(64|128|256|512|1024)\s*(?:гб|gb)\b", re.I | re.S)
_RE_5G = re.compile(r"(?<![\w-])5g(?![\w])", re.I)
_RE_EAC = re.compile(r"ростест|рст\b|eac\b|российск|рф\b|ru\b|официальн", re.I)
_RE_GLOBAL = re.compile(r"global|глобал|\beu\b|европ|международн|китайск|\bcn\b", re.I)
_RE_PRICE = re.compile(r"(\d[\d\s  ]{2,})\s*(?:₽|руб|р\.)", re.I)


def parse_config(title: str) -> str:
    m = _RE_CFG.search(title)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = _RE_CFG_REV.search(title)
    if m:
        return f"{m.group(2)}/{m.group(1)}"
    m = _RE_CFG_LOOSE.search(title)
    return f"{m.group(1)}/{m.group(2)}" if m else "?"


def split_config(text: str) -> tuple[str, str]:
    """Отделить конфигурацию от запроса: «POCO M7 6/128» -> («POCO M7», «6/128»).

    Без конфигурации возвращает (текст, "?"). Нужно свободному поиску: конфигурация идёт
    в фильтр, остальные слова — в поисковую строку магазина.
    """
    m = _RE_CFG.search(text)
    if not m:
        return " ".join(text.split()), "?"
    rest = text[:m.start()] + " " + text[m.end():]
    return " ".join(rest.split()), f"{m.group(1)}/{m.group(2)}"


def is_5g(title: str) -> bool:
    return bool(_RE_5G.search(title))


def parse_version(text: str) -> str:
    if _RE_EAC.search(text):
        return "EAC"
    if _RE_GLOBAL.search(text):
        return "Global"
    return "?"


# «Оценок: (2.8K)» / «(161)» / «2,8 тыс.»
_RE_COUNT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(k|к|тыс\.?)?", re.I)


def parse_count(text: str) -> int:
    """'2.8K' -> 2800, '161' -> 161, '' -> 0."""
    m = _RE_COUNT.search(text or "")
    if not m:
        return 0
    n = float(m.group(1).replace(",", "."))
    return int(n * 1000) if m.group(2) else int(n)


# Признаки трансграничного продавца по названию (WB): «Находки из Китая», «ОАЭшка», «AE Dubai Freezone»
_RE_CROSS_BORDER_SELLER = re.compile(r"кита[йя]|china|дуба[йя]|dubai|оаэ|uae|freezone|hong ?kong|гонконг|"
                                     r"из-за рубежа|зарубеж", re.I)
_RE_OFFICIAL_SELLER = re.compile(r"официальн|official|россия магазин", re.I)


def seller_is_cross_border(name: str) -> bool:
    return bool(_RE_CROSS_BORDER_SELLER.search(name or ""))


def seller_is_official(name: str) -> bool:
    return bool(_RE_OFFICIAL_SELLER.search(name or "")) and not seller_is_cross_border(name)


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
