"""Обход магазинов через Playwright и сбор предложений."""
from __future__ import annotations

import os
import random
import re
import sys
import time
from pathlib import Path

from .models import Model
from .offers import Offer
from .sources import Source
from .sources.common import accept

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

_RE_CAPTCHA = re.compile(r"captcha|smartcaptcha|Подтвердите, что вы не робот|Доступ ограничен|"
                         r"Access Denied|antibot|Вы не робот", re.I)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def looks_like_captcha(html: str, url: str) -> bool:
    return "showcaptcha" in url or bool(_RE_CAPTCHA.search(html[:20000]))


class Collector:
    def __init__(self, *, headless: bool = True, min_pause: float = 3.0, max_pause: float = 7.0,
                 dump_dir: Path | None = None, chromium: str | None = None,
                 profile_dir: Path | None = None):
        self.headless = headless
        self.min_pause, self.max_pause = min_pause, max_pause
        self.dump_dir = dump_dir
        self.chromium = chromium or os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
        self.profile_dir = profile_dir
        self._pw = self._browser = self._ctx = self._page = None
        self._warmed: set[str] = set()

    # -- жизненный цикл -----------------------------------------------------
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        launch = dict(headless=self.headless, args=["--disable-blink-features=AutomationControlled"])
        if self.chromium:
            launch["executable_path"] = self.chromium
        ctx_opts = dict(user_agent=USER_AGENT, locale="ru-RU", timezone_id="Europe/Moscow",
                        viewport={"width": 1366, "height": 800})
        if self.profile_dir:
            self._ctx = self._pw.chromium.launch_persistent_context(str(self.profile_dir), **launch, **ctx_opts)
        else:
            self._browser = self._pw.chromium.launch(**launch)
            self._ctx = self._browser.new_context(**ctx_opts)
        self._ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        self._page = self._ctx.new_page()  # одна вкладка на весь обход
        return self

    def __exit__(self, *exc):
        for obj in (self._ctx, self._browser, self._pw):
            try:
                if obj:
                    obj.close() if obj is not self._pw else obj.stop()
            except Exception:
                pass

    # -- вспомогательное ----------------------------------------------------
    def _pause(self) -> None:
        time.sleep(random.uniform(self.min_pause, self.max_pause))

    def _dump(self, name: str, content: str | bytes) -> None:
        if not self.dump_dir:
            return
        self.dump_dir.mkdir(parents=True, exist_ok=True)
        p = self.dump_dir / name
        p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))

    def _warm(self, src: Source) -> None:
        """Зайти на главную магазина один раз, чтобы получить cookies."""
        if src.key in self._warmed:
            return
        self._warmed.add(src.key)
        try:
            self._page.goto(src.home, wait_until="domcontentloaded", timeout=45_000)
            self._page.wait_for_timeout(1500)
        except Exception as e:
            log(f"  [{src.key}] прогрев не удался: {e.__class__.__name__}")
        self._pause()

    # -- основная работа ----------------------------------------------------
    def fetch(self, src: Source, model: Model) -> tuple[str, str] | None:
        """Открыть страницы модели по приоритету; вернуть (содержимое, url) первой удачной."""
        self._warm(src)
        for url in src.urls(model):
            tag = f"{src.key}_{re.sub(r'[^a-z0-9]+', '-', model.name.lower())}"
            try:
                if src.kind == "json":
                    resp = self._page.request.get(url, headers={"Accept": "application/json"}, timeout=45_000)
                    body = resp.text()
                    status, final_url = resp.status, url
                else:
                    resp = self._page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    self._page.wait_for_timeout(3000)
                    body, final_url = self._page.content(), self._page.url
                    status = resp.status if resp else 0
            except Exception as e:
                log(f"  [{src.key}] {url} -> ошибка {e.__class__.__name__}: {str(e)[:120]}")
                self._pause()
                continue
            self._dump(f"{tag}.{'json' if src.kind == 'json' else 'html'}", body)
            if status >= 400:
                log(f"  [{src.key}] {url} -> HTTP {status}, пропускаю")
                self._pause()
                continue
            if src.kind != "json" and looks_like_captcha(body, final_url):
                if self.dump_dir:
                    self._dump(f"{tag}_captcha.png", self._page.screenshot(full_page=False))
                log(f"  [{src.key}] капча на {final_url}, источник пропущен для модели")
                self._pause()
                return None
            self._pause()
            return body, final_url
        return None

    def collect(self, src: Source, model: Model) -> list[Offer]:
        got = self.fetch(src, model)
        if not got:
            return []
        body, url = got
        raw = src.extract(body, model, url)
        kept = [o for o in raw if accept(o, model)]
        log(f"  [{src.key}] {model.name}: карточек {len(raw)}, подходящих {len(kept)}")
        return kept
