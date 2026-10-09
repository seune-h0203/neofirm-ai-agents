@echo off
REM Python Scripts 디렉토리(nlm.exe 위치)를 PATH에 추가
for /f "delims=" %%i in ('python -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable),'Scripts'))"') do set SCRIPTS_DIR=%%i
set PATH=%SCRIPTS_DIR%;%USERPROFILE%\.local\bin;%PATH%
cd /d "%~dp0"
echo NeoFirm Generator 시작 중...
echo nlm 위치 확인 중...
where nlm 2>nul || echo [경고] nlm을 PATH에서 찾지 못했습니다. app.py의 fallback 로직을 사용합니다.
echo http://localhost:8000 을 브라우저에서 열어주세요
echo (Ctrl+C 로 종료)
python -m uvicorn app:app --port 8000 --reload
pause
