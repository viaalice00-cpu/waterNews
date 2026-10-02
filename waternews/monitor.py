"""백그라운드 감시: 재난문자 실시간 폴링, 예약 키워드 뉴스 자동 조회, 실시간 이벤트(SSE) 전달."""

import queue
import threading
import time
from datetime import datetime, timedelta

from . import disaster, news, settings as settings_mod, store
from .classify import RegionMatcher
from .net import now_kst

KEEP_DAYS = 3
MAX_LIVE = 5000


def enabled_basin_ids(s):
    return {b["id"] for b in s["basins"] if b.get("enabled")}


def matcher_for(s, basin_ids=None):
    ids = enabled_basin_ids(s) if basin_ids is None else set(basin_ids)
    return RegionMatcher(s["basins"], ids) if ids else None


def is_alert(item, s, target_ids=None):
    """알림 대상 여부: 활성 유역(target_ids)에 해당하고 관련 문자일 때."""
    if target_ids is None:
        target_ids = enabled_basin_ids(s)
    if target_ids and not any(r["basinId"] in target_ids for r in item["regions"]):
        return False
    return item["relevant"] or not s["alerts"].get("waterOnly", True)


class EventHub:
    def __init__(self):
        self._subs = []
        self._lock = threading.Lock()

    def subscribe(self):
        q = queue.Queue(maxsize=200)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, event, data):
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait((event, data))
            except queue.Full:
                pass


