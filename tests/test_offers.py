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
