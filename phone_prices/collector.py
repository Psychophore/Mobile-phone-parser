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
# Заглушки блокировки по IP: Ozon («Похоже, нет соединения… Выключите VPN»), DNS (qrator, «Доступ к сайту … запрещен»)
_RE_IP_BLOCK = re.compile(r"Похоже, нет соединения|Выключите VPN|Доступ к сайту [\w.\-]+ запрещен|__qrator", re.I)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _proxy_opts(url: str) -> dict:
    """'socks5://user:pass@host:1080' -> параметры proxy для Playwright."""
    from urllib.parse import urlsplit
    u = urlsplit(url if "://" in url else "http://" + url)
    opts = {"server": f"{u.scheme}://{u.hostname}:{u.port}" if u.port else f"{u.scheme}://{u.hostname}"}
    if u.username:
        opts["username"], opts["password"] = u.username, u.password or ""
    return opts


# Страницы JS-проверки, которые проходят сами и перезагружаются: Ozon «Antibot Challenge Page», DNS (Qrator)
_RE_CHALLENGE = re.compile(r"antibot challenge|__qrator|qauth_utm|checking your browser|Проверка браузера", re.I)
CHALLENGE_WAIT_S = 30


def looks_like_challenge(html: str) -> bool:
    return bool(_RE_CHALLENGE.search(html[:20000]))


def looks_like_captcha(html: str, url: str) -> bool:
    return "showcaptcha" in url or bool(_RE_CAPTCHA.search(html[:20000]))


def looks_like_ip_block(html: str) -> bool:
    """Магазин отказал по адресу клиента (дата-центр / зарубежный IP); другие адреса пробовать бесполезно."""
    return bool(_RE_IP_BLOCK.search(html[:20000]))


class Collector:
    def __init__(self, *, headless: bool = True, min_pause: float = 3.0, max_pause: float = 7.0,
                 dump_dir: Path | None = None, chromium: str | None = None,
                 profile_dir: Path | None = None, proxy: str | None = None,
                 no_browser: bool = False):
        self.headless = headless
        self.min_pause, self.max_pause = min_pause, max_pause
        self.dump_dir = dump_dir
        self.chromium = chromium or os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
        self.profile_dir = profile_dir
        self.proxy = proxy or os.environ.get("PARSER_PROXY")
        self.no_browser = no_browser   # без Playwright: только JSON-источники через urllib (Termux, слабые машины)
        self._pw = self._browser = self._ctx = self._page = None
        self._warmed: set[str] = set()

    # -- жизненный цикл -----------------------------------------------------
    def __enter__(self):
        if self.no_browser:
            return self
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        launch = dict(headless=self.headless, args=["--disable-blink-features=AutomationControlled"])
        if self.chromium:
            launch["executable_path"] = self.chromium
        if self.proxy:
            launch["proxy"] = _proxy_opts(self.proxy)
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

    def _get_json(self, url: str) -> tuple[int, str]:
        """JSON-запрос без браузера (режим --no-browser)."""
        import urllib.error
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                                   "Accept-Language": "ru-RU,ru;q=0.9"})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.status, r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")

    def _warm(self, src: Source) -> None:
        """Зайти на главную магазина один раз, чтобы получить cookies."""
        if src.key in self._warmed or self.no_browser:
            return
        self._warmed.add(src.key)
        try:
            self._page.goto(src.home, wait_until="domcontentloaded", timeout=45_000)
            self._page.wait_for_timeout(1500)
        except Exception as e:
            log(f"  [{src.key}] прогрев не удался: {e.__class__.__name__}")
        self._pause()

    # -- основная работа ----------------------------------------------------
    def pages(self, src: Source, model: Model):
        """Открывать адреса модели по приоритету; отдавать (содержимое, url) каждой удачной страницы.

        Останавливается на капче. Страницы-заглушки магазина (is_error) и HTTP >= 400 пропускаются.
        """
        if self.no_browser and src.kind != "json":
            log(f"  [{src.key}] нужен браузер, в режиме --no-browser источник пропущен")
            return
        self._warm(src)
        tag = f"{src.key}_{re.sub(r'[^a-z0-9]+', '-', model.name.lower())}"
        for n, url in enumerate(src.urls(model), 1):
            try:
                if src.kind == "json" and self.no_browser:
                    status, body = self._get_json(url)
                    final_url = url
                elif src.kind == "json":
                    resp = self._page.request.get(url, headers={"Accept": "application/json"}, timeout=45_000)
                    body = resp.text()
                    status, final_url = resp.status, url
                else:
                    resp = self._page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    self._page.wait_for_timeout(3000)
                    body, final_url = self._page.content(), self._page.url
                    status = resp.status if resp else 0
                    if looks_like_challenge(body):
                        body, final_url, status = self._pass_challenge(src, body, status)
            except Exception as e:
                log(f"  [{src.key}] {url} -> ошибка {e.__class__.__name__}: {str(e)[:120]}")
                self._pause()
                continue
            suffix = "" if n == 1 else f"_{n}"
            self._dump(f"{tag}{suffix}.{'json' if src.kind == 'json' else 'html'}", body)
            if src.kind != "json" and looks_like_ip_block(body):
                log(f"  [{src.key}] HTTP {status} на {final_url}: магазин блокирует этот IP, источник пропущен для модели")
                self._pause()
                return
            if status >= 400:
                log(f"  [{src.key}] {url} -> HTTP {status}, пропускаю")
                self._pause()
                continue
            if src.kind != "json" and looks_like_captcha(body, final_url):
                if self.dump_dir:
                    self._dump(f"{tag}{suffix}_captcha.png", self._page.screenshot(full_page=False))
                log(f"  [{src.key}] капча на {final_url}, источник пропущен для модели")
                self._pause()
                return
            if src.is_error and src.is_error(body):
                log(f"  [{src.key}] {url} -> страница с ошибкой магазина, пробую следующий адрес")
                self._pause()
                continue
            self._pause()
            yield body, final_url

    def _pass_challenge(self, src: Source, body: str, status: int) -> tuple[str, str, int]:
        """Дать странице JS-проверки (Ozon antibot, DNS Qrator) пройти и перезагрузиться самой."""
        log(f"  [{src.key}] страница JS-проверки, жду до {CHALLENGE_WAIT_S} с")
        deadline = time.monotonic() + CHALLENGE_WAIT_S
        while time.monotonic() < deadline:
            self._page.wait_for_timeout(2000)
            try:
                body = self._page.content()
            except Exception:      # страница в этот момент перезагружается
                continue
            if not looks_like_challenge(body):
                log(f"  [{src.key}] проверка пройдена")
                return body, self._page.url, 200
        log(f"  [{src.key}] проверка не прошла за {CHALLENGE_WAIT_S} с")
        return body, self._page.url, status

    def fetch(self, src: Source, model: Model) -> tuple[str, str] | None:
        """Первая удачная страница модели (для совместимости)."""
        return next(self.pages(src, model), None)

    def collect(self, src: Source, model: Model) -> list[Offer]:
        raw: list[Offer] = []
        for body, url in self.pages(src, model):
            raw = src.extract(body, model, url)
            if raw:
                break
            log(f"  [{src.key}] {url} -> карточек нет, пробую следующий адрес")
        kept = [o for o in raw if accept(o, model)]
        log(f"  [{src.key}] {model.name}: карточек {len(raw)}, подходящих {len(kept)}")
        return kept
