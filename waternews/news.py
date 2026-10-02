"""구글 뉴스(RSS) · 네이버 뉴스 검색 API 연계."""

import html
import json
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from .classify import classify, exclusion_hits, group_context, keyword_hits
from .net import KST, FetchError, http_get, now_kst

GOOGLE_RSS = "https://news.google.com/rss/search"
NAVER_NEWS = "https://openapi.naver.com/v1/search/news.json"
REGION_CHUNK = 8          # 구글 검색어 1건당 OR 결합 지명 수
NAVER_MIN_INTERVAL = 0.15  # 네이버 호출 간 최소 간격(초) — 초당 호출 제한(오류 012) 대응, 약 6~7회/초
NAVER_RETRIES = 3          # 속도 제한(429) 시 재시도 횟수 (1초 → 2초 → 4초 대기)
_TAG_RE = re.compile(r"<[^>]+>")


def clean(text):
    return html.unescape(_TAG_RE.sub("", html.unescape(text or ""))).strip()


def _pubdate(value):
    try:
        return parsedate_to_datetime(value).astimezone(KST)
    except (TypeError, ValueError, IndexError):
        return None


def _q(term):
    return f'"{term}"' if " " in term else term


# ---------------------------------------------------------------- Google News
def google_query(keyword, region_terms, start, end, today=None):
    q = _q(keyword)
    if region_terms:
        q += " (" + " OR ".join(_q(t) for t in region_terms) + ")"
    today = today or now_kst().date()
    if end >= today:
        # 오늘까지 조회: RSS 는 after:/before: 를 무시하고 관련도 높은 옛 기사를 주는 경우가 많아
        # 최근 N일 연산자 when: 을 사용 (RSS 에서 안정적으로 동작)
        q += f" when:{(today - start).days + 1}d"
    else:
        # 과거 기간: before: 는 해당일 미포함이므로 종료일+1
        q += f" after:{start.isoformat()} before:{(end + timedelta(days=1)).isoformat()}"
    return q


def parse_google_rss(payload):
    root = ET.fromstring(payload)
    items = []
    for it in root.iter("item"):
        title = clean(it.findtext("title"))
        source = it.find("source")
        press = clean(source.text) if source is not None and source.text else ""
        if press and title.endswith(" - " + press):
            title = title[: -len(press) - 3]
        pub = _pubdate(it.findtext("pubDate"))
        items.append({
            "source": "google",
            "title": title,
            "link": (it.findtext("link") or "").strip(),
            "press": press,
            "description": "",
            "publishedAt": pub.isoformat() if pub else "",
        })
    return items


