"""Подбор моделей по правилам из документа с критериями.

Выбор делает код, а не нейросеть: так ответы предсказуемы, объяснимы и бесплатны.
Каждое правило добавляет баллы и строку «почему» или «учтите», которую видит человек.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import CUT, GOOD, OK, Phone
from .prices import PriceOffer, PriceStore

# Что важнее человеку
PRIORITY_BATTERY = "battery"
PRIORITY_SCREEN = "screen"
PRIORITY_PRICE = "price"

OVER_BUDGET_TOLERANCE = 0.10   # «чуть дороже бюджета» — не больше чем на 10 %


@dataclass(frozen=True)
class Needs:
    budget: int                       # максимум, руб.
    nfc: bool = False                 # будет платить телефоном
    priority: str = PRIORITY_PRICE


@dataclass
class Pick:
    phone: Phone
    offer: PriceOffer
    score: float
    why: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    over_budget: bool = False


def _mah(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " мАч"


def _weights(priority: str) -> tuple[float, float]:
    """Веса батареи и экрана: то, что человек назвал важным, весит вчетверо больше второго."""
    if priority == PRIORITY_BATTERY:
        return 2.0, 0.5
    if priority == PRIORITY_SCREEN:
        return 0.5, 2.0
    return 1.0, 1.0


def evaluate(phone: Phone, needs: Needs) -> tuple[float, list[str], list[str]] | None:
    """Баллы, доводы и оговорки; None — модель не подходит совсем."""
    why: list[str] = []
    caveats: list[str] = []
    score = 0.0

    tier = phone.chip_tier
    if tier == CUT:
        return None
    if tier == GOOD:
        score += 3
        why.append(f"{phone.chip}: мессенджеры и видео без подтормаживаний")
    elif tier == OK:
        score += 1
        why.append(f"{phone.chip}: для мессенджеров и видео хватит")
        caveats.append("процессор слабее, через пару лет может подтормаживать")
    else:
        caveats.append("процессор не проверен")

    if phone.ram >= 6:
        score += 2
    else:
        caveats.append(f"{phone.ram} ГБ памяти — компромисс ради цены")

    battery_w, screen_w = _weights(needs.priority)
    if phone.battery_mah is None:
        caveats.append("ёмкость батареи не подтверждена")
    elif phone.battery_mah < 5000:
        return None
    elif phone.battery_mah >= 6000:
        score += (3 if phone.battery_mah >= 7000 else 2) * battery_w
        why.append(f"батарея {_mah(phone.battery_mah)}: день-два без зарядки")
    else:
        score += 1 * battery_w
        why.append(f"батарея {_mah(phone.battery_mah)}")

    screen_bits = []
    if phone.screen_type == "AMOLED":
        score += 1 * screen_w
        screen_bits.append("AMOLED")
    elif phone.screen_type:
        screen_bits.append(phone.screen_type)
    if phone.resolution == "FHD+":
        score += 1 * screen_w
        screen_bits.append("FHD+")
    elif phone.resolution == "HD+":
        score -= 1 * screen_w
        caveats.append("экран HD+: картинка мягче, чем у FHD+")
    if phone.refresh_hz and phone.refresh_hz >= 90:
        score += 0.5 * screen_w
        screen_bits.append(f"{phone.refresh_hz} Гц")
    if screen_bits and (phone.screen_type == "AMOLED" or phone.resolution == "FHD+"):
        why.append("экран " + ", ".join(screen_bits))

    if needs.nfc:
        if phone.nfc is False:
            return None
        if phone.nfc is None:
            score -= 1
            caveats.append("NFC для оплаты не подтверждён — проверьте в карточке")
        else:
            why.append("есть NFC для оплаты телефоном")
    elif phone.nfc is False:
        caveats.append("нет NFC: платить телефоном не получится")

    return score, why, caveats


def recommend(catalog: list[Phone], prices: PriceStore, needs: Needs, limit: int = 3) -> list[Pick]:
    """До `limit` вариантов в бюджете; если их меньше — добавить «чуть дороже бюджета»."""
    within: list[Pick] = []
    above: list[Pick] = []
    for phone in catalog:
        offer = prices.best(phone.model)
        if not offer:
            continue   # без живой цены не советуем
        res = evaluate(phone, needs)
        if res is None:
            continue
        score, why, caveats = res
        if needs.priority == PRIORITY_PRICE:
            # дешевле при прочих равных — лучше: 1 балл за каждые 20 % бюджета экономии
            score += (needs.budget - offer.price_rub) / needs.budget * 5
        pick = Pick(phone, offer, score, why, caveats)
        if offer.price_rub <= needs.budget:
            within.append(pick)
        elif offer.price_rub <= needs.budget * (1 + OVER_BUDGET_TOLERANCE):
            pick.over_budget = True
            above.append(pick)
    order = lambda p: (-p.score, p.offer.price_rub)
    out = sorted(within, key=order)[:limit]
    if len(out) < limit:
        out += sorted(above, key=order)[:limit - len(out)]
    return out


def cheapest_known(catalog: list[Phone], prices: PriceStore) -> PriceOffer | None:
    """Самая низкая известная цена по каталогу — подсказка, если в бюджет ничего не попало."""
    offers = [o for o in (prices.best(p.model) for p in catalog) if o]
    return min(offers, key=lambda o: o.price_rub, default=None)
