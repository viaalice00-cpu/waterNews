@echo off
chcp 65001 >nul
title 유역 상수도 모니터링 - 업데이트
cd /d "%~dp0"

where git >nul 2>nul || ( echo [오류] Git이 설치되어 있지 않습니다. https://git-scm.com 에서 설치하세요. & pause & exit /b 1 )
if not exist ".git" ( echo [오류] 이 폴더는 git clone 으로 받은 폴더가 아닙니다. 설치 안내를 확인하세요. & pause & exit /b 1 )

echo GitHub에서 최신 버전을 받습니다...
git pull --ff-only
if errorlevel 1 ( echo [오류] 업데이트 실패. 폴더 안의 파일을 직접 수정했다면 되돌린 뒤 다시 시도하세요. & pause & exit /b 1 )

echo 화면을 다시 빌드합니다...
pushd web
call npm install --no-audit --no-fund
call npm run build
if errorlevel 1 ( popd & echo [오류] 화면 빌드 실패 & pause & exit /b 1 )
popd

echo.
echo 업데이트 완료. (인증키·설정은 %%APPDATA%%\waterNews 에 있어 그대로 유지됩니다)
echo 실행 중인 프로그램이 있다면 창을 닫고 start.bat 을 다시 실행하세요.
pause
