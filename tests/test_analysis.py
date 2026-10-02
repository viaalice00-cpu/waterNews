import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from waternews import ai, analysis, settings, store
from waternews.classify import disaster_group_context
from waternews.defaults import DEFAULT_KEYWORD_GROUPS
from waternews.net import KST

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=KST)
GEUM = [{"basinId": "geum", "basin": "금강유역", "region": "정읍시"}]


def item(h, title, body="", kind="news", regions=GEUM, source="전북일보", cats=("outage",)):
    return {"uid": f"{kind}:{h}:{title[:5]}", "kind": kind, "time": (T0 + timedelta(hours=h)).isoformat(),
            "firstSeen": "", "title": title, "body": body, "source": source, "link": "",
            "regionText": "", "regions": regions, "categories": list(cats)}


JEONGEUP = [
    item(0, "정읍시 송수관 파열로 단수", "노후 송수관 파열로 3,200세대 단수. 급수차 투입, 긴급 복구 작업"),
    item(1, "[정읍시] 송수관 파열로 단수 중. 복구 완료 시까지 급수차 운영", kind="disaster", source="안전안내 · 수도"),
    item(12, "정읍 단수 12시간째 민원 빗발", "주민 불편 호소, 상가 영업 차질"),
    item(20, "정읍시의회 늑장 대응 질타", "의원들 책임 규명 요구"),
    item(26, "정읍시 단수 복구 완료…정상 공급 재개", "요금 감면 검토"),
]


class ContextTest(unittest.TestCase):
    def test_tags_and_negation(self):
        ctx = analysis.context_tags("노후 송수관 파열로 단수. 복구 완료 시까지 급수차 운영")
        self.assertIn("관로 파열·파손", ctx["사고유형"])
        self.assertIn("노후 관로", ctx["원인"])
        self.assertEqual(ctx["대응·조치"], ["비상급수"])   # '복구 완료 시까지' 는 복구 완료 아님

    def test_planned_outage_is_not_construction_accident(self):
        ctx = analysis.context_tags("관로 보수공사로 신관동 일원 단수 예정")
        self.assertIn("계획 단수", ctx["사고유형"])
        self.assertNotIn("원인", ctx)

    def test_numbers(self):
        self.assertEqual(analysis.extract_numbers("약 3,200세대, 1만 가구, 12시간"),
                         {"세대": 10000.0, "시간": 12.0})


class ClusterTest(unittest.TestCase):
    def test_incident_cluster_timeline_and_insights(self):
        other = item(2, "공주시 관로 보수공사로 단수 예정", regions=[{**GEUM[0], "region": "공주시"}])
        later = item(100, "정읍시 또 단수", "송수관 파열")    # 48시간 넘게 떨어진 재발 → 별도 사건
        res = analysis.analyze(JEONGEUP + [other, later], [], 168, now=T0 + timedelta(hours=101))
        by_region = {}
        for c in res["clusters"]:
            by_region.setdefault(c["region"], []).append(c)
        self.assertEqual(len(by_region["정읍시"]), 2)
        c = min(by_region["정읍시"], key=lambda x: x["start"])
        self.assertEqual(c["counts"], {"news": 4, "disaster": 1, "total": 5})
        self.assertEqual(c["title"], "정읍시 송수관 파열로 단수")
        self.assertEqual(c["status"], "복구 완료")
        self.assertEqual([e["phase"] for e in c["timeline"]], ["발생", "대응", "여론", "여론", "복구"])
        self.assertEqual(c["numbers"]["세대"], 3200)
        texts = " ".join(i["text"] for i in c["insights"])
        self.assertIn("여론 대응", texts)
        self.assertIn("대규모", texts)
        self.assertTrue(any("반복 발생" in i["text"] for i in res["insights"]))
        self.assertNotIn("_items", c)

    def test_ongoing_long_incident_flagged(self):
        # 최초 감지 30시간 후: 복구 보도가 없으면 장기화 경고
        c = analysis.analyze(JEONGEUP[:4], [], 72, now=T0 + timedelta(hours=30))["clusters"][0]
        self.assertEqual(c["status"], "대응 중")
        self.assertTrue(any("장기화" in i["text"] for i in c["insights"]))
        # 마지막 보도 후 3일 넘게 조용하면 '소강'
        c = analysis.analyze(JEONGEUP[:4], [], 720, now=T0 + timedelta(hours=20 + 80))["clusters"][0]
        self.assertEqual(c["status"], "소강")
        self.assertFalse(any("장기화" in i["text"] for i in c["insights"]))

    def test_basin_filter_and_trend(self):
        han = item(3, "서울 단수", regions=[{"basinId": "han", "basin": "한강유역", "region": "서울특별시"}])
        res = analysis.analyze(JEONGEUP + [han], JEONGEUP[:1], 72, basin_ids={"han"})
        self.assertEqual([c["region"] for c in res["clusters"]], ["서울특별시"])


