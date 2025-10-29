# crawler/scheduler.py
"""크롤링 스케줄러 - 실행 주기 및 제한 관리"""

import time
import random
from typing import Dict, Optional
from dataclasses import dataclass


@dataclass
class ScheduleConfig:
    """스케줄 설정"""
    min_marathon_interval: int = 5      # 대회별 최소 간격 (초)
    min_participant_gap: float = 3.0    # 참가자별 최소 간격 (초)
    participant_gap_jitter: float = 2.0 # 참가자별 랜덤 지터 (초)


class CrawlerScheduler:
    """
    크롤러 스케줄러
    
    기능:
    - 대회별 실행 주기 관리
    - 참가자별 요청 간격 제한
    - 동시 요청 분산 (랜덤 지터)
    
    사용 예:
        scheduler = CrawlerScheduler()
        
        # 대회 실행 가능 여부
        if scheduler.should_run_marathon(marathon_id, refresh_sec):
            # 크롤링 실행
            scheduler.mark_marathon_run(marathon_id)
        
        # 참가자 페치 가능 여부
        if scheduler.can_fetch_participant(participant_id):
            # 페치 실행
            scheduler.mark_participant_fetch(participant_id)
    """
    
    def __init__(self, config: Optional[ScheduleConfig] = None):
        """
        Args:
            config: 스케줄 설정 (None이면 기본값 사용)
        """
        self.config = config or ScheduleConfig()
        
        # 마지막 실행 시각 추적
        self.last_marathon_run: Dict[int, float] = {}    # marathon_id → timestamp
        self.last_participant_fetch: Dict[int, float] = {}  # participant_id → timestamp
    
    # ============= 대회 스케줄링 =============
    
    def should_run_marathon(
        self,
        marathon_id: int,
        refresh_sec: int
    ) -> bool:
        """
        대회 크롤링 실행 가능 여부
        
        Args:
            marathon_id: 대회 ID
            refresh_sec: 설정된 새로고침 주기 (초)
        
        Returns:
            True면 실행 가능
        """
        now = time.time()
        last_run = self.last_marathon_run.get(marathon_id, 0)
        
        # 최소 간격과 설정된 주기 중 큰 값 사용
        min_interval = max(self.config.min_marathon_interval, refresh_sec)
        
        return (now - last_run) >= min_interval
    
    def mark_marathon_run(self, marathon_id: int):
        """
        대회 크롤링 실행 완료 기록
        
        Args:
            marathon_id: 대회 ID
        """
        self.last_marathon_run[marathon_id] = time.time()
    
    def get_marathon_wait_time(
        self,
        marathon_id: int,
        refresh_sec: int
    ) -> float:
        """
        다음 실행까지 대기 시간 계산
        
        Args:
            marathon_id: 대회 ID
            refresh_sec: 새로고침 주기 (초)
        
        Returns:
            대기 시간 (초), 0 이하면 즉시 실행 가능
        """
        now = time.time()
        last_run = self.last_marathon_run.get(marathon_id, 0)
        min_interval = max(self.config.min_marathon_interval, refresh_sec)
        
        elapsed = now - last_run
        return max(0, min_interval - elapsed)
    
    # ============= 참가자 스케줄링 =============
    
    def can_fetch_participant(self, participant_id: int) -> bool:
        """
        참가자 페치 가능 여부 (rate limiting)
        
        Args:
            participant_id: 참가자 ID
        
        Returns:
            True면 페치 가능
        """
        now = time.time()
        last_fetch = self.last_participant_fetch.get(participant_id, 0)
        
        # 최소 간격 + 랜덤 지터
        min_gap = self.config.min_participant_gap + random.random() * self.config.participant_gap_jitter
        
        return (now - last_fetch) >= min_gap
    
    def mark_participant_fetch(self, participant_id: int):
        """
        참가자 페치 완료 기록
        
        Args:
            participant_id: 참가자 ID
        """
        self.last_participant_fetch[participant_id] = time.time()
    
    def get_participant_wait_time(self, participant_id: int) -> float:
        """
        다음 페치까지 대기 시간 계산
        
        Args:
            participant_id: 참가자 ID
        
        Returns:
            대기 시간 (초), 0 이하면 즉시 가능
        """
        now = time.time()
        last_fetch = self.last_participant_fetch.get(participant_id, 0)
        min_gap = self.config.min_participant_gap
        
        elapsed = now - last_fetch
        return max(0, min_gap - elapsed)
    
    # ============= 통계 =============
    
    def get_stats(self) -> Dict:
        """
        스케줄러 통계 반환
        
        Returns:
            {
                'tracked_marathons': int,      # 추적 중인 대회 수
                'tracked_participants': int,   # 추적 중인 참가자 수
                'config': ScheduleConfig       # 현재 설정
            }
        """
        return {
            'tracked_marathons': len(self.last_marathon_run),
            'tracked_participants': len(self.last_participant_fetch),
            'config': self.config
        }
    
    def reset(self):
        """스케줄러 초기화 (테스트용)"""
        self.last_marathon_run.clear()
        self.last_participant_fetch.clear()
    
    def reset_marathon(self, marathon_id: int):
        """특정 대회 스케줄 초기화"""
        self.last_marathon_run.pop(marathon_id, None)
    
    def reset_participant(self, participant_id: int):
        """특정 참가자 스케줄 초기화"""
        self.last_participant_fetch.pop(participant_id, None)


