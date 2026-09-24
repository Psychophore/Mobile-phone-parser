"""Тесты консультанта: каталог, цены из CSV, правила подбора, диалог, партнёрские ссылки, Telegram."""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advisor.affiliate import Affiliate
from advisor.catalog import CUT, GOOD, OK, Phone, chip_tier, load_catalog
from advisor.dialog import Advisor, parse_budget
from advisor.events import EventLog, read_events, stats
from advisor.prices import PriceStore
from advisor.recommend import PRIORITY_BATTERY, PRIORITY_PRICE, PRIORITY_SCREEN, Needs, evaluate, recommend
from advisor.telegram import TelegramClient, handle_update, markup
from phone_prices.offers import CSV_FIELDS

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def write_prices(path: Path, rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            base = {k: "" for k in CSV_FIELDS}
            base.update({"config": "6/128", "version": "?", "seller": "Магазин", "rating": "4.8", "reviews": "50",
                         "trusted": "1", "cross_border": "0", "title": r["model"],
                         "url": f"https://market.yandex.ru/card/{r['model'].replace(' ', '-')}-{r['price_rub']}",
                         "fetched_at": "2026-09-23T08:00:00Z", "shop": "market.yandex.ru"})
            base.update({k: str(v) for k, v in r.items()})
            w.writerow(base)
    return path


def store(tmp_path, rows) -> PriceStore:
    return PriceStore.load([write_prices(tmp_path / "p.csv", rows)])


def test_catalog_matches_parser_models():
    phones = load_catalog()
    assert len(phones) == 13
    poco = next(p for p in phones if p.model == "POCO M7")
    assert poco.config == "6/128" and poco.battery_mah == 7000 and poco.nfc is False
    assert next(p for p in phones if p.model == "Samsung Galaxy A07").config == "4/128"


def test_chip_tiers_follow_criteria_table():
    assert chip_tier("Helio G99 Ultra") == GOOD
    assert chip_tier("Snapdragon 685") == GOOD
    assert chip_tier("Helio G100") == GOOD
    assert chip_tier("Helio G81 Ultra") == OK
    assert chip_tier("Snapdragon 6s Gen 1") == OK
    assert chip_tier("Unisoc T606") == CUT
    assert chip_tier("Helio G35") == CUT
    assert chip_tier(None) is None


def test_price_store_keeps_trusted_latest_and_prefers_rated(tmp_path):
    s = store(tmp_path, [
        {"model": "POCO M7", "price_rub": 12000, "trusted": "0"},                        # непроверенный
        {"model": "POCO M7", "price_rub": 13000, "reviews": "0", "rating": ""},           # без оценок
        {"model": "POCO M7", "price_rub": 13766, "shop": "wildberries.ru"},
        {"model": "POCO M7", "price_rub": 11000, "fetched_at": "2026-09-10T08:00:00Z",    # устаревший снимок
         "url": "https://old"},
    ])
    best = s.best("POCO M7")
    assert best.price_rub == 13766 and best.shop_name == "Wildberries"
    assert [o.price_rub for o in s.offers("POCO M7")] and all(o.price_rub != 12000 for o in s.offers("POCO M7"))
    assert all(o.price_rub != 11000 for o in s.offers("POCO M7"))


def test_price_store_same_card_takes_newest_snapshot(tmp_path):
    a = write_prices(tmp_path / "a.csv", [{"model": "POCO M7", "price_rub": 14000, "url": "https://x/1",
                                            "fetched_at": "2026-09-22T08:00:00Z"}])
    b = write_prices(tmp_path / "b.csv", [{"model": "POCO M7", "price_rub": 13500, "url": "https://x/1",
                                            "fetched_at": "2026-09-23T08:00:00Z"}])
    assert PriceStore.load([tmp_path]).best("POCO M7").price_rub == 13500
    assert PriceStore.load([a, b]).best("POCO M7").price_rub == 13500


def phone(**kw) -> Phone:
    base = dict(model="X", ram=6, rom=128, chip="Helio G99", screen_type="IPS", resolution="FHD+",
                refresh_hz=90, battery_mah=5000, nfc=True)
    base.update(kw)
    return Phone(**base)


def test_evaluate_hard_filters():
    assert evaluate(phone(chip="Unisoc T606"), Needs(15000)) is None
    assert evaluate(phone(battery_mah=4500), Needs(15000)) is None
    assert evaluate(phone(nfc=False), Needs(15000, nfc=True)) is None
    _, _, caveats = evaluate(phone(nfc=None), Needs(15000, nfc=True))
    assert any("NFC" in c for c in caveats)
    _, _, caveats = evaluate(phone(nfc=False), Needs(15000))
    assert any("нет NFC" in c for c in caveats)


def test_priority_changes_order():
    big_battery = phone(model="B", battery_mah=7000, screen_type="IPS", resolution="HD+", refresh_hz=None)
    nice_screen = phone(model="S", battery_mah=5000, screen_type="AMOLED", resolution="FHD+", refresh_hz=120)
    sb = lambda p, pr: evaluate(p, Needs(15000, priority=pr))[0]
    assert sb(big_battery, PRIORITY_BATTERY) > sb(nice_screen, PRIORITY_BATTERY)
    assert sb(nice_screen, PRIORITY_SCREEN) > sb(big_battery, PRIORITY_SCREEN)


def test_recommend_budget_and_over_budget(tmp_path):
    catalog = load_catalog()
    s = store(tmp_path, [
        {"model": "POCO M7", "price_rub": 13766},
        {"model": "Samsung Galaxy A07", "price_rub": 9752, "config": "4/128"},
        {"model": "Samsung Galaxy A17 4G", "price_rub": 16400},      # на 9 % дороже 15 000
        {"model": "Honor X7d", "price_rub": 28289},                  # вне бюджета совсем
    ])
    picks = recommend(catalog, s, Needs(15000, priority=PRIORITY_PRICE))
    names = [p.phone.model for p in picks]
    assert names[:2] == ["POCO M7", "Samsung Galaxy A07"] or set(names[:2]) == {"POCO M7", "Samsung Galaxy A07"}
    assert names[-1] == "Samsung Galaxy A17 4G" and picks[-1].over_budget
    assert "Honor X7d" not in names
    # NFC обязателен: POCO M7 (нет NFC) выпадает, A17 (есть NFC) остаётся
    nfc_names = [p.phone.model for p in recommend(catalog, s, Needs(15000, nfc=True))]
    assert "POCO M7" not in nfc_names and "Samsung Galaxy A17 4G" in nfc_names


def test_plural_and_shop_button(tmp_path):
    from advisor.dialog import plural
    assert [plural(n, "оценка", "оценки", "оценок") for n in (1, 3, 5, 11, 21, 112, 143)] == \
        ["оценка", "оценки", "оценок", "оценок", "оценка", "оценок", "оценки"]
    adv = advisor(tmp_path, [{"model": "POCO M7", "price_rub": 13000}])
    [res] = run_dialog(adv)
    assert res.buttons[0][0].text == "Маркет · 13 000 ₽ · POCO M7"
    assert "Продавец: Магазин 4,8 ★ (50 оценок)." in res.text
    adv = advisor(tmp_path, [{"model": "POCO M7", "price_rub": 13000, "seller": "", "rating": "4.9", "reviews": "803"}])
    [res] = run_dialog(adv)
    assert "Рейтинг карточки 4,9 ★ (803 оценки)." in res.text and "Продавец:" not in res.text
    assert "Ростест или глобальная версия — в карточке не указано" in res.text
    assert "объём памяти" not in res.text
    adv = advisor(tmp_path, [{"model": "POCO M7", "price_rub": 13000, "config": "?", "version": "EAC"}])
    [res] = run_dialog(adv)
    assert "убедитесь, что это 6/128" in res.text and "Ростест или глобальная" not in res.text


def test_parse_budget():
    assert parse_budget("15000") == 15000
    assert parse_budget("до 15 000 рублей") == 15000
    assert parse_budget("15к") == 15000
    assert parse_budget("12,5 тыс") == 12500
    assert parse_budget("15") == 15000
    assert parse_budget("много") is None
    assert parse_budget("100") is None or parse_budget("100") == 100000
    assert parse_budget("5000000") is None


def advisor(tmp_path, rows, affiliate=None, events=None):
    return Advisor(load_catalog(), store(tmp_path, rows), affiliate, events, now=lambda: NOW)


def run_dialog(adv, chat=1, budget="b:15000", nfc="n:0", prio="p:price"):
    adv.handle_text(chat, "/start")
    adv.handle_button(chat, budget)
    adv.handle_button(chat, nfc)
    return adv.handle_button(chat, prio)


def test_dialog_full_flow_with_affiliate_and_events(tmp_path):
    aff = Affiliate({"wildberries.ru": "https://go.example/?ulp={url_enc}&sub={subid}"}, "Реклама. erid: TEST")
    ev = EventLog(tmp_path / "events.jsonl", salt="s")
    adv = advisor(tmp_path, [{"model": "POCO M7", "price_rub": 13766, "shop": "wildberries.ru",
                              "seller": "Xiaomi Официальный Магазин", "rating": "4.9", "reviews": "161",
                              "url": "https://www.wildberries.ru/catalog/1/detail.aspx"},
                             {"model": "Samsung Galaxy A07", "price_rub": 9752, "config": "4/128"}], aff, ev)
    first = adv.handle_text(42, "привет")
    assert "сколько готовы потратить" in first[0].text
    assert "Бюджет до 12 000 ₽" in adv.handle_text(42, "12 тыс")[0].text
    adv.handle_button(42, "n:0")
    [res] = adv.handle_button(42, "p:price")
    assert "POCO M7" not in res.text   # 13 766 > 12 000 и больше чем на 10 %
    assert "Samsung Galaxy A07" in res.text
    [res] = run_dialog(adv, chat=42)
    assert "<b>1." in res.text and "POCO M7" in res.text and "Xiaomi Официальный Магазин 4,9 ★ (161 оценка)" in res.text
    assert "Реклама. erid: TEST" in res.text and "Цены на 23.09" in res.text
    urls = [b.url for row in res.buttons for b in row if b.url]
    wb = [u for u in urls if u.startswith("https://go.example/")]
    assert wb and "ulp=https%3A%2F%2Fwww.wildberries.ru%2Fcatalog%2F1%2Fdetail.aspx" in wb[0]
    assert any(u.startswith("https://market.yandex.ru/") for u in urls)   # у Маркета нет шаблона — прямая ссылка
    events = read_events(tmp_path / "events.jsonl")
    assert {e["event"] for e in events} >= {"start", "answer", "result"}
    assert all("42" not in json.dumps(e["user"]) or len(e["user"]) == 12 for e in events)
    assert "получили подбор: 1" in stats(events)


def test_dialog_empty_result_suggests_cheapest(tmp_path):
    adv = advisor(tmp_path, [{"model": "Honor X7d", "price_rub": 28289}])
    [res] = run_dialog(adv, budget="b:10000")
    assert "ничего надёжного не нашлось" in res.text and "Honor X7d за 28 289 ₽" in res.text
    assert any(b.data == "b:25000" for row in res.buttons for b in row)


def test_dialog_stale_prices_warning_and_html_escape(tmp_path):
    adv = advisor(tmp_path, [{"model": "POCO M7", "price_rub": 13000, "seller": "<Рога & копыта>",
                              "fetched_at": "2026-09-15T08:00:00Z"}])
    [res] = run_dialog(adv)
    assert "давно не обновлялись" in res.text
    assert "&lt;Рога &amp; копыта&gt;" in res.text


def test_dialog_text_on_button_step_repeats_question(tmp_path):
    adv = advisor(tmp_path, [])
    adv.handle_text(7, "/start")
    adv.handle_button(7, "b:15000")
    [r] = adv.handle_text(7, "да")
    assert any(b.data == "n:1" for row in r.buttons for b in row)


class FakeOpener:
    def __init__(self):
        self.calls = []

    def __call__(self, req, timeout=None):
        method = req.full_url.rsplit("/", 1)[1]
        self.calls.append((method, json.loads(req.data.decode("utf-8"))))
        body = json.dumps({"ok": True, "result": True}).encode()

        class R:
            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False

            def read(s):
                return body
        return R()


def test_telegram_update_handling(tmp_path):
    adv = advisor(tmp_path, [{"model": "POCO M7", "price_rub": 13000}])
    op = FakeOpener()
    client = TelegramClient("T", opener=op)
    handle_update(client, adv, {"update_id": 1, "message": {"chat": {"id": 5, "type": "private"}, "text": "/start"}})
    method, params = op.calls[-1]
    assert method == "sendMessage" and params["chat_id"] == 5 and params["parse_mode"] == "HTML"
    assert params["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "b:10000"
    handle_update(client, adv, {"update_id": 2, "callback_query": {"id": "q", "from": {"id": 5}, "data": "b:15000",
                                                                    "message": {"chat": {"id": 5}}}})
    assert [c[0] for c in op.calls[-2:]] == ["answerCallbackQuery", "sendMessage"]
    handle_update(client, adv, {"update_id": 3, "message": {"chat": {"id": -100, "type": "group"}, "text": "hi"}})
    assert len(op.calls) == 3   # в группах бот молчит


def test_markup_url_buttons():
    from advisor.dialog import Button, Reply
    m = markup(Reply("x", [[Button("Открыть", url="https://a")], [Button("Ещё", data="restart")]]))
    assert m == {"inline_keyboard": [[{"text": "Открыть", "url": "https://a"}],
                                     [{"text": "Ещё", "callback_data": "restart"}]]}
