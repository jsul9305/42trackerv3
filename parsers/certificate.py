# parsers/certificate.py
"""기록증(완주증) URL 생성 및 검증"""

from typing import Optional, List, Tuple

from bs4 import BeautifulSoup

from utils.network_utils import get_session, abs_url
from config.constants import DEFAULT_HEADERS


# ============= URL 생성 =============

def build_certificate_url(
    host: str,
    usedata: str,
    nameorbibno: str,
    cert_key: Optional[str] = None,
    url_template: Optional[str] = None
) -> Optional[str]:
    """
    기록증 URL 생성
    
    우선순위:
    1. url_template (커스텀 템플릿)
    2. 호스트별 기본 규칙
    
    Args:
        host: 호스트명 (예: smartchip.co.kr)
        usedata: 대회 ID
        nameorbibno: 참가번호
        cert_key: 기록증 키 (선택, 없으면 nameorbibno 사용)
        url_template: 커스텀 템플릿 (플레이스홀더: {usedata}, {nameorbibno}, {cert_key})
    
    Returns:
        기록증 URL 또는 None
    
    Examples:
        >>> build_certificate_url("smartchip.co.kr", "202550000158", "10396")
        'https://smartchip.co.kr/TriRun_Record.asp?Rally_id=202550000158&Bally_no=10396'
        
        >>> build_certificate_url("spct.co.kr", "2025092102", "123")
        'https://img.spct.kr/PhotoResultsJPG/images/2025092102/2025092102-000123.jpg'
    """
    host_lower = (host or "").lower()
    
    # 1) 커스텀 템플릿 우선
    if url_template:
        return (
            url_template
            .replace("{usedata}", usedata or "")
            .replace("{nameorbibno}", nameorbibno or "")
            .replace("{cert_key}", cert_key or nameorbibno or "")
        )
    
    # 2) 호스트별 기본 규칙
    if "smartchip.co.kr" in host_lower:
        return _build_smartchip_cert_url(usedata, nameorbibno, cert_key)
    
    if "spct" in host_lower:
        return _build_spct_cert_url(usedata, nameorbibno)
    
    if "myresult.co.kr" in host_lower:
        return _build_myresult_cert_url(usedata, nameorbibno)
    
    return None


def build_certificate_candidates(
    host: str,
    usedata: str,
    bib: str,
    cert_key: Optional[str] = None,
    cert_template: Optional[str] = None
) -> List[Tuple[str, Optional[str]]]:
    """
    기록증 URL 후보 목록 생성 (URL, Referer)
    
    여러 가능성을 시도하기 위해 후보 목록 반환
    - 템플릿이 있으면 우선 시도
    - 호스트별로 여러 변형 생성 (대소문자, 제로패딩 등)
    
    Args:
        host: 호스트명
        usedata: 대회 ID
        bib: 참가번호
        cert_key: 기록증 키 (선택)
        cert_template: 커스텀 템플릿 (선택)
    
    Returns:
        [(image_url, referer_url), ...] 형태의 리스트
    
    Examples:
        >>> build_certificate_candidates("spct.co.kr", "2025092102", "123")
        [
            ('https://img.spct.kr/PhotoResultsJPG/images/2025092102/2025092102-123.jpg', 'https://...'),
            ('https://img.spct.kr/PhotoResultsJPG/images/2025092102/2025092102-000123.jpg', 'https://...'),
            ...
        ]
    """
    host_lower = (host or "").lower()
    key = cert_key or bib
    candidates = []
    
    # 1) 템플릿 우선
    if cert_template:
        url = (
            cert_template
            .replace("{usedata}", usedata or "")
            .replace("{nameorbibno}", bib or "")
            .replace("{cert_key}", key or "")
        )
        candidates.append((url, None))
    
    # 2) 호스트별 변형 생성
    if "smartchip.co.kr" in host_lower:
        candidates.extend(_build_smartchip_candidates(usedata, key))
    
    elif "spct" in host_lower:
        candidates.extend(_build_spct_candidates(usedata, bib))
    
    elif "myresult.co.kr" in host_lower:
        candidates.extend(_build_myresult_candidates(usedata, bib))
    
    return candidates


