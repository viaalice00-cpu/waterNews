@echo off
chcp 65001 >nul
title 유역 상수도 모니터링
cd /d "%~dp0"

rem ── Python 명령 확인 (python 또는 py)
set PY=python
where python >nul 2>nul || set PY=py
where %PY% >nul 2>nul || (
  echo [오류] Python이 설치되어 있지 않습니다. https://www.python.org 에서 설치하세요.
  pause & exit /b 1
)

rem ── GitHub에서 최신 코드 받기 (git clone 으로 받은 폴더일 때만)
set REBUILD=
if exist ".git" (
  where git >nul 2>nul && (
    for /f %%i in ('git rev-parse HEAD') do set OLD=%%i
    echo [1/3] GitHub에서 최신 버전 확인 중...
    git pull --ff-only
    if errorlevel 1 echo [주의] 업데이트를 받지 못했습니다. 기존 버전으로 실행합니다.
    for /f %%i in ('git rev-parse HEAD') do set NEW=%%i
  )
)
if not "%OLD%"=="%NEW%" set REBUILD=1
if not exist "web\dist\index.html" set REBUILD=1

rem ── 화면(React) 빌드: 코드가 바뀌었거나 빌드 결과가 없을 때만
if defined REBUILD (
  echo [2/3] 화면을 빌드합니다. 1~2분 걸릴 수 있습니다...
  pushd web
  call npm install --no-audit --no-fund
  call npm run build
  if errorlevel 1 ( popd & echo [오류] 화면 빌드 실패. Node.js 설치를 확인하세요. & pause & exit /b 1 )
  popd
) else (
  echo [2/3] 변경 사항 없음 - 빌드 생략
)

rem ── 서버 실행 + 3초 뒤 브라우저 열기
echo [3/3] 서버를 시작합니다. 이 창을 닫으면 프로그램이 종료됩니다.
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8080"
%PY% app.py
pause
