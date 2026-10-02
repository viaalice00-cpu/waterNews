"""환경설정 로드/저장. 인증키는 data/settings.json 에만 저장되며 화면에는 마스킹되어 표시된다."""

import copy
import json
import os
import re
import threading

from .defaults import DEFAULT_SETTINGS

DATA_DIR = os.environ.get("WATERNEWS_DATA_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

SECRET_FIELDS = [("safetydata", "serviceKey"), ("naver", "clientId"), ("naver", "clientSecret"),
                 ("ai", "apiKey")]
ENV_FALLBACK = {
    ("safetydata", "serviceKey"): "SAFETYDATA_SERVICE_KEY",
    ("naver", "clientId"): "NAVER_CLIENT_ID",
    ("naver", "clientSecret"): "NAVER_CLIENT_SECRET",
    ("ai", "apiKey"): "ANTHROPIC_API_KEY",
}

_lock = threading.RLock()


def _path():
    return os.path.join(DATA_DIR, "settings.json")


def _merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load():
    with _lock:
        stored = {}
        if os.path.exists(_path()):
            with open(_path(), encoding="utf-8") as f:
                stored = json.load(f)
        s = _merge(DEFAULT_SETTINGS, stored)
        for (sec, key), env in ENV_FALLBACK.items():
            if not s[sec].get(key) and os.environ.get(env):
                s[sec][key] = os.environ[env]
        return s


def save(settings):
    with _lock:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = _path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, _path())


def _hint(value):
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return value[:4] + "•" * 6 + value[-4:]


def public_view(settings):
    """화면 전달용: 인증키 원문 대신 설정 여부와 일부만 노출."""
    s = copy.deepcopy(settings)
    for sec, key in SECRET_FIELDS:
        val = s[sec].get(key) or ""
        s[sec][key] = ""
        s[sec][key + "Set"] = bool(val)
        s[sec][key + "Hint"] = _hint(val)
    return s


def _str_list(values, max_len=50, limit=500):
    out, seen = [], set()
    for v in values or []:
        if not isinstance(v, str):
            continue
        v = v.strip()[:max_len]
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out[:limit]


def _int(v, default, lo, hi):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _slug(name, used):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "basin"
    slug, n = base, 2
    while slug in used:
        slug, n = f"{base}-{n}", n + 1
    return slug


def apply_update(current, payload):
    """화면에서 받은 설정을 검증해 현재 설정에 반영한 새 설정을 반환."""
    s = copy.deepcopy(current)
    payload = payload or {}

    sd = payload.get("safetydata") or {}
    if "apiUrl" in sd and isinstance(sd["apiUrl"], str):
        url = sd["apiUrl"].strip()
        if url and not url.startswith(("http://", "https://")):
            raise ValueError("재난문자 API URL은 http(s):// 로 시작해야 합니다.")
        s["safetydata"]["apiUrl"] = url or DEFAULT_SETTINGS["safetydata"]["apiUrl"]
    if "numOfRows" in sd:
        s["safetydata"]["numOfRows"] = _int(sd["numOfRows"], 1000, 10, 1000)
    if "maxPages" in sd:
        s["safetydata"]["maxPages"] = _int(sd["maxPages"], 10, 1, 50)
    if "rgnNm" in sd and isinstance(sd["rgnNm"], str):
        s["safetydata"]["rgnNm"] = sd["rgnNm"].strip()[:50]
    if "pollIntervalSec" in sd:
        s["safetydata"]["pollIntervalSec"] = _int(sd["pollIntervalSec"], 120, 30, 3600)
    for flag in ("verifySsl", "pollEnabled"):
        if flag in sd:
            s["safetydata"][flag] = bool(sd[flag])

    news = payload.get("news") or {}
    if "sources" in news:
        s["news"]["sources"] = [x for x in _str_list(news["sources"]) if x in ("google", "naver")]
    for flag in ("regionInQuery", "scheduleEnabled"):
        if flag in news:
            s["news"][flag] = bool(news[flag])
    if "naverMaxPages" in news:
        s["news"]["naverMaxPages"] = _int(news["naverMaxPages"], 5, 1, 10)
    if "scheduleIntervalMin" in news:
        s["news"]["scheduleIntervalMin"] = _int(news["scheduleIntervalMin"], 30, 5, 1440)
    if "scheduleLookbackHours" in news:
        s["news"]["scheduleLookbackHours"] = _int(news["scheduleLookbackHours"], 24, 1, 168)

    ai = payload.get("ai") or {}
    if "model" in ai:
        from .ai import AI_MODELS
        if ai["model"] not in AI_MODELS:
            raise ValueError("지원하지 않는 AI 모델입니다.")
        s["ai"]["model"] = ai["model"]

    alerts = payload.get("alerts") or {}
    if "waterOnly" in alerts:
        s["alerts"]["waterOnly"] = bool(alerts["waterOnly"])

    if "keywords" in payload:
        s["keywords"] = _str_list(payload["keywords"], max_len=30, limit=100)

    if "excludeKeywords" in payload:
        s["excludeKeywords"] = _str_list(payload["excludeKeywords"], max_len=30, limit=200)

    if "basins" in payload:
        basins, used = [], set()
        for b in payload["basins"] or []:
            name = str(b.get("name") or "").strip()[:30]
            if not name:
                continue
            bid = str(b.get("id") or "").strip()
            if not re.fullmatch(r"[a-z0-9-]{1,40}", bid) or bid in used:
                bid = _slug(name, used)
            used.add(bid)
            basins.append({
                "id": bid,
                "name": name,
                "enabled": bool(b.get("enabled")),
                "regions": _str_list(b.get("regions"), max_len=30),
            })
        s["basins"] = basins

    # 인증키: 값이 입력된 경우에만 갱신, clearSecrets 로 명시 삭제
    for sec, key in SECRET_FIELDS:
        val = (payload.get(sec) or {}).get(key)
        if isinstance(val, str) and val.strip():
            s[sec][key] = val.strip()
    for item in payload.get("clearSecrets") or []:
        sec, _, key = str(item).partition(".")
        if (sec, key) in SECRET_FIELDS:
            s[sec][key] = ""
    return s