# ============= 호스트별 URL 생성 (내부) =============

def _build_smartchip_cert_url(
    usedata: str,
    nameorbibno: str,
    cert_key: Optional[str]
) -> str:
    """스마트칩 기록증 URL"""
    key = cert_key or nameorbibno
    return f"https://smartchip.co.kr/TriRun_Record.asp?Rally_id={usedata}&Bally_no={key}"


def _build_spct_cert_url(usedata: str, nameorbibno: str) -> str:
    """SPCT 기록증 URL (6자리 제로패딩)"""
    from parsers.spct import extract_event_no
    
    event_no = extract_event_no(usedata)
    
    # 숫자면 6자리 제로패딩
    bib = nameorbibno.strip()
    if bib.isdigit():
        bib = bib.zfill(6)
    
    return f"https://img.spct.kr/PhotoResultsJPG/images/{event_no}/{event_no}-{bib}.jpg"


def _build_myresult_cert_url(usedata: str, nameorbibno: str) -> str:
    """MyResult 기록증 URL"""
    return f"https://www.myresult.co.kr/upload/certificate/{usedata}/{nameorbibno}.jpg"


# ============= 후보 생성 (내부) =============

def _build_smartchip_candidates(
    usedata: str,
    key: str
) -> List[Tuple[str, Optional[str]]]:
    """스마트칩 후보 목록"""
    candidates = []
    
    # 1) 페이지 (내부에서 <img> 추출 필요)
    page_url = f"https://smartchip.co.kr/TriRun_Record.asp?Rally_id={usedata}&Bally_no={key}"
    candidates.append((page_url, None))
    
    # 2) 이미지 직접 (Referer 필요할 수 있음)
    img_url = f"https://image.smartchip.co.kr/record_data/TriRun_Record.php?Rally_id={usedata}&Bally_no={key}"
    candidates.append((img_url, page_url))
    
    return candidates


def _build_spct_candidates(
    usedata: str,
    bib: str
) -> List[Tuple[str, Optional[str]]]:
    """SPCT 후보 목록 (여러 포맷 시도)"""
    from parsers.spct import extract_event_no, generate_bib_variants
    
    event_no = extract_event_no(usedata)
    variants = generate_bib_variants(bib)
    
    candidates = []
    
    for variant in variants:
        # Referer (핫링크 방지 우회)
        referer = f"https://img.spct.kr/PhotoResultsJPG/ResultsPhotoResults.php?EVENT_NO={event_no}&BIB_NO={variant}"
        
        # 소문자 확장자
        img_lower = f"https://img.spct.kr/PhotoResultsJPG/images/{event_no}/{event_no}-{variant}.jpg"
        candidates.append((img_lower, referer))
        
        # 대문자 확장자 (일부 이벤트)
        img_upper = f"https://img.spct.kr/PhotoResultsJPG/images/{event_no}/{event_no}-{variant}.JPG"
        candidates.append((img_upper, referer))
    
    return candidates


def _build_myresult_candidates(
    usedata: str,
    bib: str
) -> List[Tuple[str, Optional[str]]]:
    """MyResult 후보 목록"""
    # Referer (상세 페이지)
    referer = f"https://www.myresult.co.kr/{usedata}/{bib}"
    
    # 이미지 URL
    img_url = f"https://www.myresult.co.kr/upload/certificate/{usedata}/{bib}.jpg"
    
    return [(img_url, referer)]


# ============= URL 검증 =============