def fetch_google(keyword, region_terms, start, end, getter=http_get):
    params = {"q": google_query(keyword, region_terms, start, end),
              "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
    _, body = getter(f"{GOOGLE_RSS}?{urllib.parse.urlencode(params)}")
    return parse_google_rss(body)


# ---------------------------------------------------------------- Naver
def parse_naver(payload):
    data = json.loads(payload)
    items = []
    for it in data.get("items", []):
        pub = _pubdate(it.get("pubDate"))
        link = it.get("originallink") or it.get("link") or ""
        host = urllib.parse.urlparse(link).hostname or ""
        items.append({
            "source": "naver",
            "title": clean(it.get("title")),
            "link": link,
            "naverLink": it.get("link") or "",
            "press": host.removeprefix("www."),
            "description": clean(it.get("description")),
            "publishedAt": pub.isoformat() if pub else "",
        })
    return items, int(data.get("total") or 0)


class _Throttle:
    """여러 스레드(수동 조회·예약 조회)가 공유하는 호출 간격 제한."""

    def __init__(self, interval):
        self.interval = interval
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            if now < self._next:
                time.sleep(self._next - now)
                now = self._next
            self._next = now + self.interval


naver_throttle = _Throttle(NAVER_MIN_INTERVAL)


def _naver_error_code(body):
    try:
        return str(json.loads(body).get("errorCode", ""))
    except (ValueError, AttributeError):
        return ""


def naver_get(url, headers, getter=http_get, sleep=time.sleep):
    """네이버 API 호출: 간격 제한 + 속도 제한(012) 시 지수 백오프 재시도. 일일 한도(010)는 즉시 안내."""
    for attempt in range(NAVER_RETRIES + 1):
        naver_throttle.wait()
        try:
            return getter(url, headers=headers)
        except FetchError as e:
            if e.status != 429:
                raise
            if _naver_error_code(e.body) == "010":
                raise FetchError("네이버 검색 API 일일 호출 한도(25,000회)를 초과했습니다. 내일 다시 시도하거나 "
                                 "예약 조회 주기를 늘리고 네이버 최대 페이지 수를 줄이세요.", 429, e.body) from e
            if attempt == NAVER_RETRIES:
                raise FetchError("네이버 검색 API 속도 제한(초당 호출 수)을 초과했습니다. 잠시 후 다시 조회하세요.",
                                 429, e.body) from e
            sleep(2 ** attempt)


def fetch_naver(keyword, client_id, client_secret, start, max_pages=5, getter=http_get):
    """최신순으로 페이지를 넘기며 조회 시작일 이전 기사가 나오면 중단."""
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    out = []
    for page in range(max_pages):
        params = {"query": keyword, "display": 100, "start": page * 100 + 1, "sort": "date"}
        _, body = naver_get(f"{NAVER_NEWS}?{urllib.parse.urlencode(params)}", headers, getter)
        items, total = parse_naver(body)
        out.extend(items)
        oldest = min((i["publishedAt"] for i in items if i["publishedAt"]), default="")
        if (not items or len(items) < 100 or page * 100 + 100 >= min(total, 1000)
                or (oldest and datetime.fromisoformat(oldest).date() < start)):
            break
    return out


# ---------------------------------------------------------------- 통합 검색
def _norm_title(title):
    return re.sub(r"[^0-9a-z가-힣]", "", title.lower())


def search_news(settings, keywords, start, end, sources, matcher=None,
                include_unmatched=False, region_in_query=None, getter=http_get):
    """키워드×소스 조회 → 기간 필터 → 중복 제거 → 분류/지역 매칭."""
    keywords = [k for k in keywords if k.strip()]
    if not keywords:
        raise ValueError("검색 키워드를 1개 이상 입력하세요.")
    if region_in_query is None:
        region_in_query = settings["news"].get("regionInQuery", True)
    naver = settings["naver"]
    errors, tasks = [], []

    terms = matcher.news_terms() if (matcher and region_in_query) else []
    chunks = [terms[i:i + REGION_CHUNK] for i in range(0, len(terms), REGION_CHUNK)] or [[]]

    if "google" in sources:
        for kw in keywords:
            for chunk in chunks:
                tasks.append(("구글", kw, lambda kw=kw, chunk=chunk:
                              fetch_google(kw, chunk, start, end, getter=getter)))
    if "naver" in sources:
        if naver.get("clientId") and naver.get("clientSecret"):
            for kw in keywords:
                tasks.append(("네이버", kw, lambda kw=kw: fetch_naver(
                    kw, naver["clientId"], naver["clientSecret"], start,
                    settings["news"].get("naverMaxPages", 5), getter=getter)))
        else:
            errors.append("네이버 검색 API 키(Client ID/Secret)가 설정되지 않아 네이버 조회를 건너뜁니다.")

    raw = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [(src, kw, pool.submit(fn)) for src, kw, fn in tasks]
        for src, kw, fut in futures:
            try:
                for it in fut.result():
                    it["query"] = kw
                    raw.append(it)
            except (FetchError, ValueError, ET.ParseError) as e:
                errors.append(f"{src} '{kw}' 조회 실패: {e}")

    merged = {}
    dropped = {"date": 0, "region": 0}
    out_dates = []
    for it in raw:
        if it["publishedAt"]:
            d = datetime.fromisoformat(it["publishedAt"]).date()
            if d < start or d > end:
                dropped["date"] += 1
                out_dates.append(d)
                continue
        key = _norm_title(it["title"])
        if not key:
            continue
        if key in merged:
            m = merged[key]
            if it["source"] not in m["sources"]:
                m["sources"].append(it["source"])
            if it["query"] not in m["queries"]:
                m["queries"].append(it["query"])
            if not m["description"] and it["description"]:
                m["description"] = it["description"]
            continue
        it["sources"] = [it.pop("source")]
        it["queries"] = [it.pop("query")]
        it["id"] = key[:80]
        merged[key] = it

    items, excluded = [], 0
    exclude_words = settings.get("excludeKeywords") or []
    for it in merged.values():
        text = f"{it['title']} {it['description']}"
        it["categories"] = classify(text)
        it["keywordHits"] = keyword_hits(text, keywords)
        it["regions"] = matcher.match_news(text) if matcher else []
        # 키워드 그룹 맥락: 어떤 그룹의 맥락으로 쓰인 기사인지 (없으면 '맥락 불명확')
        it["groups"] = group_context(it["title"], text, settings.get("keywordGroups"))
        it["contextMatch"] = bool(it["groups"])
        if not it["contextMatch"]:
            # 그룹 맥락이 없으면 '파열'·'누수' 같은 일반 단어만으로는 상수도 사고로 분류하지 않음
            it["categories"] = classify(text, strict=True)
        if matcher and not it["regions"] and not include_unmatched:
            dropped["region"] += 1
            continue
        # 제외된 기사도 화면에서 확인할 수 있도록 표시만 하고 목록에는 남긴다
        it["excludedBy"] = exclusion_hits(text, exclude_words)
        if it["excludedBy"]:
            it["categories"] = []
            it["groups"], it["contextMatch"] = [], False
            excluded += 1
        items.append(it)
    items.sort(key=lambda x: x["publishedAt"], reverse=True)
    if dropped["date"] and not items:   # 결과가 전부 기간 밖일 때만 안내 (네이버 마지막 페이지의 옛 기사는 정상)
        errors.append(
            f"수집된 기사 중 {dropped['date']}건이 조회 기간 밖이라 제외됐습니다 "
            f"(해당 기사 발행일 {min(out_dates)} ~ {max(out_dates)}). 검색 엔진이 관련도 높은 과거 기사를 "
            "반환한 경우로, 기간을 넓히거나 키워드를 구체적으로(예: '수돗물 유충') 입력해 보세요.")
    return {"items": items, "errors": errors, "requestCount": len(tasks), "rawCount": len(raw),
            "dropped": dropped,
            "excludedCount": excluded}
