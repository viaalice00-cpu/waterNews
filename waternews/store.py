"""수집 이력 저장소 (SQLite, 표준 라이브러리).

사고 분석은 실시간 폴링·예약 조회·수동 조회로 들어온 상수도/풍수해 관련 항목을 누적해 사용한다.
data/waternews.db 에 저장되며 보관 기간(기본 90일)이 지나면 정리된다.
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import timedelta

from . import settings as settings_mod
from .net import now_kst

KEEP_DAYS = 90
_lock = threading.Lock()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    uid         TEXT PRIMARY KEY,      -- news:<id> | disaster:<sn>
    kind        TEXT NOT NULL,         -- news | disaster
    time        TEXT NOT NULL,         -- 기사 발행/문자 생성 시각 (ISO, KST)
    first_seen  TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    source      TEXT NOT NULL,         -- 언론사 또는 긴급단계·재해구분
    link        TEXT NOT NULL,
    region_text TEXT NOT NULL,
    regions     TEXT NOT NULL,         -- JSON [{basinId, basin, region}]
    categories  TEXT NOT NULL          -- JSON ["outage", ...]
);
CREATE INDEX IF NOT EXISTS idx_items_time ON items(time);
"""


def db_path():
    return os.path.join(settings_mod.DATA_DIR, "waternews.db")


@contextmanager
def _db():
    """트랜잭션 커밋 후 연결을 닫는다 (sqlite3 의 with 문은 닫지 않음)."""
    os.makedirs(settings_mod.DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(db_path(), timeout=10)
    try:
        conn.executescript(_SCHEMA)
        with conn:
            yield conn
    finally:
        conn.close()


def _row_from_news(it):
    return {
        "uid": f"news:{it['id']}", "kind": "news", "time": it.get("publishedAt") or now_kst().isoformat(),
        "title": it["title"], "body": it.get("description") or "", "source": it.get("press") or "",
        "link": it.get("link") or "", "region_text": "", "regions": it.get("regions") or [],
        "categories": it.get("categories") or [],
    }


def _row_from_disaster(it):
    src = " · ".join(x for x in (it.get("step"), it.get("disasterType")) if x)
    return {
        "uid": f"disaster:{it['sn']}", "kind": "disaster", "time": it.get("createdAt") or now_kst().isoformat(),
        "title": it["message"][:120], "body": it["message"], "source": src or "재난문자",
        "link": "", "region_text": it.get("region") or "", "regions": it.get("regions") or [],
        "categories": it.get("categories") or [],
    }


def save_news(items):
    """분류된(상수도·풍수해) 뉴스만 저장. 제외 키워드에 걸린 기사는 저장하지 않는다."""
    rows = [_row_from_news(it) for it in items if it.get("categories") and not it.get("excludedBy")]
    return _save(rows)


def save_disasters(items):
    rows = [_row_from_disaster(it) for it in items if it.get("relevant")]
    return _save(rows)


def _save(rows):
    if not rows:
        return 0
    now = now_kst().isoformat()
    with _lock, _db() as conn:
        before = conn.total_changes
        for r in rows:
            # 이미 있으면 분류·지역 정보만 갱신 (first_seen 유지)
            conn.execute(
                """INSERT INTO items (uid, kind, time, first_seen, title, body, source, link, region_text, regions, categories)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(uid) DO UPDATE SET regions=excluded.regions, categories=excluded.categories,
                     body=CASE WHEN length(excluded.body) > length(items.body) THEN excluded.body ELSE items.body END""",
                (r["uid"], r["kind"], r["time"], now, r["title"], r["body"], r["source"], r["link"],
                 r["region_text"], json.dumps(r["regions"], ensure_ascii=False),
                 json.dumps(r["categories"], ensure_ascii=False)))
        conn.execute("DELETE FROM items WHERE time < ?", ((now_kst() - timedelta(days=KEEP_DAYS)).isoformat(),))
        return conn.total_changes - before


def load(since_iso, until_iso=None):
    q = "SELECT uid, kind, time, first_seen, title, body, source, link, region_text, regions, categories FROM items WHERE time >= ?"
    args = [since_iso]
    if until_iso:
        q += " AND time < ?"
        args.append(until_iso)
    with _lock, _db() as conn:
        rows = conn.execute(q + " ORDER BY time", args).fetchall()
    keys = ["uid", "kind", "time", "firstSeen", "title", "body", "source", "link", "regionText", "regions", "categories"]
    out = []
    for r in rows:
        d = dict(zip(keys, r))
        d["regions"] = json.loads(d["regions"])
        d["categories"] = json.loads(d["categories"])
        out.append(d)
    return out


def stats():
    with _lock, _db() as conn:
        rows = conn.execute("SELECT kind, COUNT(*), MAX(first_seen) FROM items GROUP BY kind").fetchall()
    return {k: {"count": c, "lastSeen": last} for k, c, last in rows}
