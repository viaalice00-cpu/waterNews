import json
import os
import tempfile
import unittest
from datetime import date
from email.utils import format_datetime
from datetime import datetime

from waternews import disaster, news, settings
from waternews.classify import RegionMatcher, classify, disaster_pattern, exclusion_hits, news_term
from waternews.defaults import DEFAULT_SETTINGS
from waternews.net import KST

SAMPLE = {
    "header": {"resultMsg": "NORMAL SERVICE", "resultCode": "00", "errorMsg": None},
    "numOfRows": 2, "pageNo": 1, "totalCount": 3,
    "body": [
        {"SN": "215001", "CRT_DT": "2026/10/01 09:12:33",
         "MSG_CN": "[정읍시] 송수관 파열로 시기동 일대 단수 중. 급수차 운영.",
         "RCPTN_RGN_NM": "전북특별자치도 정읍시", "EMRG_STEP_NM": "안전안내",
         "DST_SE_NM": "수도", "REG_YMD": "2026-10-01", "MDFCN_YMD": "2026-10-01"},
        {"SN": "215002", "CRT_DT": "2026/10/01 10:00:00",
         "MSG_CN": "[서울시] 도심 집회로 교통 혼잡 예상.",
         "RCPTN_RGN_NM": "서울특별시", "EMRG_STEP_NM": "안전안내",
         "DST_SE_NM": "교통", "REG_YMD": "2026-10-01", "MDFCN_YMD": "2026-10-01"},
    ],
}


class DisasterApiTest(unittest.TestCase):
    def test_parse_v2_response(self):
        rows, total = disaster.parse_response(json.dumps(SAMPLE).encode())
        self.assertEqual(total, 3)
        it = disaster.normalize(rows[0])
        self.assertEqual(it["sn"], "215001")
        self.assertEqual(it["createdAt"], "2026-10-01T09:12:33+09:00")
        self.assertEqual(it["region"], "전북특별자치도 정읍시")
        self.assertEqual(it["step"], "안전안내")
        self.assertEqual(it["disasterType"], "수도")

    def test_error_header(self):
        bad = {"header": {"resultCode": "30", "resultMsg": "SERVICE KEY IS NOT REGISTERED", "errorMsg": "등록되지 않은 키"}}
        with self.assertRaisesRegex(disaster.DisasterApiError, "SERVICE KEY"):
            disaster.parse_response(json.dumps(bad).encode())

    def test_non_json(self):
        with self.assertRaisesRegex(disaster.DisasterApiError, "SERVICE_KEY_IS_NOT_REGISTERED"):
            disaster.parse_response(b"<OpenAPI_ServiceResponse><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED</returnAuthMsg>")

    def test_parse_dt_formats(self):
        for v in ("2026/10/01 09:12:33", "2026-10-01 09:12:33.0", "20261001091233"):
            self.assertEqual(disaster.parse_dt(v).isoformat(), "2026-10-01T09:12:33+09:00")

    def test_pagination_and_dedupe(self):
        calls = []

        def fetcher(sd, page, crt, rgn):
            calls.append((page, crt))
            rows = SAMPLE["body"] if page == 1 else [SAMPLE["body"][0]]
            return list(rows), 3

        sd = {**DEFAULT_SETTINGS["safetydata"], "serviceKey": "k", "numOfRows": 2}
        items, total = disaster.fetch_messages(sd, "20261001", None, fetcher)
        self.assertEqual([c[0] for c in calls], [1, 2])
        self.assertEqual(len(items), 2)

    def test_range_exact_day_semantics(self):
        """crtDt 가 해당일만 반환하는 경우 일자별로 추가 조회한다."""
        days = []

        def fetcher(sd, page, crt, rgn):
            days.append(crt)
            row = dict(SAMPLE["body"][0], SN=crt, CRT_DT=f"{crt[:4]}/{crt[4:6]}/{crt[6:]} 08:00:00")
            return [row], 1

        sd = {**DEFAULT_SETTINGS["safetydata"], "serviceKey": "k"}
        items = disaster.fetch_range(sd, date(2026, 9, 28), date(2026, 9, 30), fetcher=fetcher)
        self.assertEqual(days, ["20260928", "20260929", "20260930"])
        self.assertEqual([i["sn"] for i in items], ["20260930", "20260929", "20260928"])

    def test_service_key_unquote(self):
        self.assertEqual(disaster._service_key("ab%2Bcd%3D%3D"), "ab+cd==")
        self.assertEqual(disaster._service_key(" abc "), "abc")


