# webapp/services/participant.py
"""참가자 비즈니스 로직"""

from typing import Dict, List, Optional, Any
from urllib.parse import urlsplit

from utils.time_utils import looks_time
from core.database import get_db
from webapp.services.prediction import PredictionService


class ParticipantService:
    """
    참가자 관련 비즈니스 로직
    
    주요 기능:
    - 참가자 CRUD
    - 참가자 데이터 조회 (스플릿, 예측 포함)
    - BIB 번호 정규화 (SPCT 6자리 등)
    """
    
    @staticmethod
    def bulk_create_participants(marathon_id: int, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        엑셀 업로드용 일괄 등록
        items: [{ "alias": str|None, "nameorbibno": str }, ...]
        결과: {"success": True, "created": n, "skipped": k, "errors": [...], "normalized": [...]}
        """
        if not marathon_id:
            return {"success": False, "error": "marathon_id required"}

        if not items:
            return {"success": False, "error": "no items"}

        created = 0
        skipped = 0
        errors: List[str] = []
        normalized: List[Dict[str, Any]] = []

        # 사전 정규화
        clean_rows = []
        for idx, it in enumerate(items, start=1):
            bib = (it.get("nameorbibno") or "").strip()
            alias = (it.get("alias") or None)
            if not bib:
                errors.append(f"row {idx}: empty nameorbibno")
                skipped += 1
                continue
            # SPCT 등 6자리 보정 규칙 재사용
            try:
                bib_norm = ParticipantService._normalize_bib_for_spct(marathon_id, bib)
            except Exception as e:
                errors.append(f"row {idx}: normalize fail ({e})")
                skipped += 1
                continue
            clean_rows.append((idx, alias, bib_norm))

        if not clean_rows:
            return {"success": False, "error": "no valid rows", "created": 0, "skipped": skipped, "errors": errors}

        # 중복 방지: 같은 마라톤 내 동일 nameorbibno는 스킵
        try:
            with get_db() as conn:
                # 이미 존재하는 bib 목록 미리 조회
                bib_list = [b for _, _, b in clean_rows]
                placeholders = ",".join(["?"] * len(bib_list))
                existing = set()
                if bib_list:
                    rows = conn.execute(
                        f"SELECT nameorbibno FROM participants WHERE marathon_id=? AND nameorbibno IN ({placeholders})",
                        (marathon_id, *bib_list)
                    ).fetchall()
                    existing = {r["nameorbibno"] for r in rows}

                # 트랜잭션 일괄 삽입
                for idx, alias, bib_norm in clean_rows:
                    if bib_norm in existing:
                        skipped += 1
                        continue
                    try:
                        conn.execute(
                            """INSERT INTO participants (marathon_id, alias, nameorbibno, active)
                               VALUES (?, ?, ?, 1)""",
                            (marathon_id, (alias.strip() if alias else None), bib_norm)
                        )
                        created += 1
                        normalized.append({"row": idx, "nameorbibno": bib_norm, "alias": alias})
                    except Exception as e:
                        errors.append(f"row {idx}: insert fail ({type(e).__name__}: {e})")
                        skipped += 1

                conn.commit()

            return {
                "success": True,
                "created": created,
                "skipped": skipped,
                "errors": errors,
                "normalized": normalized
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"{type(e).__name__}: {e}",
                "created": created,
                "skipped": skipped,
                "errors": errors
            }
    
    @staticmethod
    def list_participants(
        marathon_id: Optional[int] = None,
        active_only: bool = False
    ) -> List[Dict]:
        """
        참가자 목록 조회
        
        Args:
            marathon_id: 특정 마라톤의 참가자만 (None이면 전체)
            active_only: True면 active=1인 참가자만
        
        Returns:
            참가자 목록
    참가자 목록 + 예측 요약(prediction, status_text, finished) 포함
    - marathon_id가 없어도 마라톤 총거리를 JOIN해서 예측 가능하게 함
    - 스플릿은 한 번에 가져와 pid별로 그룹화
        """
        from core.database import get_db
        from webapp.services.prediction import PredictionService

        with get_db() as conn:
            # 1) 참가자 + 마라톤 JOIN (항상)
            base_sql = (
                "SELECT p.*, m.total_distance_km "
                "FROM participants p "
                "JOIN marathons m ON p.marathon_id = m.id "
            )
            conds, params = [], []
            if marathon_id is not None:
                conds.append("p.marathon_id=?")
                params.append(marathon_id)
            if active_only:
                conds.append("p.active=1")
            where = (" WHERE " + " AND ".join(conds)) if conds else ""
            order = " ORDER BY p.id DESC"

            rows = conn.execute(base_sql + where + order, params).fetchall()
            participants = [dict(r) for r in rows]
            if not participants:
                return []

            # 2) 모든 참가자 스플릿을 한 번에 조회
            pids = [p["id"] for p in participants]
            splits_by_pid = {pid: [] for pid in pids}
            placeholders = ",".join("?" for _ in pids)
            split_rows = conn.execute(
                f"""SELECT participant_id, point_label, point_km, net_time, pass_clock, pace
                    FROM splits
                    WHERE participant_id IN ({placeholders})
                    ORDER BY id ASC""",
                pids
            ).fetchall()
            for s in split_rows:
                splits_by_pid[s["participant_id"]].append(dict(s))

            # 3) 예측 계산 + 호환 필드 주입
            for p in participants:
                pid = p["id"]
                splits = splits_by_pid.get(pid, [])
                total_km = p.get("race_total_km") or p.get("total_distance_km") or 42.195

                pred = PredictionService.calculate_prediction(splits, total_km)

                # 기본 예측 필드
                p["prediction"]   = pred
                p["status_text"]  = pred.get("status_text", "주행중")
                p["finished"]     = bool(pred.get("finished"))
                # 구(舊) 프런트 호환용
                p["status"]       = p["status_text"]
                # (선택) 화면에서 쓰기 좋게 완주 시간/도착시각도 평탄화
                p["finish_net"]   = pred.get("finish_net_pred")
                p["finish_clock"] = pred.get("finish_eta")

            return participants
        
    @staticmethod
    def get_participant(participant_id: int) -> Optional[Dict]:
        """
        특정 참가자 조회
        
        Args:
            participant_id: 참가자 ID
        
        Returns:
            참가자 정보 또는 None
        """
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM participants WHERE id=?",
                (participant_id,)
            ).fetchone()
            
            return dict(row) if row else None
    
    @staticmethod
    def create_participant(
        marathon_id: int,
        nameorbibno: str,
        alias: Optional[str] = None
    ) -> Dict:
        """
        참가자 생성
        
        Args:
            marathon_id: 마라톤 ID
            nameorbibno: 참가번호 또는 이름
            alias: 표시명 (선택)
        
        Returns:
            {'success': bool, 'participant_id': int, 'error': str}
        """
        # 유효성 검증
        if not nameorbibno or not nameorbibno.strip():
            return {'success': False, 'error': '참가번호/이름은 필수입니다'}
        
        nameorbibno = nameorbibno.strip()
        
        # SPCT 6자리 정규화
        nameorbibno = ParticipantService._normalize_bib_for_spct(
            marathon_id, nameorbibno
        )
        
        try:
            with get_db() as conn:
                cursor = conn.execute(
                    """INSERT INTO participants(marathon_id, alias, nameorbibno, active)
                       VALUES(?, ?, ?, 1)""",
                    (marathon_id, alias.strip() if alias else None, nameorbibno)
                )
                conn.commit()
                
                return {
                    'success': True,
                    'participant_id': cursor.lastrowid,
                    'normalized_bib': nameorbibno
                }
        
        except Exception as e:
            # UNIQUE 제약 위반 (이미 존재)
            if 'UNIQUE constraint failed' in str(e):
                return {
                    'success': False,
                    'error': '이미 등록된 참가자입니다'
                }
            
            return {
                'success': False,
                'error': f'{type(e).__name__}: {e}'
            }
    
    @staticmethod
    def update_participant(
        participant_id: int,
        **updates
    ) -> Dict:
        """
        참가자 정보 수정
        
        Args:
            participant_id: 참가자 ID
            **updates: 수정할 필드들
                - alias: 표시명
                - nameorbibno: 참가번호
                - active: 활성화 여부
        
        Returns:
            {'success': bool, 'error': str}
        """
        allowed_fields = {'alias', 'nameorbibno', 'active'}
        
        fields = []
        values = []
        
        for key, value in updates.items():
            if key in allowed_fields:
                fields.append(f"{key}=?")
                values.append(value)
        
        if not fields:
            return {'success': False, 'error': '수정할 필드가 없습니다'}
        
        values.append(participant_id)
        
        try:
            with get_db() as conn:
                conn.execute(
                    f"UPDATE participants SET {', '.join(fields)} WHERE id=?",
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
    def delete_participant(participant_id: int) -> Dict:
        """
        참가자 삭제 (CASCADE로 스플릿도 삭제됨)
        
        Args:
            participant_id: 참가자 ID
        
        Returns:
            {'success': bool, 'error': str}
        """
        try:
            with get_db() as conn:
                conn.execute(
                    "DELETE FROM participants WHERE id=?",
                    (participant_id,)
                )
                conn.commit()
                
                return {'success': True}
        
        except Exception as e:
            return {
                'success': False,
                'error': f'{type(e).__name__}: {e}'
            }
    
    @staticmethod
    def get_participant_data(participant_id: int) -> Dict:
        """
        참가자 상세 데이터 (스플릿, 예측 포함)
        
        Args:
            participant_id: 참가자 ID
        
        Returns:
            {
                'participant': Dict,
                'splits': List[Dict],
                'prediction': Dict,
                'url': str
            }
        """
        with get_db() as conn:
            # 예측 및 기록 계산에 필요한 서비스들을 먼저 import 합니다.
            from webapp.services.prediction import PredictionService

            # 참가자 + 마라톤 정보
            p = conn.execute(
                """SELECT p.*, m.total_distance_km, m.url_template, m.usedata
                   FROM participants p
                   JOIN marathons m ON p.marathon_id = m.id
                   WHERE p.id = ?""",
                (participant_id,)
            ).fetchone()
            
            if not p:
                return {'error': 'Participant not found'}
            
            # 스플릿 데이터
            splits = conn.execute(
                "SELECT * FROM splits WHERE participant_id=? ORDER BY id ASC",
                (participant_id,)
            ).fetchall()
            
            splits = [dict(s) for s in splits]

            # 완주 기록 보정 (pass_clock -> net_time)
            finish_split = next((s for s in reversed(splits) if PredictionService.is_finish_label(s.get("point_label"))), None)
            
            if finish_split:
                pass # 현재는 별도 처리 없음. DB 값을 그대로 사용.


            # URL 생성
            url = (p['url_template'] or '').replace(
                '{nameorbibno}', p['nameorbibno']
            ).replace(
                '{usedata}', p['usedata'] or ''
            )
            
            # 예측 계산 (간단 버전)
            prediction = PredictionService.calculate_prediction(
                splits,
                p['race_total_km'] or p['total_distance_km']
            )
            
            return {
                'participant': dict(p),
                'splits': splits,
                'prediction': prediction,
                'url': url
            }
    
    @staticmethod
    def _normalize_bib_for_spct(marathon_id: int, bib: str) -> str:
        """
        SPCT 대회인 경우 BIB을 6자리로 정규화
        
        Args:
            marathon_id: 마라톤 ID
            bib: 참가번호
        
        Returns:
            정규화된 참가번호
        """
        with get_db() as conn:
            row = conn.execute(
                "SELECT url_template FROM marathons WHERE id=?",
                (marathon_id,)
            ).fetchone()
            
            if not row:
                return bib
            
            url_template = row['url_template'] or ''
            host = (urlsplit(url_template).hostname or '').lower()
            
            # SPCT 호스트이고 숫자면 6자리 제로패딩
            if 'spct' in host and bib.isdigit():
                return bib.zfill(6)
            
            return bib


# ============= 사용 예시 =============

if __name__ == "__main__":
    print("Testing ParticipantService...")
    
    # 1. 참가자 생성 (SPCT)
    result = ParticipantService.create_participant(
        marathon_id=1,
        nameorbibno="123",  # → 000123으로 정규화됨
        alias="홍길동"
    )
    print(f"Create: {result}")
    
    if result['success']:
        pid = result['participant_id']
        
        # 2. 참가자 조회
        participant = ParticipantService.get_participant(pid)
        print(f"Get: {participant}")
        
        # 3. 참가자 수정
        update_result = ParticipantService.update_participant(
            pid,
            alias="홍길동 (수정)"
        )
        print(f"Update: {update_result}")
        
        # 4. 목록 조회
        participants = ParticipantService.list_participants(
            marathon_id=1,
            active_only=True
        )
        print(f"List: {len(participants)} participants")
        
        # 5. 삭제
        delete_result = ParticipantService.delete_participant(pid)
        print(f"Delete: {delete_result}")
    
    print("\n✓ Tests completed")