import json
import os


def custom_keywords(s):
    """'사용자 설정 키워드' 그룹의 키워드 (이전 버전의 단일 키워드 목록이 옮겨지는 곳)."""
    return next(g for g in s["keywordGroups"] if g["id"] == "custom")["keywords"]
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
        with self.assertRaisesRegex(disaster.DisasterApiError, "SERVICE KEY.*safetydata.go.kr 마이페이지"):
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


class KeywordGroupTest(unittest.TestCase):
    G = DEFAULT_SETTINGS["keywordGroups"]

    def test_context_needs_two_distinct_terms(self):
        from waternews.classify import group_context
        self.assertEqual(group_context("단수 공천 확정", "단수 공천 확정", self.G), [])
        self.assertEqual(group_context("노사 협상 파열", "노사 협상 파열", self.G), [])
        hit = group_context("정읍 단수", "정읍 단수…급수차 투입", self.G)
        self.assertEqual(hit[0]["id"], "water")
        self.assertEqual(group_context("도로 침수", "집중호우로 도로 침수", self.G)[0]["id"], "flood")

    def test_title_terms_weigh_more(self):
        from waternews.classify import group_context
        text = "하천 범람 우려 — 상수도 관로 점검도"
        hits = group_context("하천 범람 우려", text, self.G)
        self.assertEqual([h["id"] for h in hits], ["flood", "water"])

    def test_group_update_and_scheduled_keywords(self):
        s = settings.apply_update(json.loads(json.dumps(DEFAULT_SETTINGS)), {
            "keywordGroups": [
                {"id": "water", "name": "수도", "keywords": ["단수", "단수"], "contextTerms": ["단수", "급수"],
                 "scheduled": True},
                {"id": "", "name": "새 그룹", "keywords": ["가뭄"], "contextTerms": ["가뭄", "저수율"],
                 "scheduled": False, "minTerms": 9},
                {"id": "x", "name": "", "keywords": ["무시"]},
            ]})
        self.assertEqual([g["name"] for g in s["keywordGroups"]], ["수도", "새 그룹"])
        self.assertTrue(s["keywordGroups"][1]["id"])
        self.assertEqual(s["keywordGroups"][1]["minTerms"], 5)
        self.assertEqual(s["keywords"], ["단수", "가뭄"])
        self.assertEqual(settings.scheduled_keywords(s), ["단수"])

    def test_news_items_carry_group_context(self):
        pub = format_datetime(datetime(2026, 9, 30, 10, 0, tzinfo=KST))
        rss = (f"<rss><channel>"
               f"<item><title>정읍시 송수관 파열로 단수 - A</title><link>https://g/1</link><pubDate>{pub}</pubDate><source url='x'>A</source></item>"
               f"<item><title>노사 협상 파열 - B</title><link>https://g/2</link><pubDate>{pub}</pubDate><source url='x'>B</source></item>"
               f"</channel></rss>").encode()
        s = json.loads(json.dumps(DEFAULT_SETTINGS))
        res = news.search_news(s, ["파열"], date(2026, 9, 24), date(2026, 9, 30), ["google"],
                               getter=lambda *a, **k: (200, rss))
        by = {i["title"]: i for i in res["items"]}
        self.assertTrue(by["정읍시 송수관 파열로 단수"]["contextMatch"])
        self.assertEqual(by["정읍시 송수관 파열로 단수"]["groups"][0]["id"], "water")
        self.assertFalse(by["노사 협상 파열"]["contextMatch"])
        self.assertEqual(by["노사 협상 파열"]["categories"], [])         # '파열' 만으로는 상수도 사고 아님
        self.assertIn("water_accident", by["정읍시 송수관 파열로 단수"]["categories"])


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
        self.assertEqual(custom_keywords(s), ["단수", "적수"])
        self.assertIn("적수", s["keywords"])                  # 전체 키워드 = 모든 그룹의 합집합
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