class ClassifyTest(unittest.TestCase):
    def test_terms(self):
        self.assertEqual(news_term("정읍시"), "정읍")
        self.assertEqual(news_term("대전광역시"), "대전")
        self.assertEqual(news_term("완주군"), "완주군")
        self.assertEqual(news_term("화성시"), "화성시")   # 동음이의어 방지
        self.assertEqual(news_term("옥천"), "옥천")       # 별칭 그대로

    def test_disaster_pattern_aliases(self):
        self.assertTrue(disaster_pattern("서울시").search("서울특별시 전체"))
        self.assertTrue(disaster_pattern("대구시").search("대구광역시 수성구"))
        self.assertTrue(disaster_pattern("세종특별자치시").search("세종특별자치시"))
        self.assertFalse(disaster_pattern("광주광역시").search("경기도 성남시"))

    def test_larvae_needs_water_context(self):
        self.assertIn("water_accident", classify("정수장 유충 발견, 위생관리 구멍"))
        self.assertEqual(classify("털진드기 유충이 매개하는 쯔쯔가무시증 주의"), [])

    def test_categories(self):
        self.assertEqual(classify("송수관 파열로 단수"), ["outage", "water_accident"])
        self.assertEqual(classify("호우경보 발효"), ["flood"])
        self.assertEqual(classify("점검 안내", "수도"), ["water_accident"])
        self.assertEqual(classify("교통 혼잡"), [])

    def test_matcher(self):
        m = RegionMatcher(DEFAULT_SETTINGS["basins"], {"geum"})
        hits = m.match_disaster("전북특별자치도 정읍시")
        self.assertEqual(hits[0]["basin"], "금강유역")
        self.assertEqual(m.match_disaster("서울특별시"), [])
        self.assertTrue(m.match_news("정읍 시기동 단수"))
        self.assertFalse(m.match_news("예산 편성 회의"))   # 예산군은 전체 명칭만


class ExclusionTest(unittest.TestCase):
    EX = DEFAULT_SETTINGS["excludeKeywords"]

    def test_political_homonym_excluded(self):
        hits = exclusion_hits('국민의힘 대전·충남 사고당협 단수 임명도 제외…"추가 논의"', self.EX)
        self.assertIn("당협", hits)
        self.assertIn("단수 임명", hits)
        self.assertTrue(exclusion_hits("민주당 대전 유성을 단수공천 확정", self.EX))
        self.assertTrue(exclusion_hits("바둑 신예, 단수 묘수로 역전승", self.EX))

    def test_real_outage_kept(self):
        self.assertEqual(exclusion_hits("정읍시 시기동 일대 단수…급수차 투입", self.EX), [])
        # 정치인이 등장해도 상수도 맥락이 있으면 유지
        self.assertEqual(exclusion_hits("대전 단수 사태에 국민의힘 시의원 '수돗물 공급 대책' 촉구", self.EX), [])

    def test_custom_list(self):
        self.assertEqual(exclusion_hits("단수 임명 논란", []), [])
        self.assertEqual(exclusion_hits("단수 임명 논란", ["임명"]), ["임명"])


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = settings.DATA_DIR
        settings.DATA_DIR = self.tmp.name

    def tearDown(self):
        settings.DATA_DIR = self._orig
        self.tmp.cleanup()

    def test_secret_masking_and_update(self):
        s = settings.load()
        s = settings.apply_update(s, {"safetydata": {"serviceKey": "ABCDEFGH12345678"}})
        settings.save(s)
        view = settings.public_view(settings.load())
        self.assertEqual(view["safetydata"]["serviceKey"], "")
        self.assertTrue(view["safetydata"]["serviceKeySet"])
        self.assertEqual(view["safetydata"]["serviceKeyHint"], "ABCD••••••5678")
        # 빈 값 전송 시 유지, clearSecrets 로 삭제
        s = settings.apply_update(s, {"safetydata": {"serviceKey": ""}})
        self.assertEqual(s["safetydata"]["serviceKey"], "ABCDEFGH12345678")
        s = settings.apply_update(s, {"clearSecrets": ["safetydata.serviceKey"]})
        self.assertEqual(s["safetydata"]["serviceKey"], "")

    def test_keywords_and_basins(self):
        s = settings.apply_update(settings.load(), {
            "keywords": ["단수", " 단수 ", "적수", ""],
            "basins": [{"id": "geum", "name": "금강유역", "enabled": True, "regions": ["정읍시", "정읍시"]},
                       {"id": "", "name": "새만금유역", "enabled": False, "regions": ["군산시"]}],
            "safetydata": {"pollIntervalSec": 5},
        })
        self.assertEqual(s["keywords"], ["단수", "적수"])
        self.assertEqual(s["basins"][0]["regions"], ["정읍시"])
        self.assertTrue(s["basins"][1]["id"])
        self.assertEqual(s["safetydata"]["pollIntervalSec"], 30)

    def test_exclude_keywords_update(self):
        s = settings.load()
        self.assertIn("공천", s["excludeKeywords"])   # 기존 설정 파일에도 기본값이 채워짐
        s = settings.apply_update(s, {"excludeKeywords": ["공천", " 당협 ", "공천"]})
        self.assertEqual(s["excludeKeywords"], ["공천", "당협"])


