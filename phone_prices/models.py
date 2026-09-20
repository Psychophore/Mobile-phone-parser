"""Список моделей для проверки и целевые конфигурации.

Источник списка: документ «Handoff: подбор смартфона до 15 тыс.».
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Model:
    name: str                 # каноническое имя, как в отчёте
    ram: int                  # целевая ОЗУ, ГБ
    rom: int                  # целевой накопитель, ГБ
    query: str = ""           # поисковый запрос в магазине (по умолчанию имя)
    aliases: tuple[str, ...] = field(default_factory=tuple)  # как ещё пишут название
    note: str = ""

    @property
    def search_query(self) -> str:
        return self.query or self.name

    @property
    def config(self) -> str:
        return f"{self.ram}/{self.rom}"

    def matches_title(self, title: str) -> bool:
        """Название карточки относится к этой модели (без учёта регистра и лишних слов)."""
        t = _norm(title)
        for cand in (self.name, *self.aliases):
            tokens = _norm(cand).split()
            if all(tok in t for tok in tokens):
                return True
        return False


def _norm(s: str) -> str:
    s = s.lower().replace("ё", "е")
    for ch in "()[],.;:+«»\"'":
        s = s.replace(ch, " ")
    return " ".join(s.split())


MODELS: list[Model] = [
    Model("Samsung Galaxy A17 4G", 6, 128, aliases=("Galaxy A17", "Samsung A17")),
    Model("POCO M7", 6, 128, aliases=("Xiaomi POCO M7", "Poco M7 4G")),
    Model("Xiaomi Redmi 15", 6, 128, aliases=("Redmi 15 4G",)),
    Model("realme C67", 6, 128, aliases=("Realme C67 4G",)),
    Model("Honor X8c", 6, 128, aliases=("HONOR X8c",)),
    Model("OPPO A5 4G", 6, 128, aliases=("OPPO A5",)),
    Model("Tecno Spark 40 Pro", 6, 128, aliases=("TECNO Spark 40 Pro",)),
    Model("Tecno Pova 6 Neo", 6, 128, aliases=("TECNO POVA 6 Neo",)),
    Model("Honor X7d", 6, 128, aliases=("HONOR X7d",), note="проверен вручную, ~17 тыс."),
    Model("Infinix Hot 50i", 4, 128, aliases=("Infinix HOT 50i",)),
    Model("Samsung Galaxy A07", 4, 128, aliases=("Galaxy A07", "Samsung A07")),
    Model("Xiaomi Redmi 14C", 4, 128, aliases=("Redmi 14C",)),
    Model("Xiaomi Redmi Note 14 4G", 6, 128, aliases=("Redmi Note 14", "Redmi Note 14 4G"),
          note="контроль: ожидается 22–28 тыс."),
]

BUDGET_LOW = 10_000
BUDGET_HIGH = 15_000


def find_models(names: list[str] | None) -> list[Model]:
    """Отобрать модели по подстроке имени; пустой список — все."""
    if not names:
        return list(MODELS)
    out: list[Model] = []
    for n in names:
        key = _norm(n)
        hits = [m for m in MODELS if key in _norm(m.name) or any(key in _norm(a) for a in m.aliases)]
        if not hits:
            raise SystemExit(f"Модель не найдена в списке: {n!r}")
        for m in hits:
            if m not in out:
                out.append(m)
    return out
