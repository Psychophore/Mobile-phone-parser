"""Локальный веб-интерфейс: ключевые слова вводятся в браузере, парсер выдаёт таблицу.

Запуск: `python parse_prices.py --ui` (по умолчанию http://127.0.0.1:8765, слушает только
локальный адрес). Нужен, чтобы владелец гонял поиск сам, без сессии Claude Code.

Устройство: стандартный http.server (лишних зависимостей нет), страница — `ui.html` рядом.
Поиск идёт в отдельном потоке (Playwright работает синхронно и требует одного потока),
лог коллектора перехватывается `collector.set_log_sink` и отдаётся странице по опросу
`/api/job`. Одновременно выполняется только один поиск: браузер один.

API:
  GET  /                -> страница
  GET  /api/models      -> список моделей из MODELS (кнопки-подсказки)
  POST /api/search      -> {id}: запустить поиск, тело — параметры формы
  GET  /api/job?id&since-> новые строки лога, результаты, сводка
  POST /api/stop        -> остановить после текущего источника
  GET  /api/csv?id      -> результаты CSV
"""
from __future__ import annotations

import json
import threading
import traceback
import uuid
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .collector import Collector, log, set_log_sink
from .models import MODELS
from .offers import Offer, drop_outliers
from .query import build_query
from .report import csv_text, summary
from .sources import all_sources
from .sources.common import accept, read_page

HOST = "127.0.0.1"
PORT = 8765
PAGE = Path(__file__).with_name("ui.html")
MAX_LOG = 2000


@dataclass
class Job:
    """Один запуск поиска: лог, результаты и флаг остановки."""

    id: str
    params: dict
    lines: list[str] = field(default_factory=list)
    offers: list[Offer] = field(default_factory=list)
    summary: str = ""
    done: bool = False
    error: str = ""
    stop: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def say(self, msg: str) -> None:
        with self.lock:
            if len(self.lines) < MAX_LOG:
                self.lines.append(msg)

    def state(self, since: int) -> dict:
        with self.lock:
            return {
                "id": self.id, "done": self.done, "error": self.error, "stopping": self.stop,
                "lines": self.lines[since:], "next": len(self.lines),
                "summary": self.summary,
                "rows": [o.as_row() for o in self.offers] if self.done else [],
            }


JOBS: dict[str, Job] = {}
_running = threading.Lock()


def _int(v, default: int = 0) -> int:
    try:
        return int(float(str(v).replace(" ", "").replace(" ", "")))
    except (TypeError, ValueError):
        return default


def params_from(raw: dict) -> dict:
    """Проверить и привести к нужным типам то, что прислала страница."""
    known = list(all_sources())
    srcs = [s for s in (raw.get("sources") or []) if s in known] or ["yandex", "wb"]
    pause = raw.get("pause") or [3, 7]
    return {
        "query": " ".join(str(raw.get("query", "")).split()),
        "ram": _int(raw.get("ram")), "rom": _int(raw.get("rom")),
        "sources": srcs,
        "price_min": _int(raw.get("price_min")), "price_max": _int(raw.get("price_max")),
        "trusted_only": bool(raw.get("trusted_only", True)),
        "no_outliers": bool(raw.get("no_outliers", True)),
        "accessories": bool(raw.get("accessories", False)),
        "allow_5g": bool(raw.get("allow_5g", False)),
        "drop_variants": bool(raw.get("drop_variants", True)),
        "in_category": bool(raw.get("in_category", False)),
        "direct": bool(raw.get("direct", False)),
        "headed": bool(raw.get("headed", False)),
        "channel": (raw.get("channel") or None) if raw.get("channel") in ("chrome", "msedge") else None,
        "stealth": bool(raw.get("stealth", False)),
        "no_browser": bool(raw.get("no_browser", False)),
        "profile": str(raw.get("profile", "") or ""),
        "proxy": str(raw.get("proxy", "") or ""),
        "dumps": bool(raw.get("dumps", True)),
        "pause": [max(0.0, float(pause[0])), max(0.0, float(pause[1]))],
        "from_html": str(raw.get("from_html", "") or ""),
        "from_html_source": raw.get("from_html_source") if raw.get("from_html_source") in known else "yandex",
    }


def _crawl(job: Job, model) -> list[Offer]:
    p, sources = job.params, all_sources()
    offers: list[Offer] = []
    with Collector(headless=not p["headed"], min_pause=p["pause"][0], max_pause=p["pause"][1],
                   dump_dir=Path("dumps") if p["dumps"] else None,
                   profile_dir=Path(p["profile"]) if p["profile"] else None,
                   proxy=p["proxy"] or None, no_browser=p["no_browser"],
                   channel=p["channel"], stealth=p["stealth"], direct=p["direct"]) as c:
        for key in p["sources"]:
            if job.stop:
                log("остановлено владельцем")
                break
            src = sources[key]
            log(f"== {src.shop}")
            offers.extend(c.collect(src, model))
    return offers


def _from_dump(job: Job, model) -> list[Offer]:
    """Разобрать сохранённую страницу с диска: Ozon и DNS владелец сохраняет вручную."""
    p = job.params
    src = all_sources()[p["from_html_source"]]
    path = Path(p["from_html"]).expanduser()
    if not path.is_file():
        raise ValueError(f"файл не найден: {path}")
    raw = src.extract(read_page(path), model, src.home)
    kept = [o for o in raw if accept(o, model)]
    log(f"  [{src.key}] {path.name}: карточек {len(raw)}, подходящих {len(kept)}")
    return kept


