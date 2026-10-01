#!/bin/sh
# Mac/Linux: GitHub 최신 버전 받기 → (변경 시) 화면 빌드 → 서버 실행
cd "$(dirname "$0")" || exit 1
OLD=$(git rev-parse HEAD 2>/dev/null)
[ -d .git ] && { echo "[1/3] GitHub에서 최신 버전 확인 중..."; git pull --ff-only || echo "[주의] 업데이트 실패 - 기존 버전으로 실행"; }
NEW=$(git rev-parse HEAD 2>/dev/null)
if [ "$OLD" != "$NEW" ] || [ ! -f web/dist/index.html ]; then
  echo "[2/3] 화면을 빌드합니다..."
  (cd web && npm install --no-audit --no-fund && npm run build) || { echo "[오류] 화면 빌드 실패"; exit 1; }
else
  echo "[2/3] 변경 사항 없음 - 빌드 생략"
fi
echo "[3/3] 서버 시작: http://127.0.0.1:8080 (종료: Ctrl+C)"
( sleep 3; open http://127.0.0.1:8080 2>/dev/null || xdg-open http://127.0.0.1:8080 2>/dev/null ) &
exec python3 app.py "$@"
