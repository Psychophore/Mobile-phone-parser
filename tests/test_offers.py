import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from phone_prices.models import find_models
from phone_prices.offers import Offer, drop_outliers, is_5g, parse_config, parse_price, parse_version
from phone_prices.sources import all_sources
from phone_prices.sources.common import accept


def test_parse_config():
    assert parse_config("Смартфон POCO M7 6/128 ГБ, синий") == "6/128"
    assert parse_config("Xiaomi Redmi 15 8GB+256GB Global") == "8/256"
    assert parse_config("Samsung Galaxy A07 4 ГБ RAM 128 ГБ ROM") == "4/128"
    assert parse_config("Honor X8c чёрный") == "?"


def test_5g_and_version():
    assert is_5g("Xiaomi Redmi Note 14 5G 8/256")
    assert not is_5g("Xiaomi Redmi Note 14 4G 8/256")
    assert parse_version("POCO M7 6/128 Ростест") == "EAC"
    assert parse_version("POCO M7 6/128 Global Version") == "Global"
    assert parse_version("POCO M7 6/128") == "?"


def test_parse_price():
    assert parse_price("12 990 ₽") == 12990
    assert parse_price("от 9 499 руб.") == 9499
    assert parse_price("нет цены") is None


def test_accept_filters():
    m = find_models(["POCO M7"])[0]
    ok = Offer(m.name, "6/128", "x", 12000, "?", "", "POCO M7 6/128 ГБ", "u")
    assert accept(ok, m)
    other_cfg = Offer(m.name, "8/256", "x", 15000, "?", "", "POCO M7 8/256 ГБ", "u")
    assert not accept(other_cfg, m)
    wrong_model = Offer(m.name, "6/128", "x", 12000, "?", "", "POCO M6 Pro 6/128", "u")
    assert not accept(wrong_model, m)
    case = Offer(m.name, "6/128", "x", 12000, "?", "", "Чехол для POCO M7 6/128", "u")
    assert not accept(case, m)  # аксессуар
    cheap = Offer(m.name, "?", "x", 390, "?", "", "Чехол для POCO M7", "u")
    assert not accept(cheap, m)


def test_drop_outliers():
    m = "POCO M7"
    mk = lambda p: Offer(m, "6/128", "x", p, "?", "", "POCO M7 6/128", "u")
    kept = drop_outliers([mk(12000), mk(12500), mk(13000), mk(90000)])
    assert [o.price_rub for o in kept] == [12000, 12500, 13000]


def test_jsonld_extract():
    src = all_sources()["yandex"]
    m = find_models(["POCO M7"])[0]
    html = """<html><script type="application/ld+json">%s</script></html>""" % json.dumps({
        "@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
            {"@type": "Product", "name": "Смартфон POCO M7 6/128 ГБ Global", "url": "/product--poco-m7/1",
             "offers": {"@type": "AggregateOffer", "lowPrice": "12990", "priceCurrency": "RUB"}},
            {"@type": "Product", "name": "Смартфон POCO M7 8/256 ГБ", "url": "/product--poco-m7/2",
             "offers": {"@type": "Offer", "price": 15990}},
        ]})
    raw = src.extract(html, m, "https://market.yandex.ru/x")
    assert len(raw) == 2
    kept = [o for o in raw if accept(o, m)]
    assert len(kept) == 1 and kept[0].price_rub == 12990 and kept[0].version == "Global"
    assert kept[0].url == "https://market.yandex.ru/product--poco-m7/1"


def test_generic_extract():
    src = all_sources()["yandex"]
    m = find_models(["Honor X8c"])[0]
    html = ('<div><a href="/product--honor-x8c/5">Смартфон HONOR X8c 6/128 ГБ Ростест</a>'
            '<span class="price">13&nbsp;490 ₽</span></div>'
            '<div><a href="/product--honor-x8c-5g/6">Смартфон HONOR X8c 5G 6/128 ГБ</a><span>14 000 ₽</span></div>')
    kept = [o for o in src.extract(html, m, "https://market.yandex.ru/x") if accept(o, m)]
    assert len(kept) == 1 and kept[0].price_rub == 13490 and kept[0].version == "EAC"


def test_wb_json():
    src = all_sources()["wb"]
    m = find_models(["Redmi 14C"])[0]
    body = json.dumps({"data": {"products": [
        {"id": 1, "brand": "Xiaomi", "name": "Смартфон Redmi 14C 4/128 ГБ", "supplier": "ООО Ромашка",
         "sizes": [{"price": {"product": 899000}}]},
        {"id": 2, "brand": "Xiaomi", "name": "Redmi 14C 8/256", "salePriceU": 1199000},
    ]}})
    raw = src.extract(body, m, "")
    assert [o.price_rub for o in raw] == [8990, 11990]
    assert [o for o in raw if accept(o, m)][0].url.endswith("/catalog/1/detail.aspx")


