# utils/network_utils.py
"""네트워크 관련 유틸리티"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib.parse
import random
import time
import threading

from config.settings import VERIFY_SSL_DEFAULT, CRAWLER_MAX_WORKERS, INSECURE_HOSTS
from config.constants import DEFAULT_HEADERS


# ============= Session 싱글톤 =============
_SESSION = None
_SESSION_LOCK = threading.Lock()


def get_session() -> requests.Session:
    """
    전역 requests.Session 반환 (싱글톤)
    
    - 연결 풀 재사용으로 성능 향상
    - 자동 재시도 설정
    - 스레드 안전
    
    Returns:
        requests.Session 인스턴스
    """
    global _SESSION
    
    with _SESSION_LOCK:
        if _SESSION is None:
            _SESSION = _create_session()
    
    return _SESSION


def _create_session() -> requests.Session:
    """새로운 Session 객체 생성 (내부용)"""
    sess = requests.Session()
    
    # 재시도 전략
    retry = Retry(
        total=2,
        backoff_factor=0.2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"])
    )
    
    # 연결 풀 설정 (동시성에 맞춰 조정)
    pool_size = CRAWLER_MAX_WORKERS * 2
    adapter = HTTPAdapter(
        pool_connections=pool_size,
        pool_maxsize=pool_size,
        max_retries=retry
    )
    
    sess.mount("http://", adapter)
    sess.mount("https://", adapter)
    
    # 기본 헤더 설정
    sess.headers.update(DEFAULT_HEADERS)
    
    return sess


def reset_session():
    """Session 초기화 (테스트용)"""
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION:
            _SESSION.close()
            _SESSION = None


# ============= URL 유틸리티 =============

def add_cache_buster(url: str) -> str:
    """
    캐시 방지를 위한 쿼리 파라미터 추가
    _ts, rand, (필요시) Submit.x/Submit.y
    
    Args:
        url: 원본 URL
    
    Returns:
        캐시 버스터가 추가된 URL
    """
    u = urllib.parse.urlsplit(url)
    qs = urllib.parse.parse_qs(u.query, keep_blank_values=True)
    
    # 타임스탬프
    ts = str(int(time.time()))
    qs["_ts"] = [ts]
    qs["rand"] = [str(random.randint(100000, 999999))]
    
    # 스마트칩 특수 처리
    if u.path.endswith("/return_data_livephoto.asp"):
        qs.setdefault("Submit.x", [str(random.randint(10, 80))])
        qs.setdefault("Submit.y", [str(random.randint(5, 30))])
    
    new_query = urllib.parse.urlencode({k: v[-1] for k, v in qs.items()})
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, new_query, u.fragment))


def normalize_url(url: str) -> str:
    """
    URL 정규화 (스킴 추가)
    
    Args:
        url: URL (스킴 있거나 없거나)
    
    Returns:
        정규화된 URL (https://)
    """
    if not url.startswith(("http://", "https://")):
        return "https://" + url.lstrip("/")
    return url


def abs_url(base_host: str, url: str) -> str:
    """
    상대 경로를 절대 URL로 변환
    
    Args:
        base_host: 베이스 호스트 (예: smartchip.co.kr)
        url: 상대 또는 절대 경로
    
    Returns:
        절대 URL
    
    Examples:
        >>> abs_url("smartchip.co.kr", "/path/to/image.jpg")
        'https://smartchip.co.kr/path/to/image.jpg'
    """
    if not url:
        return url
    
    if url.startswith(("http://", "https://")):
        return url
    
    scheme = "https"
    host = base_host
    
    # myresult는 www 사용
    if "myresult.co.kr" in base_host and not base_host.startswith("www."):
        host = "www.myresult.co.kr"
    
    return urllib.parse.urlunsplit((scheme, host, url, "", ""))


# ============= SSL 검증 =============

def verify_for_host(host: str) -> bool:
    """
    특정 호스트에 대한 SSL 검증 여부 결정
    
    Args:
        host: 호스트명 (예: smartchip.co.kr)
    
    Returns:
        True면 검증, False면 무시
    """
    host = (host or "").lower()
    return host not in INSECURE_HOSTS and VERIFY_SSL_DEFAULT


# ============= 사용 예시 =============

if __name__ == "__main__":
    # Session 가져오기
    print("Testing network_utils...")
    
    session = get_session()
    print(f"✓ Session created: {session}")
    
    # 캐시 방지
    url = "https://smartchip.co.kr/data.asp?id=123"
    busted_url = add_cache_buster(url)
    print(f"\nCache buster:")
    print(f"  Original: {url}")
    print(f"  Busted: {busted_url}")
    
    # URL 정규화
    print(f"\nURL normalization:")
    print(f"  normalize_url('example.com') = {normalize_url('example.com')}")
    print(f"  normalize_url('https://example.com') = {normalize_url('https://example.com')}")
    
    # 절대 URL
    print(f"\nAbsolute URL:")
    print(f"  abs_url('smartchip.co.kr', '/image.jpg') = {abs_url('smartchip.co.kr', '/image.jpg')}")
    
    # SSL 검증
    print(f"\nSSL verification:")
    print(f"  verify_for_host('smartchip.co.kr'): {verify_for_host('smartchip.co.kr')}")
    print(f"  verify_for_host('google.com'): {verify_for_host('google.com')}")
    
    print("\n✓ All tests passed")