"""데모 모드(WATERNEWS_DEMO=1): 외부 API 없이 화면을 확인하기 위한 가상 데이터.

실제 API 응답 형식(재난문자 V2 header/body, 구글 RSS, 네이버 JSON)을 그대로 흉내낸다.
"""

import itertools
import json
import random
import urllib.parse
from datetime import timedelta
from email.utils import format_datetime

from .net import now_kst

_SAMPLES = [
    ("충청남도 공주시", "안전안내", "수도",
     "[공주시] 금일 14시~22시 상수도 관로 긴급 보수공사로 신관동 일원 단수 예정. 수돗물 사전 확보 바랍니다."),
    ("전북특별자치도 정읍시", "안전안내", "수도",
     "[정읍시] 송수관 파열로 시기동·수성동 일대 단수 중. 복구 완료 시까지 급수차 운영(시청 앞)."),
    ("대전광역시 서구", "긴급재난", "호우",
     "[대전서구] 호우경보 발효 중. 갑천 하천변 산책로 출입 통제, 저지대 침수 우려 지역 주민 대피 바랍니다."),
    ("전북특별자치도 완주군", "안전안내", "수도",
     "[완주군] 정수장 설비 점검으로 봉동읍 일부 지역 탁수 발생 가능. 잠시 방류 후 사용 바랍니다."),
    ("서울특별시", "안전안내", "교통",
     "[서울시] 도심 집회로 세종대로 일대 교통 혼잡이 예상됩니다. 대중교통을 이용 바랍니다."),
    ("대구광역시 수성구", "안전안내", "수도",
     "[대구 수성구] 상수도관 누수 복구 공사로 범어동 일부 단수 (09시~15시)."),
    ("경기도 화성시", "긴급재난", "호우",
     "[화성시] 호우로 인한 하천 범람 우려. 하천 인근 주민은 안전한 곳으로 대피 바랍니다."),
    ("충청북도 청주시", "안전안내", "폭염",
     "[청주시] 폭염경보 발효 중. 야외활동 자제, 충분한 물 마시기 등 건강관리에 유의 바랍니다."),
    ("전라남도 여수시", "안전안내", "수도",
     "[여수시] 배수지 청소로 국동 일원 수압 저하 및 단수 예상. 양해 바랍니다."),
]

_counter = itertools.count(260001)
_state = {"rows": None}


def _row(sample, when):
    rgn, step, dst, msg = sample
    return {
        "SN": str(next(_counter)),
        "CRT_DT": when.strftime("%Y/%m/%d %H:%M:%S"),
        "MSG_CN": msg,
        "RCPTN_RGN_NM": rgn,
        "EMRG_STEP_NM": step,
        "DST_SE_NM": dst,
        "REG_YMD": when.strftime("%Y-%m-%d"),
        "MDFCN_YMD": when.strftime("%Y-%m-%d"),
    }


def fetch_page(sd, page_no=1, crt_dt=None, rgn_nm=None):
    """DSSP-IF-00247 응답 형식 모사. 호출마다 일정 확률로 새 문자가 추가된다."""
    now = now_kst()
    if _state["rows"] is None:
        _state["rows"] = [_row(s, now - timedelta(minutes=17 * i + 3)) for i, s in enumerate(_SAMPLES)]
    elif random.random() < 0.5:
        _state["rows"].insert(0, _row(random.choice(_SAMPLES), now))
    rows = _state["rows"]
    if crt_dt:
        rows = [r for r in rows if r["CRT_DT"].replace("/", "")[:8] >= crt_dt]
    if rgn_nm:
        rows = [r for r in rows if rgn_nm in r["RCPTN_RGN_NM"]]
    num = int(sd.get("numOfRows") or 1000)
    page = rows[(page_no - 1) * num: page_no * num]
    from .disaster import parse_response
    return parse_response(json.dumps({
        "header": {"resultMsg": "NORMAL SERVICE", "resultCode": "00", "errorMsg": None},
        "numOfRows": num, "pageNo": page_no, "totalCount": len(rows), "body": page,
    }))


_NEWS = [
    ("정읍시, 송수관 파열로 시내 일부 단수…급수차 긴급 투입", "전북일보"),
    ("공주시 신관동 상수도 관로 보수공사, 오늘 밤까지 단수", "충청투데이"),
    ("대전 갑천 홍수주의보…하천변 출입 통제", "대전일보"),
    ("완주군 봉동읍 탁수 민원 잇따라…정수장 설비 점검", "새전북신문"),
    ("화성시 집중호우로 저지대 침수 피해 접수", "경기일보"),
    ("대구 수성구 상수도관 누수 복구, 범어동 단수", "매일신문"),
    ("여수시 배수지 청소로 국동 단수 안내", "광주일보"),
    ("전주시, 노후 상수관 교체 사업 착수", "전라일보"),
    ("청주시 '물 절약' 캠페인 진행", "충북일보"),
]


def news_getter(url, headers=None, **_):
    now = now_kst()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    if "news.google.com" in url:
        items = "".join(
            f"<item><title>{t} - {p}</title><link>https://news.example.com/g/{i}</link>"
            f"<pubDate>{format_datetime(now - timedelta(hours=3 * i + 1))}</pubDate>"
            f"<source url=\"https://news.example.com\">{p}</source></item>"
            for i, (t, p) in enumerate(_NEWS) if q.get("q", [""])[0].split()[0].strip('"') in t
            or i % 3 == 0)
        return 200, f"<?xml version=\"1.0\"?><rss><channel>{items}</channel></rss>".encode()
    kw = q.get("query", [""])[0]
    items = [{
        "title": t.replace(kw, f"<b>{kw}</b>"),
        "originallink": f"https://www.news{i}.example.kr/article/{i}",
        "link": f"https://n.news.naver.com/mnews/article/{i}",
        "description": f"{p} 보도. {t}",
        "pubDate": format_datetime(now - timedelta(hours=2 * i + 2)),
    } for i, (t, p) in enumerate(_NEWS) if kw in t]
    return 200, json.dumps({"total": len(items), "start": 1, "display": len(items),
                            "items": items}).encode()
