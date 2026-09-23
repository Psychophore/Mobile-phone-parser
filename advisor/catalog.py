"""Каталог характеристик и уровни «хорошо / терпимо / отсекать» из документа с критериями.

Каталог хранится в advisor/data/<категория>.json. Имена моделей совпадают с `phone_prices.models.MODELS`,
поэтому цены из CSV парсера сопоставляются с каталогом по полю model.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from phone_prices.models import MODELS

DATA_DIR = Path(__file__).resolve().parent / "data"

GOOD, OK, CUT = "good", "ok", "cut"

# Процессоры: «хорошо» — Helio G99/G100, Snapdragon 685 и новее; «терпимо» — Helio G81/G85,
# Snapdragon 6s; «отсекать» — Unisoc, Helio G25/G35.
_CHIP_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"unisoc|helio g(25|35|36|37)\b", re.I), CUT),
    (re.compile(r"helio g(99|100)|snapdragon (685|6 gen|7)", re.I), GOOD),
    (re.compile(r"helio g(81|85|88|91)|snapdragon 6s", re.I), OK),
]


def chip_tier(chip: str | None) -> str | None:
    """Уровень процессора или None, если процессор неизвестен или не описан правилами."""
    if not chip:
        return None
    for rx, tier in _CHIP_RULES:
        if rx.search(chip):
            return tier
    return None


@dataclass(frozen=True)
class Phone:
    model: str
    ram: int
    rom: int
    chip: str | None
    screen_type: str | None
    resolution: str | None
    refresh_hz: int | None
    battery_mah: int | None
    nfc: bool | None

    @property
    def config(self) -> str:
        return f"{self.ram}/{self.rom}"

    @property
    def chip_tier(self) -> str | None:
        return chip_tier(self.chip)


def load_catalog(category: str = "smartphones") -> list[Phone]:
    """Каталог категории. Целевая конфигурация берётся из списка моделей парсера."""
    data = json.loads((DATA_DIR / f"{category}.json").read_text(encoding="utf-8"))
    configs = {m.name: (m.ram, m.rom) for m in MODELS}
    phones = []
    for it in data["items"]:
        if it["model"] not in configs:
            raise ValueError(f"Модели {it['model']!r} нет в phone_prices.models.MODELS")
        ram, rom = configs[it["model"]]
        phones.append(Phone(model=it["model"], ram=ram, rom=rom, chip=it.get("chip"),
                            screen_type=it.get("screen_type"), resolution=it.get("resolution"),
                            refresh_hz=it.get("refresh_hz"), battery_mah=it.get("battery_mah"),
                            nfc=it.get("nfc")))
    return phones
