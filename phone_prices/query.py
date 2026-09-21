"""Свободный поиск: Model, собранный из строки с ключевыми словами.

Нужен веб-интерфейсу (`phone_prices/webui.py`) и ключу `--query`: в отличие от моделей из
`MODELS`, запрос пишет владелец, поэтому название сверяется мягче — все слова запроса должны
быть в названии карточки, но не обязательно подряд (иначе «чайник электрический» не найдёт
«Чайник Bosch электрический»). Конфигурация «6/128» из строки запроса уходит в фильтр
и в поисковую строку магазина.
"""
from __future__ import annotations

from .models import Model
from .offers import split_config

MIN_PRICE = 500   # ниже — почти всегда не тот товар; у моделей из списка порог 3000


def build_query(text: str, *, ram: int = 0, rom: int = 0, accessories: bool = False,
                allow_5g: bool = True, drop_variants: bool = True, min_price: int = MIN_PRICE,
                in_category: bool = False) -> Model:
    """Собрать Model из ключевых слов.

    ram/rom — целевая конфигурация; если её не задали, берётся из самого запроса («POCO M7 6/128»).
    accessories — не отсеивать чехлы и стёкла, allow_5g — не отсеивать 5G,
    drop_variants — отбрасывать модификации (Pro, Plus, Max), которых нет в запросе,
    in_category — искать только в категории смартфонов (иначе по всему магазину: «чайник»
    в категории смартфонов выдаёт смартфоны).
    """
    text = " ".join((text or "").split())
    if not text:
        raise ValueError("пустой запрос")
    words, cfg = split_config(text)
    if not (ram and rom) and cfg != "?":
        ram, rom = (int(x) for x in cfg.split("/"))
    if not words:                      # запрос состоял из одной конфигурации
        words, ram, rom = text, 0, 0
    return Model(
        name=text,                     # как показать в таблице и в колонке model
        ram=ram, rom=rom,
        query=words,                   # что искать в магазине (без конфигурации: её добавит search_text)
        match="words",
        drop_variants=drop_variants,
        skip_accessories=not accessories,
        skip_5g=not allow_5g,
        min_price=max(0, int(min_price)),
        in_category=in_category,
    )
