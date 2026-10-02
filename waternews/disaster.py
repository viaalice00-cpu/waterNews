"""행정안전부_긴급재난문자 (재난안전데이터 공유플랫폼 DSSP-IF-00247) 연계.

요청변수: serviceKey(필수), numOfRows, pageNo, returnType(json|xml),
         crtDt(조회시작일자 YYYYMMDD), rgnNm(지역명: 시도명, 시군구명)
출력결과: SN, CRT_DT, MSG_CN, RCPTN_RGN_NM, EMRG_STEP_NM, DST_SE_NM, REG_YMD, MDFCN_YMD
"""

import json
import math
import re
import urllib.parse
from datetime import date, datetime, timedelta

from .classify import classify, keyword_hits
from .net import KST, FetchError, http_get

OK_CODES = {"", "0", "00", "000", "200", "INFO-0", "INFO-000"}

# 공공 API 표준 오류 코드 → 조치 안내 (메시지는 재난안전데이터 공유플랫폼 서버가 보낸 것)
ERROR_HINTS = {
    "30": "재난안전데이터 공유플랫폼(safetydata.go.kr)에 등록되지 않은 키입니다. "
          "① 공공데이터포털(data.go.kr) 키가 아닌 safetydata.go.kr 마이페이지의 '행정안전부_긴급재난문자' 서비스키인지, "
          "② 이용신청이 '승인' 상태인지(승인 직후에는 반영까지 시간이 걸릴 수 있음), "
          "③ 앞뒤 공백 없이 전체를 복사했는지 확인하세요.",
    "31": "서비스키 활용 기간이 만료되었습니다. safetydata.go.kr 에서 활용 기간을 연장하세요.",
    "32": "등록되지 않은 IP에서 호출했습니다. 이용신청 정보의 허용 IP를 확인하세요.",
    "22": "일일 호출 한도를 초과했습니다. 환경설정에서 조회 주기(초)를 늘리세요.",
    "20": "서비스 접근이 거부되었습니다. 해당 데이터의 이용신청 승인 여부를 확인하세요.",
    "12": "해당 오픈API 서비스가 없거나 폐기되었습니다. 고급 설정의 API URL을 확인하세요.",
}


class DisasterApiError(Exception):
    pass


def _service_key(raw):
    key = (raw or "").strip()
    # 포털에서 URL 인코딩된 키를 복사한 경우 이중 인코딩 방지
    return urllib.parse.unquote(key) if "%" in key else key


def parse_dt(value):
    """'2024/05/27 14:33:20', '2024-05-27 14:33:20.0', '20240527143320' 등을 KST datetime 으로."""
    digits = re.findall(r"\d+", str(value or ""))
    joined = "".join(digits)
    if len(digits) >= 3 and len(digits[0]) == 4:
        parts = [int(x) for x in digits[:6]] + [0] * (6 - min(6, len(digits)))
    elif len(joined) >= 8:
        j = joined.ljust(14, "0")
        parts = [int(j[0:4]), int(j[4:6]), int(j[6:8]), int(j[8:10]), int(j[10:12]), int(j[12:14])]
    else:
        return None
    try:
        return datetime(*parts[:6], tzinfo=KST)
    except ValueError:
        return None


def _pick(raw, *keys):
    for k in keys:
        v = raw.get(k)
        if v not in (None, ""):
            return v
    return ""


def normalize(raw):
    created = parse_dt(_pick(raw, "CRT_DT", "crtDt", "create_date"))
    return {
        "sn": str(_pick(raw, "SN", "sn", "md101_sn")),
        "createdAt": created.isoformat() if created else "",
        "message": str(_pick(raw, "MSG_CN", "msgCn", "msg")).strip(),
        "region": str(_pick(raw, "RCPTN_RGN_NM", "rcptnRgnNm", "location_name")).strip(),
        "step": str(_pick(raw, "EMRG_STEP_NM", "emrgStepNm")).strip(),
        "disasterType": str(_pick(raw, "DST_SE_NM", "dstSeNm")).strip(),
        "regYmd": str(_pick(raw, "REG_YMD", "regYmd")),
        "modYmd": str(_pick(raw, "MDFCN_YMD", "mdfcnYmd")),
    }


def annotate(item, matcher, keywords):
    """분류, 키워드, 유역/지자체 매칭 정보를 덧붙인다."""
    text = item["message"]
    item["categories"] = classify(text, item.get("disasterType"))
    item["keywordHits"] = keyword_hits(text, keywords)
    item["regions"] = matcher.match_disaster(item["region"]) if matcher else []
    item["relevant"] = bool(item["categories"] or item["keywordHits"])
    return item


