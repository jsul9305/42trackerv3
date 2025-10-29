import re

# 거리 상수
HALF_KM = 21.0
FULL_KM = 42.1
STANDARD_DISTANCES = [5.0, 10.0, 21.1, 42.2, 50.0, 100.0, 109.0]

# 거리별 허용 오차 (km)
DISTANCE_TOLERANCE = {
    (40, float('inf')): 3,  # Full
    (20, 40): 0.8,            # Half
    (15, 20): 0.8,
    (10, 15): 1.0,            # 10-15km
    (5, 10): 0.6,
    (0, 5): 0.4,
}

# 정규식
TIME_RX = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?\b")
HM_RX = re.compile(r"\b\d{1,2}:\d{2}\b")
HMS_RX = re.compile(r"\b\d{1,2}:\d{2}:\d{2}(?:\.\d{1,2})?\b")
KM_RX = re.compile(r'(\d+(?:\.\d+)?)\s*(?:k|km)\b', re.I)

# 완주 키워드
FINISH_KEYWORDS_KO = ("도착", "완주", "골인", "결승", "피니시")
FINISH_KEYWORDS_EN = ("finish", "goal", "completed", "end")

# HTTP 헤더
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ko,en;q=0.8",
}

# ============= 종목 순서 (정렬용) =============
CATEGORY_ORDER = {
    "Full": 1,
    "32K": 2,
    "Half": 3,
    "10K": 4,
    "5K": 5,
    "3K": 6,
}
