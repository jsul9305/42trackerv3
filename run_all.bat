@echo off
echo Starting SmartChip Live services...

:: 크롤러 백그라운드 실행
start "Crawler" python run_crawler.py

:: 잠시 대기
timeout /t 2 /nobreak > nul

:: 웹앱 실행
python run_webapp.py

:: 종료 시 크롤러 창도 같이 닫음
taskkill /FI "WINDOWTITLE eq Crawler*" /T /F