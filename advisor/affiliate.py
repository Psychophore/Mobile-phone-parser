"""Партнёрские ссылки и рекламная пометка.

Шаблоны ссылок берутся из кабинета CPA-сети или партнёрской программы магазина и кладутся в JSON:

    {
      "label": "Реклама. <рекламодатель>, erid: <токен>",
      "shops": {
        "wildberries.ru": {"template": "https://<ссылка из кабинета>?ulp={url_enc}&subid={subid}"}
      }
    }

Подстановки: {url} — ссылка на карточку как есть, {url_enc} — она же в URL-кодировке,
{subid} — идентификатор подбора, по которому отчёт сети сопоставляется с журналом бота.
Без файла или без шаблона для магазина ссылка остаётся прямой, пометка не показывается.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote


@dataclass
class Affiliate:
    templates: dict[str, str] = field(default_factory=dict)
    label: str = ""

    @classmethod
    def load(cls, path: Path | None) -> "Affiliate":
        if not path:
            return cls()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        templates = {shop: cfg["template"] for shop, cfg in (data.get("shops") or {}).items()
                     if isinstance(cfg, dict) and cfg.get("template")}
        return cls(templates, data.get("label", ""))

    def is_partner(self, shop: str) -> bool:
        return shop in self.templates

    def wrap(self, url: str, shop: str, subid: str = "") -> str:
        tpl = self.templates.get(shop)
        if not tpl or not url:
            return url
        return tpl.format(url=url, url_enc=quote(url, safe=""), subid=quote(subid, safe=""))
