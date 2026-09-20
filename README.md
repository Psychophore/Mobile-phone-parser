# Mobile-phone-parser

Скрипт собирает актуальные цены на бюджетные смартфоны в российских магазинах
(market.yandex.ru, ozon.ru, wildberries.ru, dns-shop.ru) через Playwright и headless Chromium.
Список моделей и критерии — из документа «Handoff: подбор смартфона до 15 тыс.».

## Установка

```bash
pip install -r requirements.txt
playwright install chromium
```

## Запуск

```bash
# Сначала одна модель на одном источнике
python parse_prices.py --models "POCO M7" --sources yandex

# Все модели, все источники (Маркет → Ozon → WB → DNS), с паузами 3–7 с
python parse_prices.py

# Показать окно браузера и сохранять cookies между запусками (помогает против капчи)
python parse_prices.py --headed --profile .profile

# Разобрать сохранённую вручную страницу магазина
python parse_prices.py --from-html page.html --source yandex --model "POCO M7"
```

Результат: `prices.csv` (model, config, shop, price_rub, version, seller, title, url, fetched_at)
и сводка в консоль: по каждой модели минимальная цена Ростест и Global с пометкой
«до 10 тыс.» / «до 15 тыс.» / «вне бюджета».

Сырые страницы и скриншоты капчи складываются в `dumps/`.
При капче источник пропускается для модели, скрипт не падает.

## Фильтры

- берутся только 4G-версии (карточки с «5G» в названии отбрасываются);
- только целевая конфигурация 6/128 (для Galaxy A07, Redmi 14C, Infinix Hot 50i — 4/128);
  карточки без указанной конфигурации остаются с пометкой `?`;
- аксессуары (чехлы, стёкла) и карточки дешевле 3000 руб. отбрасываются;
- цены выше 2× медианы по модели отбрасываются (`--keep-outliers` отключает).

## Тесты

```bash
pip install pytest && python -m pytest -q tests
```

## Ограничения

Все четыре магазина блокируют простой HTTP, а из облачных сессий Claude Code с сетевой
политикой Trusted они недоступны вовсе. Запускать с российского IP или в окружении
с уровнем сети Full.
