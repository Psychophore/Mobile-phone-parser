"""Диалог подбора, не привязанный к мессенджеру.

Транспорт (Telegram, консоль, позже Max или сайт) передаёт сюда текст или нажатую кнопку
и отправляет обратно список ответов `Reply`. Текст ответов — HTML в разметке Telegram
(<b>, <i>, <a>); консоль снимает теги сама.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from html import escape

from .affiliate import Affiliate
from .catalog import Phone
from .events import EventLog
from .prices import PriceStore
from .recommend import (PRIORITY_BATTERY, PRIORITY_PRICE, PRIORITY_SCREEN, Needs, Pick,
                        cheapest_known, recommend)

BUDGETS = [10_000, 15_000, 20_000, 25_000]
MIN_BUDGET, MAX_BUDGET = 3_000, 300_000
STALE_DAYS = 3   # старше — предупреждать, что цены могли измениться


@dataclass(frozen=True)
class Button:
    text: str
    data: str = ""    # для кнопки-ответа
    url: str = ""     # для кнопки-ссылки


@dataclass
class Reply:
    text: str
    buttons: list[list[Button]] = field(default_factory=list)


@dataclass
class State:
    step: str = "budget"
    budget: int = 0
    nfc: bool = False


def rub(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " ₽"


def plural(n: int, one: str, few: str, many: str) -> str:
    """plural(1, «оценка», «оценки», «оценок») -> «оценка»; 3 -> «оценки»; 11 и 25 -> «оценок»."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


_RE_BUDGET = re.compile(r"(\d[\d\s.,]*)\s*(к|k|тыс|т\.?)?", re.I)


def parse_budget(text: str) -> int | None:
    """«15000», «15 000», «15к», «до 15 тыс.», «12,5 тыс» -> рубли; вне разумных границ — None."""
    m = _RE_BUDGET.search(text or "")
    if not m:
        return None
    raw = m.group(1).strip().replace(" ", "")
    thousands = bool(m.group(2))
    if thousands:
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            return None
        n = int(value * 1000)
    else:
        digits = re.sub(r"\D", "", raw)
        if not digits:
            return None
        n = int(digits)
        if n < 1000:          # «15» — почти наверняка тысячи
            n *= 1000
    return n if MIN_BUDGET <= n <= MAX_BUDGET else None


