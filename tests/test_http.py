import json
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from datetime import datetime
from email.utils import format_datetime
from http.server import ThreadingHTTPServer

import app
from waternews import settings
from waternews.net import now_kst


def fake_getter(url, headers=None, **_):
    pub = format_datetime(now_kst())
    rss = (f"<rss><channel><item><title>경기 수돗물 유충 발견 - A</title><link>https://g/1</link>"
           f"<pubDate>{pub}</pubDate><source url='x'>A</source></item></channel></rss>")
    return 200, rss.encode()


class NewsEndpointTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig_dir, self._orig_getter = settings.DATA_DIR, app.NEWS_GETTER
        settings.DATA_DIR = self.tmp.name
        app.NEWS_GETTER = fake_getter
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        settings.DATA_DIR, app.NEWS_GETTER = self._orig_dir, self._orig_getter
        self.tmp.cleanup()

    def get(self, **params):
        url = f"http://127.0.0.1:{self.server.server_port}/api/news?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(url) as r:
            return json.load(r)

    def test_empty_basins_means_nationwide(self):
        """유역을 하나도 선택하지 않으면(basins=) 기본 활성 유역(금강)으로 거르지 않고 전국 기사를 보여준다."""
        today = now_kst().date().isoformat()
        common = dict(keywords="유충", sources="google", **{"from": today, "to": today})
        res = self.get(basins="", **common)
        self.assertEqual(len(res["items"]), 1)
        self.assertEqual(res["dropped"]["region"], 0)
        res = self.get(basins="geum", **common)   # 금강유역만 선택하면 경기 기사는 지역 불일치
        self.assertEqual(res["items"], [])
        self.assertEqual(res["dropped"]["region"], 1)


if __name__ == "__main__":
    unittest.main()
