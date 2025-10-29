import os, requests, threading
from pathlib import Path

# ============= 경로 설정 =============
BASE_DIR = Path(__file__).parent.parent.absolute()
DB_PATH = BASE_DIR / "smartchip.db"

# 정적 파일
STATIC_DIR = BASE_DIR / "static"
CERT_DIR = STATIC_DIR / "certs"
CERT_DIR.mkdir(parents=True, exist_ok=True)

# 웹앱 설정
WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT = int(os.getenv("WEBAPP_PORT", "5010"))
WEBAPP_DEBUG = os.getenv("WEBAPP_DEBUG", "0") == "1"

# 크롤러 설정
CRAWLER_MAX_WORKERS = int(os.getenv("CRAWLER_MAX_WORKERS", "24"))
CRAWLER_CACHE_TTL = int(os.getenv("CRAWLER_CACHE_TTL", "30"))

# SSL 검증
# 기본: 검증 ON. 전역으로 끄려면 SMARTCHIP_INSECURE_SSL=1
VERIFY_SSL_DEFAULT = os.getenv("SMARTCHIP_INSECURE_SSL", "0") != "1"
# 특정 호스트만 검증 OFF (쉼표로 구분)
# 예: SMARTCHIP_INSECURE_HOSTS="smartchip.co.kr,example.com"
# 변경 (기본값에 smartchip 추가)
default_insec = "smartchip.co.kr,www.smartchip.co.kr, myresult.co.kr, image.smartchip.co.kr, img.spct.kr"
INSECURE_HOSTS = set(
    h.strip().lower()
    for h in os.getenv("SMARTCHIP_INSECURE_HOSTS", default_insec).split(",")
    if h.strip()
)
# SSL 경고 숨김
if (not VERIFY_SSL_DEFAULT) or INSECURE_HOSTS:
    try:
        import requests
        requests.packages.urllib3.disable_warnings()
    except Exception:
        pass

# MAX_WORKERS = int(os.getenv("CRAWLER_MAX_WORKERS", "12"))  # 전체 동시 요청 수
MAX_WORKERS = int(os.getenv("CRAWLER_MAX_WORKERS", "24"))  # 24-32로 증가