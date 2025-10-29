# webapp/services/marathon.py
"""마라톤 비즈니스 로직"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import random
import string

from core.database import get_db


class MarathonService:
    """
    마라톤 관련 비즈니스 로직
    
    주요 기능:
    - 마라톤 CRUD (생성, 조회, 수정, 삭제)
    - 마라톤 활성화/비활성화
    - 마라톤 통계
    """    

    # ---------- 참여 코드 유틸 ----------
    @staticmethod
    def generate_unique_code(existing_codes):
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            if code not in existing_codes:
                return code
    
    # ---------- 조회 ----------
    @staticmethod
    def list_marathons(enabled_only: bool = False) -> List[Dict]:
        """
        마라톤 목록 조회
        
        Args:
            enabled_only: True면 활성화된 마라톤만 조회
        
        Returns:
            마라톤 목록
        """
        with get_db() as conn:
            if enabled_only:
                query = "SELECT * FROM marathons WHERE enabled=1 ORDER BY id DESC"
            else:
                query = "SELECT * FROM marathons ORDER BY id DESC"
            
            rows = conn.execute(query).fetchall()
            return [dict(row) for row in rows]
    
    @staticmethod
    def get_marathon(marathon_id: int) -> Optional[Dict]:
        """
        특정 마라톤 조회
        
        Args:
            marathon_id: 마라톤 ID
        
        Returns:
            마라톤 정보 또는 None
        """
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM marathons WHERE id=?",
                (marathon_id,)
            ).fetchone()
            
            return dict(row) if row else None
        
    @staticmethod
    def get_marathon_by_join_code(code: str) -> Optional[Dict]:
        """
        참여 코드로 마라톤 조회
        """
        if not code:
            return None
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM marathons WHERE join_code=?",
                (code.strip(),)
            ).fetchone()
            return dict(row) if row else None

    # ---------- 생성/수정/삭제 ----------
    @staticmethod
    def create_marathon(
        name: str,
        url_template: str,
        usedata: Optional[str] = None,
        total_distance_km: float = 21.1,
        refresh_sec: int = 60,
        enabled: bool = True,
        cert_url_template: Optional[str] = None,
        event_date: Optional[str] = None
    ) -> Dict:
        """
        새 마라톤 생성 + 참여 코드 자동 생성(join_code)
        API 결과로 marathon_id와 join_code 반환
        """
        # 유효성 검증
        if not name or not name.strip():
            return {'success': False, 'error': '대회명은 필수입니다'}

        if not url_template or '{nameorbibno}' not in url_template:
            return {'success': False, 'error': 'URL 템플릿에 {nameorbibno}를 포함해야 합니다'}

        if refresh_sec < 5:
            return {'success': False, 'error': '새로고침 주기는 최소 5초 이상이어야 합니다'}

        try:
            with get_db() as conn:
                # 고유 참여 코드 생성
                join_code = MarathonService.generate_unique_code(conn, length=8)
                cursor = conn.execute(
                    """INSERT INTO marathons(
                        name, url_template, usedata, 
                        total_distance_km, refresh_sec, enabled,
                        cert_url_template, event_date, join_code, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",  # Add an additional ? placeholder
                    (
                        name.strip(),
                        url_template.strip(),
                        usedata.strip() if usedata else None,
                        total_distance_km,
                        refresh_sec,
                        1 if enabled else 0,
                        cert_url_template.strip() if cert_url_template else None,
                        event_date,
                        join_code,  # 새로운 코드를 삽입합니다.
                        datetime.now().isoformat()
                    )
                )
                conn.commit()

                return {
                    'success': True,
                    'marathon_id': cursor.lastrowid,
                    'join_code': join_code
                }

        except Exception as e:
            return {
                'success': False,
                'error': f'{type(e).__name__}: {e}'
            }
        
    @staticmethod
    def regenerate_join_code(marathon_id: int) -> Dict:
        """
        특정 대회의 참여 코드를 새 값으로 교체
        """
        if not marathon_id:
            return {'success': False, 'error': 'marathon_id가 필요합니다'}

        try:
            with get_db() as conn:
                # 존재 여부 확인
                row = conn.execute(
                    "SELECT id FROM marathons WHERE id=?",
                    (marathon_id,)
                ).fetchone()
                if not row:
                    return {'success': False, 'error': '마라톤을 찾을 수 없습니다'}

                # 새 고유 코드 생성
                new_code = MarathonService._generate_unique_code(conn, length=8)

                conn.execute(
                    "UPDATE marathons SET join_code=?, updated_at=? WHERE id=?",
                    (new_code, datetime.now().isoformat(), marathon_id)
                )
                conn.commit()

                return {'success': True, 'join_code': new_code}

        except Exception as e:
            return {'success': False, 'error': f'{type(e).__name__}: {e}'}
    
    @staticmethod
    def update_marathon(
        marathon_id: int,
        **updates
    ) -> Dict:
        """
        마라톤 정보 수정
        
        Args:
            marathon_id: 마라톤 ID
            **updates: 수정할 필드들
                - name: 대회명
                - url_template: URL 템플릿
                - usedata: 대회 ID
                - total_distance_km: 총 거리
                - refresh_sec: 새로고침 주기
                - enabled: 활성화 여부
                - cert_url_template: 기록증 URL 템플릿
        
        Returns:
            {'success': bool, 'error': str}
        """
        # 허용된 필드만 업데이트
        allowed_fields = {
            'name', 'url_template', 'usedata',
            'total_distance_km', 'refresh_sec', 'enabled',
            'cert_url_template', 'event_date'
        }
        
        fields = []
        values = []
        
        for key, value in updates.items():
            if key in allowed_fields:
                # URL 템플릿 검증
                if key == 'url_template':
                    if not value or '{nameorbibno}' not in value:
                        return {
                            'success': False,
                            'error': 'URL 템플릿에 {nameorbibno}를 포함해야 합니다'
                        }
                
                # refresh_sec 검증
                if key == 'refresh_sec' and value is not None and value < 5:
                    return {
                        'success': False,
                        'error': '새로고침 주기는 최소 5초 이상이어야 합니다'
                    }
                
                fields.append(f"{key}=?")
                values.append(value)
        
        if not fields:
            return {'success': False, 'error': '수정할 필드가 없습니다'}
        
        # updated_at 추가
        fields.append("updated_at=?")
        values.append(datetime.now().isoformat())
        
        # marathon_id 추가
        values.append(marathon_id)
        
        try:
            with get_db() as conn:
                conn.execute(
                    f"UPDATE marathons SET {', '.join(fields)} WHERE id=?",
                    values
                )
                conn.commit()
                
                return {'success': True}
        
        except Exception as e:
            return {
                'success': False,
                'error': f'{type(e).__name__}: {e}'
            }
    
    @staticmethod
    def delete_marathon(marathon_id: int) -> Dict:
        """
        마라톤 삭제 (CASCADE로 참가자/스플릿도 삭제됨)
        
        Args:
            marathon_id: 마라톤 ID
        
        Returns:
            {'success': bool, 'error': str}
        """
        try:
            with get_db() as conn:
                conn.execute(
                    "DELETE FROM marathons WHERE id=?",
                    (marathon_id,)
                )
                conn.commit()
                
                return {'success': True}
        
        except Exception as e:
            return {
                'success': False,
                'error': f'{type(e).__name__}: {e}'
            }
    
    @staticmethod
    def toggle_enabled(marathon_id: int) -> Dict:
        """
        마라톤 활성화/비활성화 토글
        
        Args:
            marathon_id: 마라톤 ID
        
        Returns:
            {'success': bool, 'enabled': bool, 'error': str}
        """
        try:
            with get_db() as conn:
                # 현재 상태 조회
                row = conn.execute(
                    "SELECT enabled FROM marathons WHERE id=?",
                    (marathon_id,)
                ).fetchone()
                
                if not row:
                    return {
                        'success': False,
                        'error': '마라톤을 찾을 수 없습니다'
                    }
                
                # 토글
                new_enabled = 0 if row['enabled'] else 1
                
                conn.execute(
                    "UPDATE marathons SET enabled=?, updated_at=? WHERE id=?",
                    (new_enabled, datetime.now().isoformat(), marathon_id)
                )
                conn.commit()
                
                return {
                    'success': True,
                    'enabled': bool(new_enabled)
                }
        
        except Exception as e:
            return {
                'success': False,
                'error': f'{type(e).__name__}: {e}'
            }
    
    @staticmethod
    def get_marathon_stats(marathon_id: int) -> Dict:
        """
        마라톤 통계
        
        Args:
            marathon_id: 마라톤 ID
        
        Returns:
            {
                'total_participants': int,
                'active_participants': int,
                'total_splits': int,
                'last_updated': str
            }
        """
        with get_db() as conn:
            # 참가자 수
            total_participants = conn.execute(
                "SELECT COUNT(*) FROM participants WHERE marathon_id=?",
                (marathon_id,)
            ).fetchone()[0]
            
            active_participants = conn.execute(
                "SELECT COUNT(*) FROM participants WHERE marathon_id=? AND active=1",
                (marathon_id,)
            ).fetchone()[0]
            
            # 스플릿 수
            total_splits = conn.execute(
                """SELECT COUNT(*) FROM splits 
                   WHERE participant_id IN (
                       SELECT id FROM participants WHERE marathon_id=?
                   )""",
                (marathon_id,)
            ).fetchone()[0]
            
            # 마지막 업데이트
            last_updated_row = conn.execute(
                "SELECT updated_at FROM marathons WHERE id=?",
                (marathon_id,)
            ).fetchone()
            
            return {
                'total_participants': total_participants,
                'active_participants': active_participants,
                'total_splits': total_splits,
                'last_updated': last_updated_row['updated_at'] if last_updated_row else None
            }



