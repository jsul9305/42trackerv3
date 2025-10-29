#!/usr/bin/env python3
"""
크롤러 실행 스크립트
사용법: 
    python run_crawler.py                    # 기본 스케줄러
    python run_crawler.py --adaptive         # 적응형 스케줄러
    python run_crawler.py --help             # 도움말
"""
import sys
import argparse
from pathlib import Path

# 프로젝트 루트를 파이썬 경로에 추가
sys.path.insert(0, str(Path(__file__).parent))

from core.database import init_database, migrate_database
from crawler.engine import CrawlerEngine


def parse_args():
    """명령행 인수 파싱"""
    parser = argparse.ArgumentParser(
        description='SmartChip Live Crawler - 마라톤 실시간 기록 크롤러',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python run_crawler.py                    # 기본 모드
  python run_crawler.py --adaptive         # 적응형 모드 (실패 시 백오프)
  
스케줄러 모드:
  - 기본 (Basic):    고정된 주기로 실행, 실패해도 동일한 간격
  - 적응형 (Adaptive): 실패 시 자동으로 대기 시간 증가 (exponential backoff)
        """
    )
    
    parser.add_argument(
        '--adaptive',
        action='store_true',
        help='적응형 스케줄러 사용 (실패 시 백오프 적용)'
    )
    
    parser.add_argument(
        '--skip-init',
        action='store_true',
        help='DB 초기화 스킵 (이미 초기화된 경우)'
    )
    
    return parser.parse_args()


def main():
    """메인 함수"""
    args = parse_args()
    
    print("=" * 60)
    print("SmartChip Live Crawler")
    print("=" * 60)
    
    # 1. 데이터베이스 초기화
    if not args.skip_init:
        print("\n[1/3] Initializing database...")
        try:
            init_database()
            print("✓ Database schema created")
        except Exception as e:
            print(f"✗ Database init failed: {e}")
            return 1
        
        # 2. 마이그레이션 실행
        print("\n[2/3] Running migrations...")
        try:
            migrate_database()
            print("✓ Migrations completed")
        except Exception as e:
            print(f"✗ Migration failed: {e}")
            return 1
    else:
        print("\n[Skipped] Database initialization")
    
    # 3. 크롤러 엔진 시작
    print("\n[3/3] Starting crawler engine...")
    
    # 스케줄러 모드 표시
    if args.adaptive:
        print("→ Mode: Adaptive Scheduler (with exponential backoff)")
        print("  • Automatically increases delay on failures")
        print("  • Resets to normal on success")
    else:
        print("→ Mode: Basic Scheduler (fixed intervals)")
        print("  • Maintains constant refresh intervals")
    
    print("\nPress Ctrl+C to stop\n")
    print("-" * 60)
    
    # 엔진 생성
    engine = CrawlerEngine(use_adaptive_scheduler=args.adaptive)
    
    # 실행
    try:
        engine.run()
    except KeyboardInterrupt:
        print("\n\n" + "=" * 60)
        print("[Shutdown] Stopping crawler...")
        print("=" * 60)
        engine.shutdown()
        print("✓ Crawler stopped gracefully")
        return 0
    except Exception as e:
        print(f"\n[Fatal Error] {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)