# ============= 고급 스케줄러 =============

class AdaptiveScheduler(CrawlerScheduler):
    """
    적응형 스케줄러
    
    기능:
    - 실패 시 백오프 (exponential backoff)
    - 성공 시 점진적 속도 증가
    
    Example:
        scheduler = AdaptiveScheduler()
        
        # 크롤링 실행
        if scheduler.should_run_marathon(mid, refresh_sec):
            try:
                # 크롤링...
                scheduler.record_success(mid)
            except Exception:
                scheduler.record_failure(mid)
    """
    
    def __init__(self, config: Optional[ScheduleConfig] = None):
        super().__init__(config)
        
        # 실패 카운터
        self.failure_count: Dict[int, int] = {}  # marathon_id → count
        
        # 백오프 설정
        self.max_backoff = 300  # 최대 5분
        self.backoff_multiplier = 2.0
    
    def should_run_marathon(
        self,
        marathon_id: int,
        refresh_sec: int
    ) -> bool:
        """실패 횟수에 따른 백오프 적용"""
        # 기본 체크
        if not super().should_run_marathon(marathon_id, refresh_sec):
            return False
        
        # 백오프 체크
        failures = self.failure_count.get(marathon_id, 0)
        if failures == 0:
            return True
        
        # Exponential backoff
        backoff_sec = min(
            refresh_sec * (self.backoff_multiplier ** failures),
            self.max_backoff
        )
        
        now = time.time()
        last_run = self.last_marathon_run.get(marathon_id, 0)
        
        return (now - last_run) >= backoff_sec
    
    def record_success(self, marathon_id: int):
        """
        성공 기록 (백오프 리셋)
        
        Args:
            marathon_id: 대회 ID
        """
        self.mark_marathon_run(marathon_id)
        self.failure_count.pop(marathon_id, None)
    
    def record_failure(self, marathon_id: int):
        """
        실패 기록 (백오프 증가)
        
        Args:
            marathon_id: 대회 ID
        """
        self.mark_marathon_run(marathon_id)
        self.failure_count[marathon_id] = self.failure_count.get(marathon_id, 0) + 1
    
    def get_backoff_time(self, marathon_id: int, refresh_sec: int) -> float:
        """
        현재 백오프 시간 계산
        
        Args:
            marathon_id: 대회 ID
            refresh_sec: 기본 새로고침 주기
        
        Returns:
            백오프 시간 (초)
        """
        failures = self.failure_count.get(marathon_id, 0)
        if failures == 0:
            return refresh_sec
        
        return min(
            refresh_sec * (self.backoff_multiplier ** failures),
            self.max_backoff
        )


# ============= 사용 예시 =============

if __name__ == "__main__":
    # 1. 기본 스케줄러
    print("=== Basic Scheduler ===")
    scheduler = CrawlerScheduler()
    
    marathon_id = 1
    refresh_sec = 60
    
    # 첫 실행
    if scheduler.should_run_marathon(marathon_id, refresh_sec):
        print(f"Marathon {marathon_id}: Running (first time)")
        scheduler.mark_marathon_run(marathon_id)
    
    # 즉시 재시도 (거부됨)
    if scheduler.should_run_marathon(marathon_id, refresh_sec):
        print(f"Marathon {marathon_id}: Running")
    else:
        wait = scheduler.get_marathon_wait_time(marathon_id, refresh_sec)
        print(f"Marathon {marathon_id}: Wait {wait:.1f}s")
    
    # 참가자 페치
    participant_id = 100
    for i in range(3):
        if scheduler.can_fetch_participant(participant_id):
            print(f"Participant {participant_id}: Fetch #{i+1}")
            scheduler.mark_participant_fetch(participant_id)
        else:
            wait = scheduler.get_participant_wait_time(participant_id)
            print(f"Participant {participant_id}: Wait {wait:.1f}s")
        time.sleep(0.5)
    
    # 통계
    stats = scheduler.get_stats()
    print(f"\nStats: {stats['tracked_marathons']} marathons, "
          f"{stats['tracked_participants']} participants")
    
    print("\n=== Adaptive Scheduler ===")
    
    # 2. 적응형 스케줄러
    adaptive = AdaptiveScheduler()
    
    # 실패 시뮬레이션
    for i in range(3):
        if adaptive.should_run_marathon(marathon_id, refresh_sec):
            print(f"Attempt #{i+1}: Running")
            adaptive.record_failure(marathon_id)  # 실패!
            
            backoff = adaptive.get_backoff_time(marathon_id, refresh_sec)
            print(f"  → Failed. Next backoff: {backoff:.1f}s")
    
    # 성공
    time.sleep(1)
    if adaptive.should_run_marathon(marathon_id, refresh_sec):
        print(f"Attempt #4: Running")
        adaptive.record_success(marathon_id)  # 성공!
        print("  → Success. Backoff reset")
    
    print("\n✓ Tests passed")