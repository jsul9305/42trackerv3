import sqlite3
from contextlib import contextmanager
from typing import Generator
from config.settings import DB_PATH

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS marathons (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  url_template TEXT NOT NULL,
  usedata TEXT,
  total_distance_km REAL NOT NULL DEFAULT 21.1,
  refresh_sec INTEGER NOT NULL DEFAULT 60,
  enabled INTEGER NOT NULL DEFAULT 1,
  cert_url_template TEXT,
  event_date TEXT,
  updated_at TEXT,
  -- 아래 4개 컬럼은 과거 DB에 없을 수 있음 (마이그레이션에서 보장)
  join_code TEXT UNIQUE,
  join_code_expires_at DATETIME,
  join_code_try_window_start DATETIME,
  join_code_try_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS participants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  marathon_id INTEGER NOT NULL REFERENCES marathons(id) ON DELETE CASCADE,
  alias TEXT,
  nameorbibno TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  race_label TEXT,
  race_total_km REAL,
  cert_key TEXT,
  finish_image_url TEXT,
  finish_image_path TEXT,
  UNIQUE(marathon_id, nameorbibno)
);

CREATE TABLE IF NOT EXISTS splits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  participant_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
  point_label TEXT NOT NULL,
  point_km REAL,
  net_time TEXT,
  pass_clock TEXT,
  pace TEXT,
  seen_at TEXT,
  UNIQUE(participant_id, point_label)
);

CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  participant_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  host TEXT,
  url TEXT,
  local_path TEXT,
  seen_at TEXT,
  UNIQUE(participant_id, kind)
);

-- 2) groups: 마라톤 내 그룹과 그룹코드
CREATE TABLE IF NOT EXISTS groups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  marathon_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  group_code TEXT NOT NULL UNIQUE,
  creator_user_id INTEGER,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (marathon_id) REFERENCES marathons(id)
);
CREATE INDEX IF NOT EXISTS idx_groups_marathon ON groups(marathon_id);
CREATE INDEX IF NOT EXISTS idx_groups_group_code ON groups(group_code);

-- 3) user_groups: 사용자-그룹 매핑 (멤버십)
CREATE TABLE IF NOT EXISTS user_groups (
  user_id INTEGER NOT NULL,
  group_id INTEGER NOT NULL,
  role TEXT DEFAULT 'member', -- 'owner' | 'member'
  joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, group_id),
  FOREIGN KEY (group_id) REFERENCES groups(id)
);

-- (옵션) track_followers: 그룹코드로만 보는 관람자를 굳이 저장할 필요 없지만,
-- 익명 팔로우/구독을 적재하고 싶다면 사용
CREATE TABLE IF NOT EXISTS track_followers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id INTEGER NOT NULL,
  viewer_fingerprint TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (group_id) REFERENCES groups(id)
);

CREATE TABLE IF NOT EXISTS groups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  marathon_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  group_code TEXT UNIQUE NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT,
  updated_at TEXT,
  FOREIGN KEY (marathon_id) REFERENCES marathons(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_groups_code ON groups(group_code);
"""

@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """DB 연결 컨텍스트 매니저"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # 외래키 강제 & busy timeout
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
    finally:
        conn.close()

def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info('{table}')")
    return any(row["name"] == column for row in cur.fetchall())

def init_database():
    """데이터베이스 초기화"""
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()

def migrate_database():
    """스키마 마이그레이션"""
    with get_db() as conn:
        # participants 보강
        for col, ddl in [
            ("race_label", "ALTER TABLE participants ADD COLUMN race_label TEXT"),
            ("race_total_km", "ALTER TABLE participants ADD COLUMN race_total_km REAL"),
            ("cert_key", "ALTER TABLE participants ADD COLUMN cert_key TEXT"),
            ("finish_image_url", "ALTER TABLE participants ADD COLUMN finish_image_url TEXT"),
            ("finish_image_path", "ALTER TABLE participants ADD COLUMN finish_image_path TEXT"),
        ]:
            try:
                if not _column_exists(conn, "participants", col):
                    conn.execute(ddl)
            except sqlite3.OperationalError:
                pass

        # marathons 보강
        for col, ddl in [
            ("cert_url_template", "ALTER TABLE marathons ADD COLUMN cert_url_template TEXT"),
            ("event_date", "ALTER TABLE marathons ADD COLUMN event_date TEXT"),
            ("join_code", "ALTER TABLE marathons ADD COLUMN join_code TEXT UNIQUE"),
            ("join_code_expires_at", "ALTER TABLE marathons ADD COLUMN join_code_expires_at DATETIME"),
            ("join_code_try_window_start", "ALTER TABLE marathons ADD COLUMN join_code_try_window_start DATETIME"),
            ("join_code_try_count", "ALTER TABLE marathons ADD COLUMN join_code_try_count INTEGER DEFAULT 0"),
        ]:
            try:
                if not _column_exists(conn, "marathons", col):
                    conn.execute(ddl)
            except sqlite3.OperationalError:
                pass

        # ✅ join_code 컬럼이 있을 때만 인덱스 생성
        if _column_exists(conn, "marathons", "join_code"):
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_marathons_join_code ON marathons(join_code)")
            except sqlite3.OperationalError:
                pass

        conn.commit()