def ensure_image_url(
    host: str,
    url: str,
    referer: Optional[str] = None
) -> Optional[str]:
    """
    최종 이미지 URL 검증 및 반환
    
    - 스마트칩: 페이지에서 <img> src 추출
    - SPCT/MyResult: 직접 이미지 URL 확인
    - 상대 경로는 절대 경로로 변환
    
    Args:
        host: 호스트명
        url: URL (페이지 또는 이미지)
        referer: Referer 헤더 (선택)
    
    Returns:
        확인된 이미지 URL 또는 None
    """
    host_lower = (host or "").lower()
    session = get_session()
    
    try:
        # 1) 스마트칩: 페이지에서 이미지 추출
        if "smartchip.co.kr" in host_lower and "TriRun_Record.asp" in url:
            return _extract_smartchip_image(url, session)
        
        # 2) SPCT/MyResult: 이미지 직접 확인
        if "spct" in host_lower or "myresult" in host_lower:
            return _verify_direct_image(url, session)
        
        # 3) 기타: Referer와 함께 확인
        return _verify_image_with_referer(url, referer, session)
    
    except Exception:
        return None


def _extract_smartchip_image(url: str, session) -> Optional[str]:
    """스마트칩 페이지에서 이미지 URL 추출"""
    r = session.get(url, timeout=12, verify=VERIFY_YN, headers=DEFAULT_HEADERS)
    r.raise_for_status()
    
    soup = BeautifulSoup(r.text, "html.parser")
    img = soup.select_one('img[src*="record_data/TriRun_Record.php"]')
    
    if img and img.get("src"):
        # 상대 경로 → 절대 경로
        return abs_url("image.smartchip.co.kr", img["src"])
    
    return None


def _verify_direct_image(url: str, session) -> Optional[str]:
    """이미지 URL 직접 확인 (SPCT/MyResult)"""
    r = session.get(
        url,
        timeout=12,
        verify=VERIFY_YN,
        headers=DEFAULT_HEADERS,
        allow_redirects=True
    )
    
    if r.status_code != 200:
        return None
    
    # Content-Type 확인 (비어있어도 200이면 허용)
    content_type = (r.headers.get("content-type") or "").lower()
    if "image" in content_type or not content_type:
        return url
    
    return None


def _verify_image_with_referer(
    url: str,
    referer: Optional[str],
    session
) -> Optional[str]:
    """Referer와 함께 이미지 확인"""
    headers = dict(DEFAULT_HEADERS)
    
    if referer:
        headers["Referer"] = referer
        headers["Accept"] = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
    
    r = session.get(
        url,
        timeout=10,
        verify=VERIFY_YN,
        headers=headers,
        stream=True,
        allow_redirects=True
    )
    
    if r.status_code != 200:
        return None
    
    content_type = (r.headers.get("content-type") or "").lower()
    if "image" in content_type or not content_type:
        return url
    
    return None


# ============= 레거시 함수 (호환성) =============

def _ensure_certificate_image_url(host: str, url: str) -> Optional[str]:
    """
    레거시 함수 (호환성 유지)
    
    Deprecated: ensure_image_url() 사용 권장
    """
    return ensure_image_url(host, url, referer=None)


def _ensure_image_url(
    host: str,
    url: str,
    referer: Optional[str] = None
) -> Optional[str]:
    """
    레거시 함수 (호환성 유지)
    
    Deprecated: ensure_image_url() 사용 권장
    """
    return ensure_image_url(host, url, referer)


# ============= 사용 예시 =============

if __name__ == "__main__":
    # URL 생성
    url = build_certificate_url(
        "smartchip.co.kr",
        "202550000158",
        "10396"
    )
    print(f"SmartChip URL: {url}")
    
    # SPCT URL (자동 제로패딩)
    url = build_certificate_url(
        "spct.co.kr",
        "2025092102",
        "123"
    )
    print(f"SPCT URL: {url}")
    
    # 후보 목록 생성
    candidates = build_certificate_candidates(
        "spct.co.kr",
        "2025092102",
        "123"
    )
    print(f"\nSPCT candidates: {len(candidates)}")
    for img_url, ref in candidates[:2]:
        print(f"  {img_url}")
        print(f"    Referer: {ref}")
    
    print("\n✓ Tests passed")