class Advisor:
    def __init__(self, catalog: list[Phone], prices: PriceStore, affiliate: Affiliate | None = None,
                 events: EventLog | None = None, now=None):
        self.catalog = catalog
        self.prices = prices
        self.affiliate = affiliate or Affiliate()
        self.events = events or EventLog(None)
        self.states: dict[str, State] = {}
        self._now = now or (lambda: datetime.now().astimezone())

    # -- вход --------------------------------------------------------------------
    def handle_text(self, chat_id: int | str, text: str) -> list[Reply]:
        key = str(chat_id)
        t = (text or "").strip()
        if t.startswith("/start") or t.startswith("/restart") or key not in self.states:
            return self._start(key)
        if t.startswith("/help"):
            return [self._help()]
        st = self.states[key]
        if st.step == "budget":
            budget = parse_budget(t)
            if budget is None:
                return [self._ask_budget("Не понял сумму. Напишите число, например <b>15000</b>, или выберите:")]
            return self._set_budget(key, budget)
        if st.step == "nfc":
            return [self._ask_nfc("Выберите вариант кнопкой ниже:")]
        if st.step == "priority":
            return [self._ask_priority("Выберите вариант кнопкой ниже:")]
        return self._start(key)

    def handle_button(self, chat_id: int | str, data: str) -> list[Reply]:
        key = str(chat_id)
        if data == "restart" or key not in self.states:
            return self._start(key)
        st = self.states[key]
        kind, _, value = data.partition(":")
        if kind == "b" and value.isdigit():
            return self._set_budget(key, int(value))
        if kind == "n" and st.step in ("nfc", "priority"):
            st.nfc = value == "1"
            st.step = "priority"
            self.events.write("answer", key, question="nfc", value=st.nfc)
            return [self._ask_priority()]
        if kind == "p" and st.step == "priority" and value in (PRIORITY_BATTERY, PRIORITY_SCREEN, PRIORITY_PRICE):
            self.events.write("answer", key, question="priority", value=value)
            return self._result(key, Needs(st.budget, st.nfc, value))
        return [self._current_question(st)]

    # -- шаги --------------------------------------------------------------------
    def _start(self, key: str) -> list[Reply]:
        self.states[key] = State()
        self.events.write("start", key)
        return [self._ask_budget(
            "Привет! Помогу выбрать смартфон и найти, где он сейчас дешевле: Яндекс Маркет, Wildberries, Ozon, DNS.\n\n"
            "Три коротких вопроса. Первый: <b>сколько готовы потратить?</b> Выберите или напишите сумму.")]

    def _set_budget(self, key: str, budget: int) -> list[Reply]:
        st = self.states[key]
        st.budget, st.step = budget, "nfc"
        self.events.write("answer", key, question="budget", value=budget)
        return [self._ask_nfc(f"Бюджет до {rub(budget)}.\n\nБудете <b>платить телефоном</b> в магазинах?")]

    def _current_question(self, st: State) -> Reply:
        return {"budget": self._ask_budget, "nfc": self._ask_nfc, "priority": self._ask_priority}.get(
            st.step, self._ask_budget)()

    def _ask_budget(self, text: str = "Сколько готовы потратить?") -> Reply:
        row = [Button(f"до {b // 1000} тыс.", data=f"b:{b}") for b in BUDGETS]
        return Reply(text, [row[:2], row[2:]])

    def _ask_nfc(self, text: str = "Будете платить телефоном в магазинах?") -> Reply:
        return Reply(text, [[Button("Да, нужен NFC", data="n:1"), Button("Нет", data="n:0")]])

    def _ask_priority(self, text: str = "И последнее: <b>что важнее?</b>") -> Reply:
        return Reply(text, [[Button("Батарея подольше", data=f"p:{PRIORITY_BATTERY}")],
                            [Button("Экран получше", data=f"p:{PRIORITY_SCREEN}")],
                            [Button("Подешевле при прочих равных", data=f"p:{PRIORITY_PRICE}")]])

    def _help(self) -> Reply:
        return Reply("Я подбираю смартфон по трём вопросам и показываю самую низкую цену у проверенных продавцов.\n"
                     "/start — начать заново.", [[Button("Начать подбор", data="restart")]])

    # -- результат ---------------------------------------------------------------
    def _subid(self, key: str) -> str:
        return hashlib.sha256(f"{self.events.user(key)}:{time.time_ns()}".encode()).hexdigest()[:10]

    def _result(self, key: str, needs: Needs) -> list[Reply]:
        self.states[key].step = "done"
        picks = recommend(self.catalog, self.prices, needs)
        subid = self._subid(key)
        self.events.write("result", key, subid=subid, budget=needs.budget, nfc=needs.nfc, priority=needs.priority,
                          models=[p.phone.model for p in picks], prices=[p.offer.price_rub for p in picks],
                          shops=[p.offer.shop for p in picks])
        again = [Button("Подобрать заново", data="restart")]
        if not picks:
            low = cheapest_known(self.catalog, self.prices)
            hint = (f" Самый дешёвый подходящий вариант сейчас — {escape(low.model)} за {rub(low.price_rub)}."
                    if low else "")
            return [Reply(f"До {rub(needs.budget)} с такими условиями сейчас ничего надёжного не нашлось.{hint}\n\n"
                          "Попробуйте поднять бюджет:", self._ask_budget().buttons + [again])]
        blocks = [self._pick_text(i, p) for i, p in enumerate(picks, 1)]
        buttons = [[Button(f"{p.offer.shop_short} · {rub(p.offer.price_rub)} · {p.phone.model}",
                           url=self.affiliate.wrap(p.offer.url, p.offer.shop, subid))] for p in picks]
        head = f"Вот что советую до {rub(needs.budget)}:"
        text = "\n\n".join([head, *blocks, self._footer(picks)])
        return [Reply(text, buttons + [again])]

    def _pick_text(self, i: int, p: Pick) -> str:
        o = p.offer
        rating = (f" {o.rating:.1f}".replace(".", ",") + f" ★ ({o.reviews} {plural(o.reviews, 'оценка', 'оценки', 'оценок')})"
                  if o.rating else "")
        version = {"EAC": "официальная поставка (Ростест)", "Global": "глобальная версия"}.get(o.version, "")
        lines = [f"<b>{i}. {escape(p.phone.model)} {p.phone.config}</b> — {rub(o.price_rub)} на {o.shop_name}"
                 + (" <i>(чуть дороже бюджета)</i>" if p.over_budget else "")]
        if p.why:
            lines.append("Почему: " + "; ".join(escape(w) for w in p.why) + ".")
        if p.caveats:
            lines.append("Учтите: " + "; ".join(escape(c) for c in p.caveats) + ".")
        if o.seller:
            lines.append(f"Продавец: {escape(o.seller)}{rating}" + (f", {version}" if version else "") + ".")
        elif rating or version:
            lines.append(("Рейтинг карточки" + rating if rating else version[:1].upper() + version[1:])
                         + (f", {version}" if rating and version else "") + ".")
        return "\n".join(lines)

    def _footer(self, picks: list[Pick]) -> str:
        oldest = min(p.offer.fetched_at for p in picks).astimezone(self._now().tzinfo)
        age_days = (self._now() - oldest).total_seconds() / 86400
        parts = [f"Цены на {oldest:%d.%m}, только продавцы с хорошим рейтингом. Перед покупкой сверьте цену в магазине."]
        if age_days > STALE_DAYS:
            parts.append("⚠️ Цены давно не обновлялись и могли измениться.")
        if self.affiliate.label and any(self.affiliate.is_partner(p.offer.shop) for p in picks):
            parts.append(escape(self.affiliate.label))
        return "<i>" + " ".join(parts) + "</i>"