class NewsTest(unittest.TestCase):
    def test_google_query(self):
        q = news.google_query("수도관 파열", ["정읍", "완주군"], date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(q, '"수도관 파열" (정읍 OR 완주군) after:2026-09-01 before:2026-10-01')

    def test_google_query_recent_uses_when(self):
        q = news.google_query("유충", [], date(2026, 9, 29), date(2026, 10, 2), today=date(2026, 10, 2))
        self.assertEqual(q, "유충 when:4d")

    def test_out_of_range_articles_are_reported(self):
        old = format_datetime(datetime(2020, 7, 15, 10, 0, tzinfo=KST))
        rss = (f"<rss><channel><item><title>인천 수돗물 유충 사태 - A</title><link>https://g/1</link>"
               f"<pubDate>{old}</pubDate><source url='x'>A</source></item></channel></rss>").encode()
        s = json.loads(json.dumps(DEFAULT_SETTINGS))
        res = news.search_news(s, ["유충"], date(2026, 9, 29), date(2026, 10, 2), ["google"],
                               getter=lambda *a, **k: (200, rss))
        self.assertEqual(res["items"], [])
        self.assertEqual(res["dropped"]["date"], 1)
        self.assertTrue(any("2020-07-15" in e for e in res["errors"]))

    def test_search_merges_and_filters(self):
        pub = format_datetime(datetime(2026, 9, 30, 10, 0, tzinfo=KST))
        old = format_datetime(datetime(2026, 8, 1, 10, 0, tzinfo=KST))

        def getter(url, headers=None, **_):
            if "news.google.com" in url:
                return 200, (f"<rss><channel>"
                             f"<item><title>정읍시 송수관 파열로 단수 - 전북일보</title><link>https://g/1</link>"
                             f"<pubDate>{pub}</pubDate><source url='x'>전북일보</source></item>"
                             f"<item><title>서울 단수 소식 - A</title><link>https://g/2</link>"
                             f"<pubDate>{pub}</pubDate><source url='x'>A</source></item>"
                             f"<item><title>국민의힘 대전·충남 사고당협 단수 임명도 제외 - B</title><link>https://g/3</link>"
                             f"<pubDate>{pub}</pubDate><source url='x'>A</source></item>"
                             f"</channel></rss>").encode()
            return 200, json.dumps({"total": 2, "items": [
                {"title": "<b>정읍시</b> 송수관 파열로 단수", "originallink": "https://www.jjan.kr/1",
                 "link": "https://n/1", "description": "시기동 일대", "pubDate": pub},
                {"title": "정읍 옛 기사", "originallink": "https://x/2", "link": "", "description": "", "pubDate": old},
            ]}).encode()

        s = json.loads(json.dumps(DEFAULT_SETTINGS))
        s["naver"] = {"clientId": "i", "clientSecret": "s"}
        m = RegionMatcher(s["basins"], {"geum"})
        res = news.search_news(s, ["단수"], date(2026, 9, 24), date(2026, 9, 30),
                               ["google", "naver"], m, getter=getter)
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["excludedCount"], 1)
        kept = [i for i in res["items"] if not i["excludedBy"]]
        self.assertEqual(len(kept), 1)
        dropped = [i for i in res["items"] if i["excludedBy"]][0]
        self.assertEqual(dropped["categories"], [])
        it = kept[0]
        self.assertEqual(sorted(it["sources"]), ["google", "naver"])
        self.assertEqual(it["press"], "전북일보")
        self.assertIn("outage", it["categories"])
        self.assertEqual(it["regions"][0]["region"], "정읍시")

    def test_naver_without_keys_reports(self):
        s = json.loads(json.dumps(DEFAULT_SETTINGS))
        res = news.search_news(s, ["단수"], date(2026, 9, 24), date(2026, 9, 30), ["naver"],
                               getter=lambda *a, **k: (200, b"{}"))
        self.assertTrue(res["errors"])


if __name__ == "__main__":
    unittest.main()
