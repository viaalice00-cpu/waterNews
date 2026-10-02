"""수도사고 맥락 분석 (규칙 기반, 외부 라이브러리 없음).

처리 단계
 1. 실시간 데이터 수집  : store 에 누적된 뉴스·재난문자 (monitor/news 가 저장)
 2. 이해 영역 맥락 카운팅: 사고유형·원인·피해영향·대응조치·여론 5개 영역의 맥락 태그 집계
 3. 맥락 군집 요약 브리핑: 같은 지역·사고유형·시간대 항목을 하나의 '사건'으로 묶고 요약
 4. 사건 일지 & 인사이트: 사건별 시간순 일지(발생→대응→복구→여론)와 주의 신호 도출
"""

import re
from collections import Counter
from datetime import datetime, timedelta

from .classify import CATEGORY_LABELS, disaster_group_context, group_context
from .net import now_kst

# ---------------------------------------------------------------- 1. 이해 영역 사전
# (영역, [(맥락 태그, [찾을 단어])])
CONTEXT_DIMENSIONS = [
    ("사고유형", [
        # 공사·점검으로 사전 예고된 단수 — 사고성 단수와 구분 (목록 앞쪽일수록 대표 유형으로 우선)
        ("계획 단수", ["단수 예정", "단수될 예정", "단수된다", "단수 안내", "공사로 인한 단수", "공사에 따른 단수",
                    "공사로 단수", "청소로", "사전 안내"]),
        ("단수", ["단수", "급수 중단", "급수중단", "제한급수", "물 공급 중단", "공급 중단"]),
        ("관로 파열·파손", ["파열", "파손", "관로 사고", "터져", "터진"]),
        ("누수", ["누수", "물이 새", "새는"]),
        ("수질 이상", ["탁수", "적수", "흙탕물", "녹물", "이물질", "악취", "냄새", "수질", "유충", "깔따구"]),
        ("수압 저하", ["수압", "출수 불량", "물이 약"]),
        ("침수·범람", ["침수", "범람", "홍수", "물에 잠"]),
        ("설비 고장", ["정수장", "가압장", "취수장", "펌프", "배수지", "설비"]),
    ]),
    ("원인", [
        ("노후 관로", ["노후"]),
        ("공사·굴착", ["굴착", "공사 중 파손", "공사 도중", "타 공사", "중장비", "포크레인"]),
        ("동파·한파", ["동파", "한파", "결빙"]),
        ("집중호우·태풍", ["호우", "폭우", "집중호우", "태풍", "장마"]),
        ("가뭄", ["가뭄", "저수율"]),
        ("정전·기계 고장", ["정전", "고장", "오작동", "전기"]),
    ]),
    ("피해·영향", [
        ("세대·가구 피해", ["세대", "가구", "주민"]),
        ("상가·영업", ["상가", "식당", "영업", "자영업"]),
        ("학교·의료·복지", ["학교", "병원", "어린이집", "요양", "급식"]),
        ("산업·공장", ["공장", "산단", "산업단지", "기업"]),
        ("교통·도로", ["도로", "통제", "교통", "싱크홀", "침하"]),
    ]),
    ("대응·조치", [
        ("비상급수", ["급수차", "병물", "생수", "비상급수", "운반급수", "식수 지원"]),
        ("복구 작업", ["복구 중", "긴급 복구", "복구 작업", "보수 공사", "보수공사", "긴급 보수", "응급 복구"]),
        ("복구 완료", ["복구 완료", "복구를 완료", "정상 공급", "공급 재개", "정상화", "급수 재개"]),
        ("안내·사과", ["안내", "사과", "양해", "문자 발송"]),
        ("보상·감면", ["보상", "감면", "요금", "배상"]),
    ]),
    ("여론·이해관계자", [
        ("민원·항의", ["민원", "항의", "분통", "불만", "불편 호소", "빗발"]),
        ("의회·정치권", ["의회", "의원", "질타", "추궁", "행정사무감사"]),
        ("책임·원인 규명", ["책임", "감사", "원인 규명", "조사", "늑장", "부실"]),
        ("온라인 확산", ["SNS", "커뮤니티", "논란", "온라인"]),
    ]),
]
DIMENSION_NAMES = [d for d, _ in CONTEXT_DIMENSIONS]
INCIDENT_TYPES = [t for t, _ in CONTEXT_DIMENSIONS[0][1]]

