"""HTTP 요청 및 시간 유틸 (표준 라이브러리만 사용)."""

import ssl
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), "KST")
USER_AGENT = "Mozilla/5.0 (compatible; WaterNewsMonitor/0.1)"


class FetchError(Exception):
    def __init__(self, message, status=None, body=""):
        super().__init__(message)
        self.status = status   # HTTP 상태 코드 (연결 실패면 None)
        self.body = body


def now_kst():
    return datetime.now(KST)


def http_get(url, headers=None, timeout=20, verify_ssl=True):
    """GET 요청 후 (status, bytes) 반환. 시스템 프록시 환경변수(HTTPS_PROXY)를 따른다."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    ctx = ssl.create_default_context() if verify_ssl else ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode("utf-8", "replace")
        raise FetchError(f"HTTP {e.code}: {body}", status=e.code, body=body) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise FetchError(f"연결 실패: {reason}") from e