# ============= 간단 테스트 =============
if __name__ == "__main__":
    print("Testing MarathonService...")

    # 1. 생성
    result = MarathonService.create_marathon(
        name="2025 테스트 마라톤",
        url_template="https://smartchip.co.kr/data.asp?nameorbibno={nameorbibno}&usedata={usedata}",
        usedata="202550000158",
        total_distance_km=21.1,
        refresh_sec=60
    )
    print("Create:", result)

    if result.get('success'):
        mid = result['marathon_id']
        jc = result['join_code']
        print("Join Code:", jc)

        # 2. 코드로 조회
        m_by_code = MarathonService.get_marathon_by_join_code(jc)
        print("Get by code:", bool(m_by_code), m_by_code.get('id') if m_by_code else None)

        # 3. 재발급
        regen = MarathonService.regenerate_join_code(mid)
        print("Regenerate:", regen)

        # 4. 일반 조회
        marathon = MarathonService.get_marathon(mid)
        print("Get:", marathon['name'])

        # 5. 수정
        upd = MarathonService.update_marathon(mid, refresh_sec=30)
        print("Update:", upd)

        # 6. 통계
        stats = MarathonService.get_marathon_stats(mid)
        print("Stats:", stats)

        # 7. 삭제
        dele = MarathonService.delete_marathon(mid)
        print("Delete:", dele)

    print("\n✓ Tests completed")