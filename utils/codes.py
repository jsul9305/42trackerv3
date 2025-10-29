# utils/codes.py
import secrets, string, datetime as dt

SAFE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 32진, 헷갈리는 I1O0 제외

def gen_code(length=8):
    return ''.join(secrets.choice(SAFE_ALPHABET) for _ in range(length))

def code_expiry(hours=72):
    return dt.datetime.utcnow() + dt.timedelta(hours=hours)