def test_dns_cards():
    src = all_sources()["dns"]
    m = find_models(["realme C67"])[0]
    html = ('<div class="catalog-product ui-button-widget"><a class="catalog-product__name ui-link" '
            'href="/product/abc/6-realme-c67-6128/"><span>6.72" Смартфон realme C67 128 ГБ черный</span></a>'
            '<div class="product-buy__price">12 999 ₽</div></div>')
    raw = src.extract(html, m, "")
    assert len(raw) == 1 and raw[0].price_rub == 12999 and raw[0].version == "EAC"


def test_cli_from_html(tmp_path):
    page = tmp_path / "p.html"
    page.write_text('<a href="/product--poco-m7/1">POCO M7 6/128</a> 11 990 ₽', encoding="utf-8")
    out = tmp_path / "prices.csv"
    r = subprocess.run([sys.executable, "parse_prices.py", "--from-html", str(page), "--source", "yandex",
                        "--model", "POCO M7", "--out", str(out)], capture_output=True, text=True,
                       cwd=Path(__file__).resolve().parents[1])
    assert r.returncode == 0, r.stderr
    assert "до 15 тыс." in r.stdout
    assert out.read_text(encoding="utf-8").count("\n") == 2


# Фрагмент реальной выдачи market.yandex.ru/search (сентябрь 2026), сокращён до значимых атрибутов.
_YM_SNIPPET = (
    '<div data-auto="searchOrganic"><div><a data-auto="snippet-link" href="{href}?ogV=1&amp;sponsored=1">'
    '<span role="link" data-auto="snippet-title" itemprop="name" title="{title}" class="ds-text">{title}</span>'
    '</a></div><div><a data-auto="snippet-link" href="{href}?ogV=1"><img/></a></div>'
    '<span class="ds-valueLine" data-auto="snippet-price-current" aria-hidden="true">'
    '<span class="ds-text ds-text_weight_bold">{price}</span><span class="ds-text"> ₽</span></span>'
    '<div data-auto="delivery-wrapper">завтра</div></div>'
)


def _ym_page(*cards: tuple[str, str, str]) -> str:
    body = "".join(_YM_SNIPPET.format(href=h, title=t, price=p) for h, t, p in cards)
    return f"<html><body><div data-auto=\"searchIncut\"></div>{body}</body></html>"


def test_yandex_snippets():
    src = all_sources()["yandex"]
    m = find_models(["POCO M7"])[0]
    html = _ym_page(
        ("/card/smartfon-poco-m7-6128gb-global/4740996788", "Смартфон Poco M7, 6/128ГБ, global", "14 503"),
        ("/card/smartfon-apple-iphone-17/1", "Смартфон Apple iPhone 17 256 ГБ (без RuStore)", "97 735"),
        ("/card/smartfon-xiaomi-poco-m7-ru/4799842652", "Смартфон Xiaomi POCO M7 6/128 ГБ RU, 4G, NFC, синий", "17 463"),
        ("/card/poco-m7-8256/3", "Смартфон Xiaomi Poco M7, 8/256 Gb, 6.88&quot;, цвет Black", "19 993"),
    )
    raw = src.extract(html, m, "https://market.yandex.ru/search?text=POCO+M7")
    assert [o.price_rub for o in raw] == [14503, 97735, 17463, 19993]
    assert raw[0].url == "https://market.yandex.ru/card/smartfon-poco-m7-6128gb-global/4740996788"
    assert raw[3].title == 'Смартфон Xiaomi Poco M7, 8/256 Gb, 6.88", цвет Black'
    kept = [o for o in raw if accept(o, m)]
    assert [(o.price_rub, o.version) for o in kept] == [(14503, "Global"), (17463, "EAC")]


def test_yandex_error_page_gives_nothing():
    from phone_prices.sources.yandex_market import is_error_page
    src = all_sources()["yandex"]
    m = find_models(["POCO M7"])[0]
    html = ('<html><body><div data-auto="failure"><h1>Что-то пошло не так</h1></div>'
            '<a href="/card/poco-m7/1">POCO M7 6/128</a> 12 990 ₽</body></html>')
    assert is_error_page(html)
    assert src.extract(html, m, "https://market.yandex.ru/x") == []
    assert src.is_error is is_error_page


def test_yandex_urls_search_by_price():
    src = all_sources()["yandex"]
    m = find_models(["POCO M7"])[0]
    first, second = src.urls(m)
    assert first.startswith("https://market.yandex.ru/search?text=POCO+M7&hid=91491&how=aprice")
    assert "6%2F128" in second and "how=aprice" in second


def test_collector_tries_next_url_when_page_is_empty():
    from phone_prices.collector import Collector
    src = all_sources()["yandex"]
    m = find_models(["POCO M7"])[0]
    pages = [
        ("<html><div data-auto=\"failure\">Тут ничего нет</div></html>", "https://market.yandex.ru/1"),
        ("<html></html>", "https://market.yandex.ru/2"),
        ('<a href="/card/poco-m7/1">POCO M7 6/128</a> 12 990 ₽', "https://market.yandex.ru/3"),
    ]
    c = Collector(dump_dir=None)
    c.pages = lambda s, mm: iter(pages)   # без браузера
    got = c.collect(src, m)
    assert [o.price_rub for o in got] == [12990]
    assert got[0].url == "https://market.yandex.ru/card/poco-m7/1"


