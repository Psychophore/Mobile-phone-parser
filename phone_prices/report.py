"""CSV и консольная сводка."""
from __future__ import annotations

import csv
from pathlib import Path

from .models import BUDGET_HIGH, BUDGET_LOW, Model
from .offers import CSV_FIELDS, Offer


def write_csv(offers: list[Offer], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for o in sorted(offers, key=lambda o: (o.model, not o.trusted, o.reviews == 0, o.price_rub)):
            w.writerow(o.as_row())


def budget_tag(price: int | None) -> str:
    if price is None:
        return "нет данных"
    if price <= BUDGET_LOW:
        return "до 10 тыс."
    if price <= BUDGET_HIGH:
        return "до 15 тыс."
    return "вне бюджета"


def pick(offers: list[Offer]) -> Offer | None:
    """Лучшее предложение: сначала карточки с оценками (самая дешёвая), без оценок — только если других нет."""
    rated = [o for o in offers if o.reviews > 0]
    pool = rated or offers
    return min(pool, key=lambda o: o.price_rub, default=None)


def summary(offers: list[Offer], models: list[Model]) -> str:
    rows = []
    for m in models:
        mine = [o for o in offers if o.model == m.name]
        eac = pick([o for o in mine if o.version == "EAC"])
        glob = pick([o for o in mine if o.version == "Global"])
        unk = pick([o for o in mine if o.version == "?"])
        best = pick(mine)
        rows.append((best.price_rub if best else 10**9, m, eac, glob, unk, len(mine)))
    rows.sort(key=lambda r: r[0])

    def fmt(o: Offer | None) -> str:
        if not o:
            return "       —"
        mark = "*" if o.reviews == 0 else " "   # * — у карточки нет оценок
        return f"{o.price_rub:>7,}".replace(",", " ") + mark

    lines = [f"{'Модель':<26} {'конф.':<6} {'Ростест':>8} {'Global':>8} {'без метки':>10}  {'карт.':>5}  вердикт",
             "-" * 86]
    for best, m, eac, glob, unk, n in rows:
        lines.append(f"{m.name:<26} {m.config:<6} {fmt(eac)} {fmt(glob)} {fmt(unk):>10}  {n:>5}  "
                     f"{budget_tag(None if best == 10**9 else best)}")
    lines.append("* — у карточки нет оценок")
    return "\n".join(lines)