class NaverRateLimitTest(unittest.TestCase):
    RATE = '{"errorMessage":"Rate limit exceeded. (속도 제한을 초과했습니다.)","errorCode":"012"}'
    DAILY = '{"errorMessage":"Query limit exceeded.","errorCode":"010"}'

    def setUp(self):
        self._interval = news.naver_throttle.interval
        news.naver_throttle.interval = 0.0

    def tearDown(self):
        news.naver_throttle.interval = self._interval

    def _getter(self, failures, body):
        calls = []

        def getter(url, headers=None, **_):
            calls.append(url)
            if len(calls) <= failures:
                raise news.FetchError(f"HTTP 429: {body}", status=429, body=body)
            return 200, b'{"total": 0, "items": []}'
        return getter, calls

    def test_rate_limit_retries_with_backoff(self):
        getter, calls = self._getter(2, self.RATE)
        slept = []
        status, _ = news.naver_get("u", {}, getter, sleep=slept.append)
        self.assertEqual(status, 200)
        self.assertEqual(len(calls), 3)
        self.assertEqual(slept, [1, 2])

    def test_rate_limit_gives_up_with_clear_message(self):
        getter, calls = self._getter(99, self.RATE)
        with self.assertRaisesRegex(news.FetchError, "속도 제한"):
            news.naver_get("u", {}, getter, sleep=lambda s: None)
        self.assertEqual(len(calls), news.NAVER_RETRIES + 1)

    def test_daily_quota_is_not_retried(self):
        getter, calls = self._getter(99, self.DAILY)
        with self.assertRaisesRegex(news.FetchError, "일일 호출 한도"):
            news.naver_get("u", {}, getter, sleep=lambda s: self.fail("일일 한도는 재시도하지 않음"))
        self.assertEqual(len(calls), 1)

    def test_throttle_spaces_concurrent_calls(self):
        import threading
        import time
        t = news._Throttle(0.05)
        stamps = []
        lock = threading.Lock()

        def worker():
            t.wait()
            with lock:
                stamps.append(time.monotonic())
        threads = [threading.Thread(target=worker) for _ in range(6)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        stamps.sort()
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        self.assertGreaterEqual(min(gaps), 0.045)


class DataLocationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.legacy = os.path.join(self.tmp.name, "program", "data")
        self.new = os.path.join(self.tmp.name, "appdata", "waterNews")
        os.makedirs(self.legacy)
        self._orig = settings.DATA_DIR
        settings.DATA_DIR = self.new

    def tearDown(self):
        settings.DATA_DIR = self._orig
        self.tmp.cleanup()

    def test_default_dir_is_outside_program_folder(self):
        env = os.environ.pop("WATERNEWS_DATA_DIR", None)
        try:
            d = os.path.realpath(settings.default_data_dir())
            program = os.path.realpath(os.path.dirname(settings.LEGACY_DATA_DIR))
            self.assertFalse(d.startswith(program + os.sep), d)
            self.assertTrue(d.endswith("waterNews"))
        finally:
            if env is not None:
                os.environ["WATERNEWS_DATA_DIR"] = env

    def test_migrates_legacy_settings_once_without_overwriting(self):
        with open(os.path.join(self.legacy, "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"keywords": ["옛설정"], "safetydata": {"serviceKey": "OLDKEY"}}, f)
        self.assertEqual(settings.migrate_legacy(self.legacy), ["settings.json"])
        s = settings.load()
        self.assertEqual(custom_keywords(s), ["옛설정"])        # 이전 키워드 → 사용자 설정 그룹
        self.assertEqual(s["safetydata"]["serviceKey"], "OLDKEY")
        self.assertTrue(os.path.exists(os.path.join(self.legacy, "settings.json")))   # 원본 보존
        # 새 위치에서 바꾼 설정은 다음 실행 때 이전 파일로 덮이지 않음
        settings.save(settings.apply_update(s, {"keywords": ["새설정"]}))
        self.assertEqual(settings.migrate_legacy(self.legacy), [])
        self.assertEqual(custom_keywords(settings.load()), ["새설정"])

    def test_corrupted_settings_recover_from_backup(self):
        s = settings.load()
        settings.save(settings.apply_update(s, {"keywords": ["첫번째"]}))
        settings.save(settings.apply_update(settings.load(), {"keywords": ["두번째"]}))
        with open(os.path.join(self.new, "settings.json"), "w", encoding="utf-8") as f:
            f.write('{"keywords": ["깨진')      # 저장 도중 전원 차단 등으로 손상
        self.assertEqual(custom_keywords(settings.load()), ["첫번째"])
