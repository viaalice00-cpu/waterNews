"""금강유역 지자체 상수도·풍수해 언론 모니터링 서버.

실행:  python app.py              (http://127.0.0.1:8080)
       python app.py --port 9000 --host 0.0.0.0
       WATERNEWS_DEMO=1 python app.py   (외부 API 없이 가상 데이터로 화면 확인)
"""

import argparse
import json
import mimetypes
import os
import queue
import sys
import urllib.parse
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from waternews import ai, analysis, disaster, news, settings as settings_mod, store
from waternews.classify import RegionMatcher
from waternews.monitor import Monitor, enabled_basin_ids, is_alert, matcher_for
from waternews.net import now_kst

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "web", "dist")   # React 빌드 결과 (cd web && npm run build)
DEMO = os.environ.get("WATERNEWS_DEMO") == "1"
MAX_BODY = 1_000_000


def load_settings():
    s = settings_mod.load()
    if DEMO:
        s["safetydata"]["serviceKey"] = s["safetydata"]["serviceKey"] or "DEMO"
        s["naver"]["clientId"] = s["naver"]["clientId"] or "DEMO"
        s["naver"]["clientSecret"] = s["naver"]["clientSecret"] or "DEMO"
    return s


if DEMO:
    from waternews import demo
    MONITOR = Monitor(load_settings, fetcher=demo.fetch_page, news_getter=demo.news_getter)
    NEWS_GETTER = demo.news_getter
else:
    MONITOR = Monitor(load_settings)
    NEWS_GETTER = None


AI_CACHE = {}   # (사건 id, 항목 수, 모델) → 브리핑. 같은 사건에 새 기사가 들어오면 다시 생성


def _csv(v):
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _bool(v, default=False):
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")