# 태그 단어가 들어 있어도 반대 의미인 표현 (예: '복구 완료 시까지 급수차 운영' 은 아직 복구 전)
NEGATED_PHRASES = {
    "복구 완료": ["복구 완료 시까지", "복구 완료시까지", "복구 완료 전까지", "복구 완료 때까지", "복구 완료 예정",
                "정상 공급 시까지", "정상 공급 예정", "급수 재개 예정", "정상화 예정", "정상화될 때까지"],
}

_NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(만\s*)?(세대|가구|명|시간|곳|개소|톤|㎥)")


def context_tags(text):
    """텍스트 → {영역: [태그, ...]}"""
    text = text or ""
    out = {}
    for dim, tags in CONTEXT_DIMENSIONS:
        hits = []
        for tag, words in tags:
            t = text
            for phrase in NEGATED_PHRASES.get(tag, []):
                t = t.replace(phrase, "")
            if any(w in t for w in words):
                hits.append(tag)
        if hits:
            out[dim] = hits
    return out


def extract_numbers(text):
    """'3,000세대', '12시간' 같은 규모 수치 중 단위별 최댓값."""
    best = {}
    for num, man, unit in _NUM_RE.findall(text or ""):
        try:
            v = float(num.replace(",", ""))
        except ValueError:
            continue
        if man:
            v *= 10000
        unit = {"가구": "세대", "개소": "곳"}.get(unit, unit)
        best[unit] = max(best.get(unit, 0), v)
    return best


def _bigrams(text):
    t = re.sub(r"[^0-9a-z가-힣]", "", (text or "").lower())
    return {t[i:i + 2] for i in range(len(t) - 1)}


def similarity(a, b):
    x, y = _bigrams(a), _bigrams(b)
    return len(x & y) / len(x | y) if x and y else 0.0


def _dt(iso):
    return datetime.fromisoformat(iso)


# ---------------------------------------------------------------- 2. 항목 준비
def prepare(items, groups=None):
    """store.load() 결과에 맥락 태그·대표 지역·사고유형·키워드 그룹 맥락을 붙인다."""
    out = []
    for it in items:
        text = f"{it['title']} {it['body']}"
        if it["kind"] == "disaster":   # source = '긴급단계 · 재해구분'
            g = disaster_group_context(it["body"], it["source"].split(" · ")[-1], groups)
        else:
            g = group_context(it["title"], text, groups)
        ctx = context_tags(text)
        types = ctx.get("사고유형") or []
        if not types:  # 사전에 없으면 기본 분류로 대체
            types = [CATEGORY_LABELS.get(c, c) for c in it["categories"]][:1] or ["기타"]
        region = it["regions"][0]["region"] if it["regions"] else (it.get("regionText") or "지역 미상")
        out.append({**it, "text": text, "contexts": ctx, "incidentType": types[0],
                    "group": {k: g[0][k] for k in ("id", "name", "icon")} if g else None,
                     "region": region, "numbers": extract_numbers(text)})
    return out


def count_contexts(items):
    """영역별 태그 빈도 (항목 수 기준)."""
    counts = {d: Counter() for d in DIMENSION_NAMES}
    for it in items:
        for dim, tags in it["contexts"].items():
            counts[dim].update(tags)
    return {d: [{"tag": t, "count": c} for t, c in counts[d].most_common()] for d in DIMENSION_NAMES}


# ---------------------------------------------------------------- 3. 군집화
MAX_GAP = timedelta(hours=48)


def cluster(items, sim_threshold=0.3, now=None):
    """같은 지역에서 48시간 이내에 이어지는 같은 사고유형(또는 유사 제목) 항목을 한 사건으로 묶는다."""
    clusters = []
    for it in sorted(items, key=lambda x: x["time"]):
        t = _dt(it["time"])
        best, best_score = None, 0.0
        for c in clusters:
            if c["region"] != it["region"] or t - c["_last"] > MAX_GAP:
                continue
            score = 1.0 if c["incidentType"] == it["incidentType"] else max(
                similarity(it["title"], m["title"]) for m in c["items"])
            if score >= sim_threshold and score > best_score:
                best, best_score = c, score
        if best is None:
            best = {"region": it["region"], "incidentType": it["incidentType"], "items": [], "_last": t}
            clusters.append(best)
        best["items"].append(it)
        best["_last"] = max(best["_last"], t)
    now = now or now_kst()
    return [summarize_cluster(c, now) for c in clusters]