def run_job(job: Job) -> None:
    set_log_sink(job.say)
    p = job.params
    try:
        model = build_query(p["query"], ram=p["ram"], rom=p["rom"], accessories=p["accessories"],
                            allow_5g=p["allow_5g"], drop_variants=p["drop_variants"],
                            in_category=p["in_category"])
        log(f"запрос: «{model.search_text}»" + (f", конфигурация {model.config}" if model.config else ""))
        offers = _from_dump(job, model) if p["from_html"] else _crawl(job, model)

        if p["trusted_only"]:
            before = len(offers)
            offers = [o for o in offers if o.trusted]
            if before != len(offers):
                log(f"отброшено непроверенных продавцов: {before - len(offers)}")
        if p["no_outliers"]:
            before = len(offers)
            offers = drop_outliers(offers)
            if before != len(offers):
                log(f"отброшено выбросов: {before - len(offers)}")
        lo, hi = p["price_min"], p["price_max"]
        if lo or hi:
            before = len(offers)
            offers = [o for o in offers if o.price_rub >= (lo or 0) and (not hi or o.price_rub <= hi)]
            if before != len(offers):
                log(f"отброшено вне диапазона цены: {before - len(offers)}")

        offers.sort(key=lambda o: (not o.trusted, o.reviews == 0, o.price_rub))
        with job.lock:
            job.offers = offers
            job.summary = summary(offers, [model])
        log(f"готово: {len(offers)} предложений")
    except Exception as e:                       # показать владельцу, а не уронить сервер
        job.error = f"{e.__class__.__name__}: {e}"
        log("ошибка: " + job.error)
        traceback.print_exc()
    finally:
        job.done = True
        set_log_sink(None)
        if _running.locked():
            _running.release()


def start_job(raw: dict) -> tuple[dict, int]:
    p = params_from(raw)
    if not p["query"]:
        return {"error": "не задан запрос"}, 400
    if not _running.acquire(blocking=False):
        return {"error": "поиск уже идёт, дождитесь конца или нажмите «Стоп»"}, 409
    job = Job(id=uuid.uuid4().hex[:12], params=p)
    JOBS[job.id] = job
    threading.Thread(target=run_job, args=(job,), daemon=True, name="search").start()
    return {"id": job.id}, 200


class Handler(BaseHTTPRequestHandler):
    server_version = "phone-prices-ui"
    protocol_version = "HTTP/1.1"

    def log_message(self, *a) -> None:      # не засорять терминал строками доступа
        pass

    # -- ответы -------------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str, headers: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: dict, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _local_only(self) -> bool:
        """Страницу открывают с этой же машины; чужой Host — попытка достучаться снаружи."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in ("127.0.0.1", "localhost", "::1", "")

    def _job(self, qs: dict) -> Job | None:
        return JOBS.get((qs.get("id") or [""])[0])

    # -- маршруты -----------------------------------------------------------
    def do_GET(self) -> None:
        if not self._local_only():
            return self._json({"error": "только с этого компьютера"}, 403)
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if u.path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        if u.path == "/api/models":
            return self._json({"models": [{"name": m.name, "ram": m.ram, "rom": m.rom, "note": m.note}
                                          for m in MODELS],
                               "sources": [{"key": s.key, "shop": s.shop} for s in all_sources().values()]})
        if u.path == "/api/job":
            job = self._job(qs)
            if not job:
                return self._json({"error": "поиск не найден"}, 404)
            return self._json(job.state(_int((qs.get("since") or ["0"])[0])))
        if u.path == "/api/csv":
            job = self._job(qs)
            if not job:
                return self._json({"error": "поиск не найден"}, 404)
            body = csv_text(job.offers).encode("utf-8-sig")   # BOM: Excel открывает без вопросов
            return self._send(200, body, "text/csv; charset=utf-8",
                              {"Content-Disposition": f'attachment; filename="prices-{job.id}.csv"'})
        self._json({"error": "нет такой страницы"}, 404)

    def do_POST(self) -> None:
        if not self._local_only():
            return self._json({"error": "только с этого компьютера"}, 403)
        u = urlparse(self.path)
        try:
            raw = json.loads(self.rfile.read(_int(self.headers.get("Content-Length"))) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "испорченный запрос"}, 400)
        if not isinstance(raw, dict):
            return self._json({"error": "испорченный запрос"}, 400)
        if u.path == "/api/search":
            body, code = start_job(raw)
            return self._json(body, code)
        if u.path == "/api/stop":
            job = JOBS.get(str(raw.get("id", "")))
            if not job:
                return self._json({"error": "поиск не найден"}, 404)
            job.stop = True
            return self._json({"ok": True})
        self._json({"error": "нет такой страницы"}, 404)


def serve(port: int = PORT, host: str = HOST, open_browser: bool = True) -> int:
    srv = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{srv.server_address[1]}/"
    print(f"Веб-интерфейс парсера: {url}  (Ctrl+C — выход)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nостановлен")
    finally:
        srv.server_close()
    return 0
