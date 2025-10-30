# webapp/services/group.py
from typing import Optional, Dict
from datetime import datetime
import secrets, string

from core.database import get_db

class GroupService:
    @staticmethod
    def _gen_unique_code(conn, length: int = 8) -> str:
        alphabet = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(secrets.choice(alphabet) for _ in range(length))
            exists = conn.execute(
                "SELECT 1 FROM groups WHERE group_code=? LIMIT 1", (code,)
            ).fetchone()
            if not exists:
                return code

    @staticmethod
    def create_group(marathon_id: int, group_name: str) -> Dict:
        if not marathon_id:
            return {"success": False, "error": "marathon_id is required"}
        if not group_name or not group_name.strip():
            return {"success": False, "error": "group_name is required"}

        try:
            with get_db() as conn:
                # 대회 존재 확인 (선택)
                m = conn.execute("SELECT id FROM marathons WHERE id=?", (marathon_id,)).fetchone()
                if not m:
                    return {"success": False, "error": "마라톤을 찾을 수 없습니다"}

                code = GroupService._gen_unique_code(conn, 8)
                cur = conn.execute(
                    """
                    INSERT INTO groups (marathon_id, name, group_code, enabled, created_at, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?)
                    """,
                    (marathon_id, group_name.strip(), code, datetime.now().isoformat(), datetime.now().isoformat())
                )
                conn.commit()
                return {"success": True, "group_id": cur.lastrowid, "group_code": code}
        except Exception as e:
            return {"success": False, "error": f"{type(e).__name__}: {e}"}

    @staticmethod
    def get_by_code(group_code: str) -> Optional[Dict]:
        if not group_code:
            return None
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM groups WHERE group_code=?", (group_code.strip().upper(),)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def validate_code(group_code: str) -> Dict:
        g = GroupService.get_by_code(group_code)
        if not g:
            return {"valid": False, "message": "그룹 코드를 찾을 수 없습니다"}
        if not g.get("enabled", 1):
            return {"valid": False, "message": "비활성화된 그룹입니다"}
        return {
            "valid": True,
            "group_id": g["id"],
            "marathon_id": g["marathon_id"],
            "name": g.get("name"),
        }