class GroupFilterTest(unittest.TestCase):
    G = DEFAULT_KEYWORD_GROUPS

    def test_disaster_group_falls_back_to_type(self):
        # 문자 내용만으로는 수도 맥락 단어가 1개뿐이지만 재해구분 '수도' 로 수도 그룹
        g = disaster_group_context("[정읍시] 시기동 일대 단수 안내", "수도", self.G)
        self.assertEqual(g[0]["id"], "water")
        self.assertEqual(g[0]["terms"], ["재해구분: 수도"])
        self.assertEqual(disaster_group_context("호우경보 발효 중", "호우", self.G)[0]["id"], "flood")
        self.assertEqual(disaster_group_context("도심 집회로 교통 혼잡", "교통", self.G), [])

    def test_analyze_by_group(self):
        flood = item(5, "대전 집중호우로 도로 침수", "하천 범람 우려 주민 대피",
                     regions=[{**GEUM[0], "region": "대전광역시"}], cats=("flood",))
        now = T0 + timedelta(hours=30)
        res = analysis.analyze(JEONGEUP + [flood], [], 72, now=now, groups=self.G, group_id="flood")
        self.assertEqual([c["region"] for c in res["clusters"]], ["대전광역시"])
        self.assertEqual(res["collected"]["news"], 1)
        counts = {g["id"]: g["count"] for g in res["groups"]}      # 분포는 필터 전 기준
        self.assertEqual(counts["flood"], 1)
        self.assertEqual(res["groupClusterCounts"], {"water": 1, "flood": 1, "none": 0, "all": 2})
        self.assertEqual(counts["water"], 2)                       # 기사 단위로는 수도 맥락 2건
        res = analysis.analyze(JEONGEUP + [flood], [], 72, now=now, groups=self.G, group_id="water")
        self.assertEqual({c["region"] for c in res["clusters"]}, {"정읍시"})
        # 사건 단위 필터라 맥락 단어가 부족한 후속 보도(민원·의회 질타)도 사건에 포함
        self.assertEqual(res["clusters"][0]["counts"]["total"], 5)
        self.assertEqual(res["collected"]["news"] + res["collected"]["disaster"], 5)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = settings.DATA_DIR
        settings.DATA_DIR = self.tmp.name

    def tearDown(self):
        settings.DATA_DIR = self._orig
        self.tmp.cleanup()

    def test_save_and_load(self):
        now = datetime.now(KST)
        news_items = [
            {"id": "a", "title": "정읍 단수", "description": "송수관 파열", "press": "A", "link": "x",
             "publishedAt": now.isoformat(), "regions": GEUM, "categories": ["outage"], "excludedBy": []},
            {"id": "b", "title": "단수 임명", "description": "", "press": "B", "link": "y",
             "publishedAt": now.isoformat(), "regions": [], "categories": [], "excludedBy": ["당협"]},
        ]
        msgs = [{"sn": "1", "createdAt": now.isoformat(), "message": "단수 안내", "region": "전북 정읍시",
                 "step": "안전안내", "disasterType": "수도", "regions": GEUM, "categories": ["outage"],
                 "relevant": True},
                {"sn": "2", "createdAt": now.isoformat(), "message": "교통 혼잡", "region": "서울",
                 "step": "안전안내", "disasterType": "교통", "regions": [], "categories": [], "relevant": False}]
        self.assertEqual(store.save_news(news_items), 1)
        self.assertEqual(store.save_disasters(msgs), 1)
        store.save_news(news_items)                          # 중복 저장 무시
        rows = store.load((now - timedelta(hours=1)).isoformat())
        self.assertEqual(sorted(r["uid"] for r in rows), ["disaster:1", "news:a"])
        self.assertEqual(rows[0]["regions"][0]["region"], "정읍시")
        self.assertEqual(store.stats()["news"]["count"], 1)


class FakeMessages:
    def __init__(self, stop="end_turn"):
        self.calls, self.stop = [], stop

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason=self.stop, model=kw["model"],
                               content=[SimpleNamespace(type="text", text="## 상황 요약\n- 정읍시 단수")])


@unittest.skipUnless(importlib.util.find_spec("anthropic"), "anthropic SDK 미설치")
class AITest(unittest.TestCase):
    def _client(self, stop="end_turn"):
        fake = FakeMessages(stop)
        return SimpleNamespace(messages=fake, beta=SimpleNamespace(messages=fake)), fake

    def test_opus_uses_fallbacks_and_effort(self):
        res = analysis.analyze(JEONGEUP, [], 72, keep_items=True)
        c = res["clusters"][0]
        client, fake = self._client()
        out = ai.generate_briefing(c, c["_items"], model="claude-opus-5-5", client=client)
        self.assertIn("상황 요약", out["text"])
        kw = fake.calls[0]
        self.assertEqual(kw["fallbacks"], "default")
        self.assertEqual(kw["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(kw["output_config"], {"effort": "medium"})
        self.assertIn("송수관 파열", kw["messages"][0]["content"])

    def test_haiku_has_no_effort_and_refusal_raises(self):
        res = analysis.analyze(JEONGEUP, [], 72, keep_items=True)
        c = res["clusters"][0]
        client, fake = self._client()
        ai.generate_briefing(c, c["_items"], model="claude-haiku-4-5", client=client)
        self.assertNotIn("output_config", fake.calls[0])
        self.assertNotIn("fallbacks", fake.calls[0])
        client, _ = self._client(stop="refusal")
        with self.assertRaises(ai.AIError):
            ai.generate_briefing(c, c["_items"], client=client)


if __name__ == "__main__":
    unittest.main()