# ---------------------------------------------------------------- 4. 사건 요약·일지·인사이트
PHASES = [  # (단계, 판정 기준 태그) — 위에서부터 우선
    ("복구", {"복구 완료"}),
    ("여론", {"민원·항의", "의회·정치권", "책임·원인 규명", "온라인 확산"}),
    ("대응", {"비상급수", "복구 작업", "안내·사과", "보상·감면"}),
]


def phase_of(it, is_first):
    tags = {t for ts in it["contexts"].values() for t in ts}
    if is_first and "복구 완료" not in tags:
        return "발생"     # 첫 보도는 대응 내용이 섞여 있어도 '발생'으로 기록
    for name, keys in PHASES:
        if tags & keys:
            return name
    return "발생" if is_first else "확산"


def _fmt_num(v):
    return f"{int(v):,}" if v == int(v) else f"{v:,.1f}"


def _fmt_time(iso):
    return _dt(iso).strftime("%m/%d %H:%M")


QUIET_AFTER = timedelta(hours=72)   # 마지막 보도 후 이 기간 동안 새 보도가 없으면 '소강'


def summarize_cluster(c, now):
    items = sorted(c["items"], key=lambda x: x["time"])
    news = [i for i in items if i["kind"] == "news"]
    msgs = [i for i in items if i["kind"] == "disaster"]
    ctx = {d: Counter() for d in DIMENSION_NAMES}
    numbers = {}
    for it in items:
        for dim, tags in it["contexts"].items():
            ctx[dim].update(tags)
        for unit, v in it["numbers"].items():
            numbers[unit] = max(numbers.get(unit, 0), v)
    top = {d: [t for t, _ in ctx[d].most_common(3)] for d in DIMENSION_NAMES}

    # 대표 제목: 사건을 처음 알린 뉴스 (없으면 첫 재난문자). 진행 상황은 상태·일지로 표시
    title = (news or items)[0]["title"]
    group_counts = Counter(it["group"]["id"] for it in items if it["group"])
    group = next((it["group"] for it in items if it["group"] and it["group"]["id"] == group_counts.most_common(1)[0][0]),
                 None) if group_counts else None

    timeline = [{
        "time": it["time"], "kind": it["kind"], "phase": phase_of(it, i == 0),
        "title": it["title"], "source": it["source"], "link": it["link"],
        "tags": [t for ts in it["contexts"].values() for t in ts][:6],
    } for i, it in enumerate(items)]

    phases_seen = [e["phase"] for e in timeline]
    if "복구" in phases_seen[-((len(phases_seen) + 1) // 2):]:   # 최근 절반 구간에 복구 완료 보도
        status = "복구 완료"
    elif "대응" in phases_seen or "복구" in phases_seen:
        status = "대응 중"
    else:
        status = "발생"

    start, end = items[0]["time"], items[-1]["time"]
    hours = (_dt(end) - _dt(start)).total_seconds() / 3600
    elapsed = (now - _dt(start)).total_seconds() / 3600       # 최초 감지 후 경과 시간
    if status != "복구 완료" and now - _dt(end) > QUIET_AFTER:
        status = "소강"   # 복구 보도는 없지만 3일 넘게 추가 보도도 없음
    basins = sorted({r["basin"] for it in items for r in it["regions"]})
    basin_ids = sorted({r["basinId"] for it in items for r in it["regions"]})
    severe_msg = any("위급" in m["source"] or "긴급재난" in m["source"] for m in msgs)
    households = numbers.get("세대", 0)

    # 심각도 점수: 건수, 재난문자(특히 긴급·위급), 피해 규모, 여론, 장기화
    score = (len(items) + 3 * len(msgs) + (5 if severe_msg else 0) + (4 if households >= 1000 else 0)
             + (2 if sum(ctx["여론·이해관계자"].values()) else 0)
             + (3 if status in ("발생", "대응 중") and elapsed >= 24 else 0))
    severity = "높음" if score >= 14 else "보통" if score >= 6 else "낮음"

    # ---- 템플릿 브리핑 (규칙 기반 요약)
    lines = [f"[{c['region']}] {c['incidentType']} — {_fmt_time(start)} 최초 감지"
             + (f", {_fmt_time(end)}까지" if end != start else "")
             + f" 뉴스 {len(news)}건·재난문자 {len(msgs)}건."]
    if top["원인"]:
        lines.append(f"원인: {', '.join(top['원인'])} 관련 언급.")
    scale = [f"약 {_fmt_num(numbers[u])}{u}" for u in ("세대", "명", "곳") if numbers.get(u)]
    if scale or top["피해·영향"]:
        lines.append("영향: " + ", ".join(scale + top["피해·영향"]) + ".")
    if numbers.get("시간"):
        lines.append(f"지속: 최대 {_fmt_num(numbers['시간'])}시간 언급.")
    if top["대응·조치"]:
        lines.append(f"대응: {', '.join(top['대응·조치'])}.")
    if top["여론·이해관계자"]:
        lines.append(f"여론: {', '.join(top['여론·이해관계자'])} 확인.")
    lines.append(f"현재 상태: {status}.")

    cid = f"{c['region']}|{c['incidentType']}|{start}"
    return {
        "id": cid, "title": title, "region": c["region"], "incidentType": c["incidentType"],
        "group": group, "basins": basins, "basinIds": basin_ids, "start": start, "end": end, "durationHours": round(hours, 1),
        "counts": {"news": len(news), "disaster": len(msgs), "total": len(items)},
        "press": sorted({n["source"] for n in news if n["source"]}),
        "contexts": {d: [{"tag": t, "count": n} for t, n in ctx[d].most_common()] for d in DIMENSION_NAMES},
        "numbers": {u: v for u, v in numbers.items()},
        "status": status, "severity": severity, "score": score,
        "briefing": lines, "timeline": timeline, "_items": items,
        "elapsedHours": round(elapsed, 1),
        "insights": cluster_insights(items, news, msgs, ctx, numbers, status, elapsed),
    }


def cluster_insights(items, news, msgs, ctx, numbers, status, elapsed):
    out = []
    now_ref = _dt(items[-1]["time"])
    recent = [i for i in items if now_ref - _dt(i["time"]) <= timedelta(hours=6)]
    if len(recent) >= 3:
        out.append(("주의", f"최근 6시간 내 {len(recent)}건 집중 — 보도 확산 단계"))
    if status in ("발생", "대응 중") and elapsed >= 24:
        out.append(("주의", f"최초 감지 후 {int(elapsed)}시간 경과, 복구 완료 보도 없음 — 장기화 우려"))
    if status == "소강":
        out.append(("참고", "3일 이상 추가 보도 없음, 복구 완료 보도도 없음 — 실제 복구 여부 확인"))
    opinion = sum(ctx["여론·이해관계자"].values())
    if opinion >= 2:
        out.append(("주의", f"민원·의회·책임 관련 언급 {opinion}건 — 여론 대응 자료 준비 필요"))
    if numbers.get("세대", 0) >= 1000:
        out.append(("주의", f"피해 규모 약 {_fmt_num(numbers['세대'])}세대 — 대규모 사고"))
    if ctx["원인"].get("노후 관로"):
        out.append(("참고", "노후 관로 원인 언급 — 관로 교체·정비 계획 관련 문의 대비"))
    if ctx["원인"].get("공사·굴착") and not ctx["사고유형"].get("계획 단수"):
        out.append(("참고", "공사·굴착 중 파손 언급 — 시공사 책임·보상 이슈 가능"))
    if msgs and not news:
        out.append(("참고", "재난문자만 발송, 언론 보도 전 — 선제적 보도자료 대응 가능"))
    if ctx["사고유형"].get("계획 단수") and not (ctx["사고유형"].get("관로 파열·파손") or ctx["사고유형"].get("누수")):
        out.append(("참고", "사전 예고된 계획 단수 — 예정 시간 내 복구 여부만 확인"))
    if news and not msgs and status in ("발생", "대응 중"):
        out.append(("참고", "언론 보도만 있고 재난문자 없음 — 지자체 공식 안내 여부 확인"))
    if ctx["대응·조치"].get("비상급수"):
        out.append(("참고", "비상급수(급수차·병물) 진행 — 지원 물량·위치 현황 파악"))
    return [{"level": lv, "text": tx} for lv, tx in out]


def global_insights(clusters, items, prev_items, window_hours):
    out = []
    n, p = len(items), len(prev_items)
    if p and n >= p * 1.5 and n - p >= 3:
        out.append({"level": "주의", "text": f"직전 {window_hours}시간 대비 감지 건수 {p}→{n}건으로 증가"})
    elif n and not p:
        out.append({"level": "참고", "text": f"직전 {window_hours}시간에는 감지 없음 — 신규 사건 발생"})
    elif p and n <= p * 0.5:
        out.append({"level": "참고", "text": f"직전 {window_hours}시간 대비 감지 건수 {p}→{n}건으로 감소"})
    active = [c for c in clusters if c["status"] in ("발생", "대응 중")]
    if active:
        out.append({"level": "주의" if any(c["severity"] == "높음" for c in active) else "참고",
                    "text": f"진행 중 사건 {len(active)}건: " + ", ".join(f"{c['region']} {c['incidentType']}" for c in active[:5])})
    regions = Counter(c["region"] for c in clusters)
    repeat = [r for r, k in regions.items() if k >= 2 and r != "지역 미상"]
    if repeat:
        out.append({"level": "주의", "text": f"같은 지역 반복 발생: {', '.join(repeat)} — 구조적 원인 점검 필요"})
    causes = Counter(t for c in clusters for e in c["contexts"]["원인"] for t in [e["tag"]])
    if causes:
        tag, k = causes.most_common(1)[0]
        out.append({"level": "참고", "text": f"가장 많이 언급된 원인: {tag} (사건 {k}건)"})
    return out


def count_groups(items, groups):
    counts = Counter(it["group"]["id"] for it in items if it["group"])
    rows = [{"id": g["id"], "name": g["name"], "icon": g.get("icon", ""), "count": counts.get(g["id"], 0)}
            for g in groups or [] if g.get("contextTerms")]
    rows.append({"id": "", "name": "맥락 불명확", "icon": "", "count": sum(1 for it in items if not it["group"])})
    return rows


def _in_group(it, group_id):
    if not group_id:
        return True
    if group_id == "none":
        return it["group"] is None
    return bool(it["group"]) and it["group"]["id"] == group_id


def analyze(items, prev_items=None, window_hours=72, basin_ids=None, keep_items=False, now=None, groups=None,
            group_id=None):
    """분석 결과 전체.
    basin_ids: 해당 유역 항목만. group_id: 특정 키워드 그룹 맥락 항목만 ('none' = 맥락 불명확).
    그룹 분포(groups)는 그룹 필터 적용 전 기준으로 집계해 다른 그룹 건수도 함께 보여준다."""
    if basin_ids:
        items = [i for i in items if any(r["basinId"] in basin_ids for r in i["regions"])]
        prev_items = [i for i in (prev_items or []) if any(r["basinId"] in basin_ids for r in i["regions"])]
    prepared_all = prepare(items, groups)
    clusters = cluster(prepared_all, now=now)
    # 그룹 필터 버튼용: 그룹별 사건 수 (필터 적용 전)
    cluster_counts = Counter((c["group"] or {}).get("id") or "none" for c in clusters)
    cluster_counts["all"] = len(clusters)
    cluster_counts["none"] += 0          # 0건이어도 버튼에 표시
    if group_id:
        # 사건 단위로 거른다: 사건의 대표 그룹(소속 기사 다수의 그룹)이 일치하면 후속 보도까지 함께 포함
        clusters = [c for c in clusters if _in_group(c, group_id)]
        prepared = [it for c in clusters for it in c["_items"]]
        prev_items = [it for it in prepare(prev_items or [], groups) if _in_group(it, group_id)]
    else:
        prepared = prepared_all
    items = prepared
    order = {"높음": 0, "보통": 1, "낮음": 2}
    clusters.sort(key=lambda c: (c["status"] in ("복구 완료", "소강"), order[c["severity"]], -_dt(c["end"]).timestamp()))
    if not keep_items:
        for c in clusters:
            c.pop("_items", None)
    return {
        "collected": {"news": sum(i["kind"] == "news" for i in items),
                      "disaster": sum(i["kind"] == "disaster" for i in items),
                      "previous": len(prev_items or [])},
        "contexts": count_contexts(prepared),
        "groups": count_groups(prepared_all, groups),
        "groupId": group_id or "",
        "groupClusterCounts": dict(cluster_counts),
        "clusters": clusters,
        "insights": global_insights(clusters, items, prev_items or [], window_hours),
    }