class Handler(BaseHTTPRequestHandler):
    server_version = "WaterNews/0.1"

    def log_message(self, fmt, *args):
        if os.environ.get("WATERNEWS_ACCESS_LOG") == "1":
            super().log_message(fmt, *args)

    # ------------------------------------------------------------ 응답 헬퍼
    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message, status=400):
        self._json({"error": message}, status)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("요청 본문이 너무 큽니다.")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _static(self, path):
        if not os.path.isfile(os.path.join(STATIC, "index.html")):
            body = ("<meta charset='utf-8'><h3>화면(React)이 아직 빌드되지 않았습니다.</h3>"
                    "<p>터미널에서 <code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code> 실행 후 "
                    "새로고침하세요.</p>").encode("utf-8")
            self.send_response(503)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        full = os.path.realpath(os.path.join(STATIC, rel))
        if not full.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(full):
            if "." in os.path.basename(path):
                return self._error("not found", 404)
            full = os.path.join(STATIC, "index.html")   # SPA 경로는 index.html 로
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # 빌드 파일명에 해시가 붙는 assets/ 는 장기 캐시, index.html 은 매번 확인
        cache = "public, max-age=31536000, immutable" if "/assets/" in full.replace(os.sep, "/") else "no-cache"
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------ 라우팅
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query, keep_blank_values=True).items()}
        try:
            if url.path == "/api/settings":
                return self._json(self._settings_view(load_settings() if DEMO else settings_mod.load()))
            if url.path == "/api/status":
                return self._json(MONITOR.status())
            if url.path == "/api/live":
                return self._json({"items": MONITOR.live_items(), "status": MONITOR.status()})
            if url.path == "/api/news/scheduled":
                return self._json({"items": MONITOR.scheduled_news(), "status": MONITOR.status()})
            if url.path == "/api/analysis":
                return self._analysis(q)
            if url.path == "/api/news":
                return self._news(q)
            if url.path == "/api/disaster":
                return self._disaster(q)
            if url.path == "/api/events":
                return self._events()
            if url.path.startswith("/api/"):
                return self._error("not found", 404)
            return self._static(url.path)
        except (ValueError, disaster.DisasterApiError) as e:
            return self._error(str(e))

    def do_PUT(self):
        if self.path != "/api/settings":
            return self._error("not found", 404)
        try:
            new = settings_mod.apply_update(settings_mod.load(), self._body())
        except (ValueError, AttributeError, TypeError) as e:
            return self._error(f"설정 저장 실패: {e}")
        settings_mod.save(new)
        MONITOR.trigger("disaster")
        self._json(self._settings_view(load_settings() if DEMO else new))

    def do_POST(self):
        try:
            if self.path == "/api/live/refresh":
                MONITOR.trigger(self._body().get("target", "all"))
                return self._json({"ok": True})
            if self.path == "/api/disaster/test":
                return self._test_key(self._body())
            if self.path == "/api/analysis/collect":
                MONITOR.collect_now()
                return self._json({"ok": True})
            if self.path == "/api/analysis/ai":
                return self._ai_briefing(self._body())
        except ValueError as e:
            return self._error(str(e))
        return self._error("not found", 404)

    # ------------------------------------------------------------ API 구현
    @staticmethod
    def _settings_view(s):
        return {**settings_mod.public_view(s), "demo": DEMO, "aiModels": ai.AI_MODELS}

    def _run_analysis(self, q, keep_items=False):
        s = load_settings()
        hours = max(1, min(24 * 30, int(q.get("hours") or 72)))
        now = now_kst()
        since = now - timedelta(hours=hours)
        items = store.load(since.isoformat())
        prev = store.load((since - timedelta(hours=hours)).isoformat(), since.isoformat())
        ids = self._basin_ids(q, s)
        res = analysis.analyze(items, prev, hours, ids or None, keep_items=keep_items)
        res.update(hours=hours, since=since.isoformat(), until=now.isoformat(),
                   basins=sorted(ids), store=store.stats())
        return res

    def _analysis(self, q):
        res = self._run_analysis(q)
        model = load_settings()["ai"]["model"]
        for c in res["clusters"]:
            cached = AI_CACHE.get((c["id"], c["counts"]["total"], model))
            c["ai"] = cached
        return self._json(res)

    def _ai_briefing(self, body):
        q = {"hours": body.get("hours")}
        if "basins" in body:
            q["basins"] = body["basins"]
        res = self._run_analysis(q, keep_items=True)
        c = next((c for c in res["clusters"] if c["id"] == body.get("clusterId")), None)
        if not c:
            return self._error("해당 사건을 찾을 수 없습니다. 분석을 새로고침하세요.", 404)
        s = load_settings()
        key = (c["id"], c["counts"]["total"], s["ai"]["model"])
        if key not in AI_CACHE or body.get("refresh"):
            try:
                AI_CACHE[key] = ai.generate_briefing(c, c["_items"], s["ai"]["apiKey"], s["ai"]["model"])
            except ai.AIError as e:
                return self._json({"ok": False, "message": str(e)})
        return self._json({"ok": True, **AI_CACHE[key]})

    def _basin_ids(self, q, s):
        if "basins" in q:
            return set(_csv(q["basins"]))
        return enabled_basin_ids(s)

    def _news(self, q):
        s = load_settings()
        today = now_kst().date()
        start = disaster.parse_date(q.get("from"), today - timedelta(days=7))
        end = disaster.parse_date(q.get("to"), today)
        if end < start:
            start, end = end, start
        if (end - start).days > 365:
            raise ValueError("뉴스 조회 기간은 최대 1년입니다.")
        keywords = _csv(q.get("keywords")) or s["keywords"]
        sources = [x for x in _csv(q.get("sources")) or s["news"]["sources"] if x in ("google", "naver")]
        ids = self._basin_ids(q, s)
        matcher = matcher_for(s, ids) if ids else None
        kwargs = {"getter": NEWS_GETTER} if NEWS_GETTER else {}
        res = news.search_news(s, keywords, start, end, sources, matcher,
                               include_unmatched=_bool(q.get("includeUnmatched")),
                               region_in_query=_bool(q.get("regionInQuery"), s["news"]["regionInQuery"]),
                               **kwargs)
        res.update(start=start.isoformat(), end=end.isoformat(), keywords=keywords, sources=sources)
        try:
            store.save_news(res["items"])   # 사고 분석용 누적
        except Exception as e:
            print(f"[store] 뉴스 저장 실패: {e}", flush=True)
        return self._json(res)

    def _disaster(self, q):
        s = load_settings()
        today = now_kst().date()
        start = disaster.parse_date(q.get("from"), today)
        end = disaster.parse_date(q.get("to"), today)
        fetcher = MONITOR.fetcher
        items = disaster.fetch_range(s["safetydata"], start, end, q.get("rgnNm") or None, fetcher)
        ids = self._basin_ids(q, s)
        matcher = RegionMatcher(s["basins"])
        targets = enabled_basin_ids(s)
        out = []
        for it in items:
            disaster.annotate(it, matcher, s["keywords"])
            it["alert"] = is_alert(it, s, targets)
            in_target = any(r["basinId"] in ids for r in it["regions"])
            if ids and not in_target and not _bool(q.get("includeUnmatched")):
                continue
            if _bool(q.get("waterOnly")) and not it["relevant"]:
                continue
            out.append(it)
        return self._json({"items": out, "fetched": len(items),
                           "start": start.isoformat(), "end": end.isoformat()})

    def _test_key(self, body):
        s = load_settings()
        sd = dict(s["safetydata"])
        if body.get("serviceKey"):
            sd["serviceKey"] = body["serviceKey"].strip()
        sd["numOfRows"] = 5
        try:
            rows, total = MONITOR.fetcher(sd, 1, now_kst().strftime("%Y%m%d"), None)
        except disaster.DisasterApiError as e:
            return self._json({"ok": False, "message": str(e)})
        sample = [disaster.normalize(r) for r in rows[:3]]
        return self._json({"ok": True, "message": f"정상 연결 (오늘 총 {total}건)", "sample": sample})

    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        sub = MONITOR.hub.subscribe()
        try:
            self._send_event("status", MONITOR.status())
            while True:
                try:
                    event, data = sub.get(timeout=15)
                    self._send_event(event, data)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            MONITOR.hub.unsubscribe(sub)

    def _send_event(self, event, data):
        payload = json.dumps(data, ensure_ascii=False)
        self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode("utf-8"))
        self.wfile.flush()


def main(argv=None):
    p = argparse.ArgumentParser(description="유역별 상수도·풍수해 언론/재난문자 모니터링")
    p.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = p.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    MONITOR.start()
    if DEMO:
        MONITOR.collect_now()   # 데모: 사고 분석 화면용 데이터 즉시 수집
    mode = " [데모 모드]" if DEMO else ""
    print(f"모니터링 서버 실행 중{mode}: http://{args.host}:{args.port}  (종료: Ctrl+C)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        MONITOR.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