def parse_response(payload):
    """API 응답(JSON) → (원본 행 목록, totalCount)."""
    try:
        data = json.loads(payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload)
    except ValueError:
        text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload)
        msg = re.search(r"<(?:returnAuthMsg|resultMsg|errMsg)>([^<]+)<", text)
        raise DisasterApiError(f"JSON 이 아닌 응답: {msg.group(1) if msg else text[:200]}")

    if isinstance(data, dict) and isinstance(data.get("response"), dict):
        data = data["response"]
    header = data.get("header") or {}
    code = str(header.get("resultCode", "")).strip()
    if code not in OK_CODES:
        msg = " / ".join(str(x) for x in (header.get("resultMsg"), header.get("errorMsg")) if x)
        hint = ERROR_HINTS.get(code.lstrip("0") if code.isdigit() and len(code) > 2 else code)
        raise DisasterApiError(f"[{code}] {msg or '오류 응답'}" + (f" — {hint}" if hint else ""))

    body = data.get("body")
    if isinstance(body, dict):
        body = body.get("items") or body.get("item") or body.get("data") or []
        if isinstance(body, dict):
            body = body.get("item") or [body]
    rows = body if isinstance(body, list) else []
    total = data.get("totalCount")
    if total in (None, "") and isinstance(data.get("body"), dict):
        total = data["body"].get("totalCount")
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = len(rows)
    return rows, total


def fetch_page(sd, page_no=1, crt_dt=None, rgn_nm=None):
    key = _service_key(sd.get("serviceKey"))
    if not key:
        raise DisasterApiError("재난안전데이터 공유플랫폼 인증키(serviceKey)가 설정되지 않았습니다.")
    params = {
        "serviceKey": key,
        "returnType": "json",
        "pageNo": str(page_no),
        "numOfRows": str(sd.get("numOfRows") or 1000),
    }
    if crt_dt:
        params["crtDt"] = crt_dt
    rgn = rgn_nm if rgn_nm is not None else sd.get("rgnNm")
    if rgn:
        params["rgnNm"] = rgn
    url = f"{sd['apiUrl']}?{urllib.parse.urlencode(params)}"
    try:
        _, body = http_get(url, verify_ssl=sd.get("verifySsl", True))
    except FetchError as e:
        raise DisasterApiError(str(e)) from e
    return parse_response(body)


def fetch_messages(sd, crt_dt=None, rgn_nm=None, fetcher=fetch_page):
    """조회시작일자(crtDt) 기준으로 전체 페이지를 수집해 정규화한다."""
    num = int(sd.get("numOfRows") or 1000)
    rows, total = fetcher(sd, 1, crt_dt, rgn_nm)
    pages = min(int(sd.get("maxPages") or 10), max(1, math.ceil(total / num)))
    for page in range(2, pages + 1):
        more, _ = fetcher(sd, page, crt_dt, rgn_nm)
        if not more:
            break
        rows.extend(more)
    seen, items = set(), []
    for r in rows:
        it = normalize(r)
        if it["sn"] and it["sn"] in seen:
            continue
        seen.add(it["sn"])
        items.append(it)
    return items, total


def _in_range(item, start, end):
    if not item["createdAt"]:
        return True
    d = datetime.fromisoformat(item["createdAt"]).date()
    return start <= d <= end


def fetch_range(sd, start, end, rgn_nm=None, fetcher=fetch_page):
    """기간 조회. crtDt 가 '조회시작일 이후 전체'로 동작하면 1회, '해당일'로 동작하면 일자별 조회."""
    if end < start:
        start, end = end, start
    if (end - start).days > 30:
        raise DisasterApiError("재난문자 기간 조회는 최대 31일까지 가능합니다.")
    items, _ = fetch_messages(sd, start.strftime("%Y%m%d"), rgn_nm, fetcher)
    covers_later = any(
        it["createdAt"] and datetime.fromisoformat(it["createdAt"]).date() > start for it in items)
    if not covers_later and end > start:
        day = start + timedelta(days=1)
        seen = {it["sn"] for it in items}
        while day <= end:
            more, _ = fetch_messages(sd, day.strftime("%Y%m%d"), rgn_nm, fetcher)
            for it in more:
                if it["sn"] not in seen:
                    seen.add(it["sn"])
                    items.append(it)
            day += timedelta(days=1)
    items = [it for it in items if _in_range(it, start, end)]
    items.sort(key=lambda x: x["createdAt"], reverse=True)
    return items


def parse_date(value, default=None):
    if not value:
        return default
    return date.fromisoformat(value)