def test_model_matching_is_word_based():
    redmi15 = find_models(["Xiaomi Redmi 15"])[0]
    assert redmi15.matches_title("Смартфон Xiaomi Redmi 15 4G 6/128ГБ NFC, Ростест (EAC)")
    assert not redmi15.matches_title("Xiaomi Redmi 15C NFC 4/128GB Midnight Black")
    assert not redmi15.matches_title("Смартфон Xiaomi Redmi Note 15 8/256 ГБ (Global)")
    c67 = find_models(["realme C67"])[0]
    assert c67.matches_title('6,72" Смартфон realme C67 6/128 ГБ (RMX3890) зеленый')
    assert not c67.matches_title("Realme Смартфон Русская версия (EAC) realme C75 NFC")
    poco = find_models(["POCO M7"])[0]
    assert poco.matches_title("Poco Смартфон Poco M7 Глобальная версия Global 6/128 ГБ")
    assert not poco.matches_title("Poco Смартфон POCO M7 Pro purple-8+256 Global 8/256 ГБ")
    spark = find_models(["Tecno Spark 40 Pro"])[0]
    assert spark.matches_title("Смартфон Tecno Spark 40 Pro 8 ГБ/256 ГБ Черный Ростест")
    assert not spark.matches_title("Смартфон Tecno Spark 40 Pro Plus 8/256 Gb, Nebula Black")
    assert not spark.matches_title('6,78" Смартфон TECNO Spark 40 Pro+ 8/256 ГБ (SPARK 40 PRO+) 2025')
    a17 = find_models(["Galaxy A17"])[0]
    assert a17.matches_title("Смартфон Samsung Galaxy A17, 4G LTE, NFC, 4/128Gb, Light Blue")
    hot = find_models(["Infinix Hot 50i"])[0]
    assert hot.matches_title("Смартфон Infinix HOT 50i 4/128 ГБ") and not hot.matches_title("Infinix Hot 50 Pro")


def test_parse_config_space_separated():
    assert parse_config("POCO M7, 6 128ГБ, global") == "6/128"
    assert parse_config("Смартфон Poco M7 6 128 Black") == "6/128"
    assert parse_config("Смартфон M7 8GB+256GB Blue") == "8/256"
    assert parse_config("Смартфон M7 8 ГБ+256 ГБ, синий") == "8/256"
    assert parse_config('6,72" Смартфон realme C67 черный') == "?"    # диагональ — не конфигурация
    assert parse_config("Смартфон 6.88 дюйма 128 Гц") == "?"
    assert parse_config("TECNO Pova 6 Neo Global 16 1024Gb 8000mAh") == "16/1024"   # фейковые «1 ТБ» карточки


def test_wb_title_composition():
    from phone_prices.sources.wildberries import compose_title
    assert compose_title("POCO", "Смартфон M7 8GB+256GB Blue") == "POCO M7 8GB+256GB Blue"
    assert compose_title("Xiaomi", "Смартфон Poco M7 6 128 Blue") == "Xiaomi Poco M7 6 128 Blue"
    assert compose_title("", "Смартфон Poco M7 6 128 Black") == "Poco M7 6 128 Black"
    assert compose_title("POCO", "M7 Глобальная версия 6 128GB серебристый") == "POCO M7 Глобальная версия 6 128GB серебристый"
    assert compose_title("", "Poco Смартфон POCO M7 Ростест (EAC) 6 128 ГБ") == "Poco Смартфон POCO M7 Ростест (EAC) 6 128 ГБ"
    assert compose_title("Нет бренда", "Чехол для Xiaomi Poco M7") == "Чехол для Xiaomi Poco M7"
    m = find_models(["POCO M7"])[0]
    for brand, name in (("POCO", "Смартфон M7 6GB+128GB Black"), ("Xiaomi", "Смартфон Poco M7 6 128 Blue"),
                        ("", "Смартфон Poco M7 6 128 Silver")):
        assert m.matches_title(compose_title(brand, name)), (brand, name)
    assert not m.matches_title(compose_title("POCO", "Смартфон M7 Pro 8GB+256GB"))


def test_ip_block_detection():
    from phone_prices.collector import looks_like_ip_block
    assert looks_like_ip_block("<title>Похоже, нет соединения</title>Выключите VPN, перезагрузите роутер")
    assert looks_like_ip_block("<div class=\"descr\"><p>Доступ к сайту www.dns-shop.ru запрещен.</p>")
    assert looks_like_ip_block('<script src="/__qrator/qauth_utm_v2d_v9118.js"></script>')
    assert not looks_like_ip_block('<div data-auto="searchOrganic">POCO M7 14 503 ₽</div>')
