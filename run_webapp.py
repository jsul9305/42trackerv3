#!/usr/bin/env python3
"""
웹앱 실행 스크립트
사용법: python run_webapp.py
"""
import sys
from pathlib import Path

# 프로젝트 루트를 파이썬 경로에 추가
sys.path.insert(0, str(Path(__file__).parent))

from webapp.app import create_app
from config.settings import WEBAPP_HOST, WEBAPP_PORT, WEBAPP_DEBUG
from core.database import init_database, migrate_database

def main():
    print("=" * 50)
    print("SmartChip Live WebApp")
    print("=" * 50)
    
    # 1. 데이터베이스 초기화
    print("\n[1/2] Initializing database...")
    init_database()
    migrate_database()
    print("✓ Database ready")
    
    # 2. Flask 앱 생성 및 실행
    print(f"\n[2/2] Starting web server...")
    print(f"→ URL: http://{WEBAPP_HOST}:{WEBAPP_PORT}")
    print(f"→ Debug: {WEBAPP_DEBUG}")
    print(f"→ Press Ctrl+C to stop\n")
    
    app = create_app()
    app.run(
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
        debug=WEBAPP_DEBUG
    )

if __name__ == "__main__":
    main()