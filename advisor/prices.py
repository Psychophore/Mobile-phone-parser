"""Цены из снимков парсера (CSV `parse_prices.py`).

Бот не ходит в магазины сам: антибот Ozon, DNS и WB пускает только настоящий браузер с российского
адреса. Парсер запускается там, где магазины доступны, и кладёт CSV в каталог снимков; бот читает
последние данные и честно показывает их дату.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SHOP_NAMES = {
    "market.yandex.ru": "Яндекс Маркете",
    "wildberries.ru": "Wildberries",
    "ozon.ru": "Ozon",
    "dns-shop.ru": "DNS",
}

SHOP_SHORT = {"market.yandex.ru": "Маркет", "wildberries.ru": "WB", "ozon.ru": "Ozon", "dns-shop.ru": "DNS"}


@dataclass(frozen=True)
class PriceOffer:
    model: str
    config: str
    shop: str
    price_rub: int
    version: str
    seller: str
    rating: float | None
    reviews: int
    url: str
    fetched_at: datetime

    @property
    def shop_name(self) -> str:
        return SHOP_NAMES.get(self.shop, self.shop)

    @property
    def shop_short(self) -> str:
        return SHOP_SHORT.get(self.shop, self.shop)


def _parse_time(s: str) -> datetime:
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.fromtimestamp(0, timezone.utc)


def _row_offer(row: dict) -> PriceOffer | None:
    try:
        price = int(row["price_rub"])
    except (KeyError, ValueError):
        return None
    if str(row.get("trusted", "1")).strip() not in ("1", "True", "true"):
        return None   # бот советует только проверенных продавцов (правило владельца)
    rating = row.get("rating") or ""
    try:
        rating_f = float(rating) if rating else None
    except ValueError:
        rating_f = None
    try:
        reviews = int(float(row.get("reviews") or 0))
    except ValueError:
        reviews = 0
    return PriceOffer(model=row["model"], config=row.get("config", ""), shop=row.get("shop", ""),
                      price_rub=price, version=row.get("version", "?"), seller=row.get("seller", ""),
                      rating=rating_f, reviews=reviews, url=row.get("url", ""),
                      fetched_at=_parse_time(row.get("fetched_at", "")))


class PriceStore:
    """Лучшие предложения по моделям из одного или нескольких CSV.

    Если одну и ту же карточку (url) собирали несколько раз, берётся последний снимок.
    Предложения старше самого свежего по модели больше чем на `window_days` отбрасываются:
    старые цены не должны перебивать новые.
    """

    def __init__(self, offers: list[PriceOffer], window_days: float = 3.0):
        latest: dict[tuple[str, str], PriceOffer] = {}
        for o in offers:
            key = (o.model, o.url or f"{o.shop}:{o.price_rub}")
            if key not in latest or o.fetched_at > latest[key].fetched_at:
                latest[key] = o
        by_model: dict[str, list[PriceOffer]] = {}
        for o in latest.values():
            by_model.setdefault(o.model, []).append(o)
        self._by_model: dict[str, list[PriceOffer]] = {}
        for model, lst in by_model.items():
            newest = max(o.fetched_at for o in lst)
            self._by_model[model] = [o for o in lst if (newest - o.fetched_at).total_seconds() <= window_days * 86400]

    @classmethod
    def load(cls, paths: list[Path], window_days: float = 3.0) -> "PriceStore":
        """Загрузить CSV-файлы; каталог — все *.csv внутри."""
        files: list[Path] = []
        for p in paths:
            files.extend(sorted(p.glob("*.csv")) if p.is_dir() else [p])
        offers: list[PriceOffer] = []
        for f in files:
            with f.open(encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    o = _row_offer(row)
                    if o:
                        offers.append(o)
        return cls(offers, window_days)

    def offers(self, model: str) -> list[PriceOffer]:
        return list(self._by_model.get(model, []))

    def best(self, model: str) -> PriceOffer | None:
        """Самое дешёвое предложение; карточки с оценками важнее карточек без оценок."""
        lst = self.offers(model)
        rated = [o for o in lst if o.reviews > 0]
        return min(rated or lst, key=lambda o: o.price_rub, default=None)

    def newest(self) -> datetime | None:
        times = [o.fetched_at for lst in self._by_model.values() for o in lst]
        return max(times, default=None)

    def models(self) -> list[str]:
        return sorted(self._by_model)