class Monitor:
    def __init__(self, load_settings=settings_mod.load, fetcher=disaster.fetch_page,
                 news_getter=None):
        self.load_settings = load_settings
        self.fetcher = fetcher
        self.news_getter = news_getter
        self.hub = EventHub()
        self.lock = threading.RLock()
        self.live = {}                 # sn -> 정규화된 재난문자
        self.baseline_done = False
        self.d_status = {"lastPoll": None, "lastSuccess": None, "error": None,
                         "nextPoll": None, "polls": 0, "lastTotal": 0}
        self.news_items = {}
        self.news_first = True
        self.n_status = {"lastRun": None, "error": None, "nextRun": None, "runs": 0}
        self._next_d = 0.0
        self._next_n = 0.0
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._busy_d = threading.Lock()
        self._busy_n = threading.Lock()

    # ------------------------------------------------------------ 재난문자
    def poll_disaster(self):
        if not self._busy_d.acquire(blocking=False):
            return
        try:
            s = self.load_settings()
            sd = s["safetydata"]
            now = now_kst()
            # 자정 직후 누락 방지: 폴링 간격의 2배 이전 시점의 날짜부터 조회
            crt = (now - timedelta(seconds=sd["pollIntervalSec"] * 2)).strftime("%Y%m%d")
            with self.lock:
                self.d_status["lastPoll"] = now.isoformat()
                self.d_status["polls"] += 1
            try:
                items, total = disaster.fetch_messages(sd, crt, None, self.fetcher)
            except disaster.DisasterApiError as e:
                with self.lock:
                    self.d_status["error"] = str(e)
                self.hub.publish("status", self.status())
                return
            try:
                store.save_disasters(self._annotate_disaster(items, s))
            except Exception as e:  # 저장 실패가 실시간 감시를 멈추지 않도록
                print(f"[store] 재난문자 저장 실패: {e}", flush=True)
            new = []
            with self.lock:
                for it in items:
                    if it["sn"] not in self.live:
                        it["firstSeenAt"] = now.isoformat()
                        self.live[it["sn"]] = it
                        new.append(it)
                self._prune(now)
                first = not self.baseline_done
                self.baseline_done = True
                self.d_status.update(error=None, lastSuccess=now.isoformat(), lastTotal=total)
            if new and not first:
                annotated = self._annotate_disaster(new, s)
                self.hub.publish("disaster", {"items": annotated})
            self.hub.publish("status", self.status())
        finally:
            self._busy_d.release()

    def _prune(self, now):
        cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat()
        for sn in [sn for sn, it in self.live.items() if it["createdAt"] and it["createdAt"] < cutoff]:
            del self.live[sn]
        if len(self.live) > MAX_LIVE:
            for sn, _ in sorted(self.live.items(), key=lambda kv: kv[1]["createdAt"])[: len(self.live) - MAX_LIVE]:
                del self.live[sn]

    def _annotate_disaster(self, items, s):
        # 지역 표시는 전체 유역 기준, 알림 여부는 활성 유역 기준
        m = RegionMatcher(s["basins"])
        targets = enabled_basin_ids(s)
        out = []
        for it in items:
            a = disaster.annotate(dict(it), m, s["keywords"], s.get("keywordGroups"))
            a["alert"] = is_alert(a, s, targets)
            out.append(a)
        return out

    def live_items(self):
        s = self.load_settings()
        with self.lock:
            items = list(self.live.values())
        items = self._annotate_disaster(items, s)
        items.sort(key=lambda x: x["createdAt"], reverse=True)
        return items

    # ------------------------------------------------------------ 예약 뉴스
    def run_news_schedule(self):
        if not self._busy_n.acquire(blocking=False):
            return
        try:
            s = self.load_settings()
            now = now_kst()
            start = (now - timedelta(hours=s["news"]["scheduleLookbackHours"])).date()
            kwargs = {"getter": self.news_getter} if self.news_getter else {}
            try:
                res = news.search_news(s, settings_mod.scheduled_keywords(s), start, now.date(), s["news"]["sources"],
                                       matcher_for(s), **kwargs)
                res["items"] = [it for it in res["items"] if not it["excludedBy"]]
                try:
                    store.save_news(res["items"])
                except Exception as e:
                    print(f"[store] 뉴스 저장 실패: {e}", flush=True)
                err = "; ".join(res["errors"]) or None
            except ValueError as e:
                res, err = {"items": []}, str(e)
            new = []
            with self.lock:
                for it in res["items"]:
                    if it["id"] not in self.news_items:
                        it["firstSeenAt"] = now.isoformat()
                        new.append(it)
                    else:
                        it["firstSeenAt"] = self.news_items[it["id"]].get("firstSeenAt")
                self.news_items = {it["id"]: it for it in res["items"]}
                first, self.news_first = self.news_first, False
                self.n_status.update(lastRun=now.isoformat(), error=err,
                                     runs=self.n_status["runs"] + 1)
            if new and not first:
                self.hub.publish("news", {"items": new})
            self.hub.publish("status", self.status())
        finally:
            self._busy_n.release()

    def scheduled_news(self):
        with self.lock:
            items = list(self.news_items.values())
        items.sort(key=lambda x: x["publishedAt"], reverse=True)
        return items

    # ------------------------------------------------------------ 루프
    def status(self):
        s = self.load_settings()
        with self.lock:
            return {
                "disaster": {**self.d_status,
                             "enabled": bool(s["safetydata"]["pollEnabled"]),
                             "keySet": bool(s["safetydata"]["serviceKey"]),
                             "intervalSec": s["safetydata"]["pollIntervalSec"],
                             "liveCount": len(self.live)},
                "news": {**self.n_status,
                         "enabled": bool(s["news"]["scheduleEnabled"]),
                         "intervalMin": s["news"]["scheduleIntervalMin"],
                         "count": len(self.news_items)},
                "serverTime": now_kst().isoformat(),
            }

    def collect_now(self):
        """사고 분석용 즉시 수집: 재난문자 + 예약 키워드 뉴스 (예약 조회가 꺼져 있어도 1회 실행)."""
        s = self.load_settings()
        if s["safetydata"]["serviceKey"]:
            threading.Thread(target=self.poll_disaster, daemon=True).start()
        threading.Thread(target=self.run_news_schedule, daemon=True).start()

    def trigger(self, what="all"):
        if what in ("all", "disaster"):
            self._next_d = 0
        if what in ("all", "news"):
            self._next_n = 0
        self._wake.set()

    def _tick(self):
        s = self.load_settings()
        t = time.time()
        sd, ns = s["safetydata"], s["news"]
        if sd["pollEnabled"] and sd["serviceKey"] and t >= self._next_d:
            self._next_d = t + sd["pollIntervalSec"]
            with self.lock:
                self.d_status["nextPoll"] = datetime.fromtimestamp(self._next_d, now_kst().tzinfo).isoformat()
            threading.Thread(target=self.poll_disaster, daemon=True).start()
        if ns["scheduleEnabled"] and t >= self._next_n:
            self._next_n = t + ns["scheduleIntervalMin"] * 60
            with self.lock:
                self.n_status["nextRun"] = datetime.fromtimestamp(self._next_n, now_kst().tzinfo).isoformat()
            threading.Thread(target=self.run_news_schedule, daemon=True).start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:  # 설정 파일 손상 등으로 루프가 죽지 않도록
                with self.lock:
                    self.d_status["error"] = f"감시 루프 오류: {e}"
            self._wake.wait(2)
            self._wake.clear()

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="monitor").start()

    def stop(self):
        self._stop.set()
        self._wake.set()
