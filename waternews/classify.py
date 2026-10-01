"""상수도 사고·단수·풍수해 분류와 유역/지자체 매칭."""

import re

CATEGORIES = [
    {
        "id": "outage",
        "label": "단수",
        "terms": ["단수", "급수 중단", "급수중단", "제한급수", "운반급수", "비상급수",
                  "급수 차질", "물 공급 중단", "수돗물 공급 중단", "병물", "생수 지원"],
    },
    {
        "id": "water_accident",
        "label": "상수도 사고",
        "terms": ["상수도", "상수관", "수도관", "송수관", "도수관", "배수관", "관로 파손",
                  "누수", "파열", "적수", "탁수", "흙탕물", "녹물", "수질사고", "수질 사고",
                  "정수장", "취수장", "가압장", "배수지", "수돗물"],
    },
    {
        "id": "flood",
        "label": "풍수해",
        "terms": ["홍수", "호우", "폭우", "집중호우", "침수", "범람", "태풍", "풍수해",
                  "제방 붕괴", "제방 유실", "댐 방류", "산사태", "하천 수위", "홍수주의보",
                  "홍수경보", "호우경보", "호우주의보"],
    },
]
CATEGORY_LABELS = {c["id"]: c["label"] for c in CATEGORIES}

# 재난문자 재해구분명(DST_SE_NM) → 분류
DST_SE_CATEGORY = {
    "수도": "water_accident",
    "홍수": "flood",
    "호우": "flood",
    "태풍": "flood",
    "산사태": "flood",
}

_SUFFIX_RE = re.compile(r"(특별자치시|특별자치도|특별시|광역시|시|군|구)$")
_CITY_SUFFIXES = ("특별자치시", "특별자치도", "특별시", "광역시")

# 핵심 지명이 일반 명사와 겹치는 시(市) — 뉴스에서는 '화성시'처럼 전체 명칭으로만 매칭
AMBIGUOUS_CITY_CORES = {"광주", "화성", "양산", "하남", "구리", "과천", "오산", "고양", "광명"}


def _split(region):
    name = (region or "").strip()
    m = _SUFFIX_RE.search(name)
    if not m or len(name) - len(m.group(1)) < 2:
        return name, None, None
    return name, name[: m.start()], m.group(1)


def news_term(region):
    """뉴스 본문에서 찾을 지명. 예) 정읍시→정읍, 완주군→완주군, 대전광역시→대전."""
    name, core, suffix = _split(region)
    if not core:
        return name
    if suffix in _CITY_SUFFIXES:
        return core
    if suffix == "시" and core not in AMBIGUOUS_CITY_CORES:
        return core
    return name


def disaster_pattern(region):
    """재난문자 수신지역명(RCPTN_RGN_NM)에 쓸 정규식.

    '서울시'처럼 약칭으로 입력해도 '서울특별시'와 매칭되도록 시 계열 접미사를 허용한다.
    """
    name, core, suffix = _split(region)
    if core and (suffix == "시" or suffix in _CITY_SUFFIXES):
        return re.compile(re.escape(core) + r"(특별자치시|특별자치도|특별시|광역시|시)")
    return re.compile(re.escape(name))


def classify(text, dst_se_nm=None):
    """텍스트에서 분류 id 목록을 반환한다."""
    text = text or ""
    found = []
    for cat in CATEGORIES:
        if any(t in text for t in cat["terms"]):
            found.append(cat["id"])
    extra = DST_SE_CATEGORY.get((dst_se_nm or "").strip())
    if extra and extra not in found:
        found.append(extra)
    return found


def keyword_hits(text, keywords):
    text = text or ""
    return [k for k in keywords if k and k in text]


class RegionMatcher:
    """유역 설정으로부터 뉴스/재난문자 지역 매칭기를 만든다."""

    def __init__(self, basins, basin_ids=None):
        self.entries = []
        for b in basins:
            if basin_ids is not None and b["id"] not in basin_ids:
                continue
            for r in b.get("regions", []):
                if not r.strip():
                    continue
                self.entries.append({
                    "basinId": b["id"],
                    "basin": b["name"],
                    "region": r.strip(),
                    "term": news_term(r),
                    "pattern": disaster_pattern(r),
                })

    def __bool__(self):
        return bool(self.entries)

    def news_terms(self):
        seen, out = set(), []
        for e in self.entries:
            if e["term"] not in seen:
                seen.add(e["term"])
                out.append(e["term"])
        return out

    @staticmethod
    def _pack(hits):
        return [{"basinId": e["basinId"], "basin": e["basin"], "region": e["region"]} for e in hits]

    def match_news(self, text):
        text = text or ""
        return self._pack([e for e in self.entries if e["term"] in text])

    def match_disaster(self, region_text):
        region_text = region_text or ""
        return self._pack([e for e in self.entries if e["pattern"].search(region_text)])
