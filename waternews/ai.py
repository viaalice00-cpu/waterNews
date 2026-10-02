"""AI 브리핑 (선택 기능): Claude API 로 사건 군집을 보고서형 문장으로 요약한다.

- 필요: `pip install anthropic` + 환경설정의 Anthropic API 키 (또는 ANTHROPIC_API_KEY 환경변수)
- 설치/키가 없으면 규칙 기반 브리핑만 사용된다.
- 전송 데이터: 해당 사건의 뉴스 제목·요약, 재난문자 내용 (공개 정보)
"""

AI_MODELS = {
    "claude-opus-5-5": "Claude Opus 5.5 (기본, 고품질)",
    "claude-sonnet-5-5": "Claude Sonnet 5.5 (빠르고 저렴)",
    "claude-haiku-4-5": "Claude Haiku 4.5 (가장 저렴)",
}
DEFAULT_MODEL = "claude-opus-5-5"
# 서버측 대체 모델(fallbacks="default")을 지원하는 모델 — 안전 분류기가 요청을 거절하면 다른 모델로 자동 재실행
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}

SYSTEM_PROMPT = """당신은 상수도 사업 기관의 언론·재난 모니터링 분석관입니다.
주어진 뉴스 기사와 행정안전부 긴급재난문자만 근거로, 한 건의 수도 사고(단수·관로 파열·누수·수질 이상·침수 등)에
대해 기관 내부 보고용 브리핑을 작성합니다.

작성 원칙
- 자료에 없는 사실(피해 규모, 원인, 시간 등)을 추정하거나 지어내지 마세요. 불확실하면 '확인 필요'로 표시하세요.
- 기사 간 내용이 다르면(예: 피해 세대 수) 차이를 그대로 밝히세요.
- 정치·인물 평가는 하지 말고, 사실과 대응에 필요한 시사점만 쓰세요.
- 한국어 개조식 문체(~함, ~임)로, 아래 형식을 지키세요.

## 상황 요약
(3줄 이내: 언제·어디서·무엇이·현재 상태)

## 경과
(시간순 핵심 3~6개 항목, '- MM/DD HH:MM 내용' 형식)

## 쟁점·맥락
(원인, 피해·영향, 여론·언론 논조)

## 대응 시사점
(기관이 준비할 사항 2~4개)

## 확인 필요
(자료로 확인되지 않는 사항)"""


class AIError(Exception):
    pass


def build_prompt(cluster, items, max_items=40, max_body=400):
    lines = [
        f"사건: {cluster['region']} {cluster['incidentType']}",
        f"기간: {cluster['start']} ~ {cluster['end']} (뉴스 {cluster['counts']['news']}건, 재난문자 {cluster['counts']['disaster']}건)",
        f"규칙 기반 상태 판정: {cluster['status']}",
        "",
        "<자료>",
    ]
    for it in sorted(items, key=lambda x: x["time"])[-max_items:]:
        kind = "뉴스" if it["kind"] == "news" else "재난문자"
        body = (it["body"] or "")[:max_body]
        lines.append(f"[{it['time'][:16].replace('T', ' ')}] ({kind} · {it['source']}) {it['title']}")
        if body and body != it["title"]:
            lines.append(f"    {body}")
    lines.append("</자료>")
    lines.append("\n위 자료만 근거로 브리핑을 작성하세요.")
    return "\n".join(lines)


def generate_briefing(cluster, items, api_key="", model=DEFAULT_MODEL, client=None):
    """브리핑 텍스트(마크다운) 반환. client 는 테스트용 주입."""
    try:
        import anthropic
    except ImportError as e:
        raise AIError("AI 브리핑을 쓰려면 명령 프롬프트에서 'pip install anthropic' 을 실행한 뒤 서버를 다시 시작하세요.") from e

    if client is None:
        client = anthropic.Anthropic(api_key=api_key or None, timeout=180, max_retries=2)
    model = model if model in AI_MODELS else DEFAULT_MODEL
    req = {
        "model": model,
        "max_tokens": 16000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": build_prompt(cluster, items)}],
    }
    if model != "claude-haiku-4-5":            # Haiku 4.5 는 effort 미지원
        req["output_config"] = {"effort": "medium"}
    try:
        if model in _FALLBACK_MODELS:
            resp = client.beta.messages.create(
                **req, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        else:
            resp = client.messages.create(**req)
    except anthropic.AuthenticationError as e:
        raise AIError("Anthropic API 키가 올바르지 않습니다. 환경설정에서 키를 확인하세요.") from e
    except anthropic.PermissionDeniedError as e:
        raise AIError(f"API 키 권한이 없습니다: {e.message}") from e
    except anthropic.RateLimitError as e:
        raise AIError("요청 한도를 초과했습니다. 잠시 후 다시 시도하세요.") from e
    except anthropic.BadRequestError as e:
        raise AIError(f"요청 오류: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise AIError(f"Claude API 오류 ({e.status_code}). 잠시 후 다시 시도하세요.") from e
    except anthropic.APIConnectionError as e:
        raise AIError("Claude API 에 연결할 수 없습니다. 인터넷/프록시 설정을 확인하세요.") from e

    if resp.stop_reason == "refusal":
        raise AIError("AI가 이 요청에 대한 응답을 거절했습니다. 규칙 기반 브리핑을 참고하세요.")
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        raise AIError("AI 응답이 비어 있습니다.")
    if resp.stop_reason == "max_tokens":
        text += "\n\n(응답이 길이 제한으로 잘렸습니다)"
    return {"text": text, "model": resp.model}
