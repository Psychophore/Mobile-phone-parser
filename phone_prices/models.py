"""Список моделей для проверки и целевые конфигурации.

Источник списка: документ «Handoff: подбор смартфона до 15 тыс.».
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Model:
    """Модель из списка или свободный запрос (см. `phone_prices/query.py`).

    Поля после `note` задают правила отбора карточек (`sources/common.py::accept`): у моделей из
    списка они остаются по умолчанию, свободный запрос из веб-интерфейса меняет их под себя.
    """

    name: str                 # каноническое имя, как в отчёте
    ram: int                  # целевая ОЗУ, ГБ (0 — конфигурация не важна)
    rom: int                  # целевой накопитель, ГБ (0 — конфигурация не важна)
    query: str = ""           # поисковый запрос в магазине (по умолчанию имя)
    aliases: tuple[str, ...] = field(default_factory=tuple)  # как ещё пишут название
    note: str = ""
    match: str = "phrase"     # "phrase" — слова названия подряд; "words" — все слова запроса в любом порядке
    drop_variants: bool = True  # в режиме "words": отбрасывать модификации (Pro, Plus, Max), если их нет в запросе
    skip_accessories: bool = True   # отсеивать чехлы, стёкла, зарядки
    skip_5g: bool = True            # отсеивать 5G-версии
    min_price: int = 3000           # дешевле — точно не тот товар

    @property
    def search_query(self) -> str:
        return self.query or self.name

    @property
    def config(self) -> str:
        return f"{self.ram}/{self.rom}" if self.ram and self.rom else ""

    @property
    def search_text(self) -> str:
        """Строка для поля поиска магазина: запрос плюс конфигурация, если она задана."""
        return f"{self.search_query} {self.config}".strip()

    def matches_title(self, title: str) -> bool:
        """Название карточки относится к этой модели."""
        words = _norm(title).split()
        if self.match == "words":
            return self._matches_words(words)
        return self._matches_phrase(words)

    def _matches_phrase(self, words: list[str]) -> bool:
        """Слова названия идут в карточке подряд (Redmi 15C и Redmi Note 15 — не Redmi 15,
        realme C75 — не C67), а слово сразу после них не суффикс другой модификации
        (M7 Pro, Spark 40 Pro Plus)."""
        for cand in (self.name, *self.aliases):
            tokens = _norm(cand).split()
            n = len(tokens)
            for i in range(len(words) - n + 1):
                if words[i:i + n] == tokens and (i + n >= len(words) or words[i + n] not in _VARIANT_SUFFIXES):
                    return True
        return False

    def _matches_words(self, words: list[str]) -> bool:
        """Все слова запроса есть в названии в любом порядке («чайник электрический» —
        «Чайник Bosch электрический 1.7 л»). Слова с цифрами сверяются целиком (M7 — не M70),
        остальные — по началу слова, чтобы падежи не мешали («чайник» — «чайника»)."""
        tokens = _norm(self.search_query).split()
        if not tokens:
            return False
        if not all(_word_hit(t, words) for t in tokens):
            return False
        if self.drop_variants and any(w in _VARIANT_SUFFIXES and w not in tokens for w in words):
            return False
        return True


# Слова, которые сразу после названия означают другую модель (POCO M7 Pro, Tecno Spark 40 Pro Plus)
_VARIANT_SUFFIXES = frozenset({"pro", "plus", "max", "ultra", "lite", "neo", "mini", "prime", "power", "play"})


def _word_hit(token: str, words: list[str]) -> bool:
    if any(ch.isdigit() for ch in token):
        return token in words
    return any(w.startswith(token) for w in words)


def _norm(s: str) -> str:
    s = s.lower().replace("ё", "е")
    s = re.sub(r"(?<=[a-zа-я])\+", " plus", s)   # «Pro+» → «pro plus»; «8+256» не трогаем
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
