# parsers/utils.py
"""파서 공통 유틸리티 (라우팅, 폴백, 팩토리)"""

from typing import Dict, Any, Optional

from bs4 import BeautifulSoup

from parsers.smartchip import SmartchipParser
from parsers.spct import SPCTParser
from parsers.myresult import MyResultParser
from utils.distance_utils import km_from_label
from utils.time_utils import all_times


# ============= 파서 매핑 =============

PARSER_MAP = {
    "smartchip.co.kr": "smartchip",
    "spct.co.kr": "spct",
    "time.spct.co.kr": "spct",
    "myresult.co.kr": "myresult",
    "www.myresult.co.kr": "myresult",
}

# 파서 인스턴스 캐시 (싱글톤)
_PARSER_CACHE = {}


# ============= 파서 팩토리 =============

def get_parser(host: str):
    """
    호스트에 맞는 파서 인스턴스 반환 (캐싱)
    
    Args:
        host: 호스트명 (예: smartchip.co.kr)
    
    Returns:
        파서 인스턴스 또는 None
    """
    if not host:
        return None
    
    host_lower = host.lower()
    
    # 정확한 매칭
    if host_lower in PARSER_MAP:
        parser_type = PARSER_MAP[host_lower]
    else:
        # 부분 매칭 (하위 도메인 지원)
        parser_type = None
        for domain, ptype in PARSER_MAP.items():
            if domain in host_lower:
                parser_type = ptype
                break
    
    if not parser_type:
        return None
    
    # 캐시에서 가져오거나 생성
    if parser_type not in _PARSER_CACHE:
        if parser_type == "smartchip":
            _PARSER_CACHE[parser_type] = SmartchipParser()
        elif parser_type == "spct":
            _PARSER_CACHE[parser_type] = SPCTParser()
        elif parser_type == "myresult":
            _PARSER_CACHE[parser_type] = MyResultParser()
    
    return _PARSER_CACHE.get(parser_type)


# ============= 메인 파서 함수 =============

def parse(
    html: str,
    host: Optional[str] = None,
    url: Optional[str] = None,
    usedata: Optional[str] = None,
    bib: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    HTML 파싱 (라우팅 + 폴백)
    
    우선순위:
    1. 도메인별 전용 파서
    2. 범용 테이블 파서 (폴백)
    
    Args:
        html: HTML 문자열
        host: 호스트명
        url: URL (호환성 유지)
        usedata: 대회 ID (smartchip용)
        bib: 참가번호 (smartchip용)
        **kwargs: 추가 컨텍스트
    
    Returns:
        {
            'splits': List[Dict],
            'summary': Dict,
            'assets': List[Dict],
            'race_label': str,
            'race_total_km': float
        }
    """
    if not html:
        return _empty_result()
    
    host_lower = (host or "").lower()
    
    # 1) 도메인별 전용 파서 시도
    parser = get_parser(host_lower)
    if parser:
        try:
            context = {
                'host': host,
                'url': url,
                'usedata': usedata,
                'bib': bib,
                **kwargs
            }
            
            result = parser.parse(html, **context)
            if result:
                return _ensure_defaults(result)
        
        except Exception as e:
            print(f"[warn] domain parser failed ({host_lower}): {type(e).__name__}: {e}")
    
    # 2) 범용 테이블 파서 (폴백)
    return parse_generic_table(html)


# ============= 범용 파서 =============

def parse_generic_table(html: str) -> Dict[str, Any]:
    """
    범용 테이블 파서 (폴백)
    
    모든 <table>을 순회하며 시간 패턴이 있는 행 추출
    - 첫 컬럼: 라벨
    - 나머지: 시간 추출 (첫 번째=net, 두 번째=clock)
    
    Args:
        html: HTML 문자열
    
    Returns:
        표준 포맷 딕셔너리
    """
    soup = BeautifulSoup(html or "", "html.parser")
    splits = []
    
    for tr in soup.select("table tr"):
        cols = [c.get_text(" ", strip=True) for c in tr.select("th, td")]
        
        if len(cols) < 2:
            continue
        
        label = cols[0]
        rest_text = " ".join(cols[1:])
        times = all_times(rest_text)
        
        if not times:
            continue
        
        net = times[0] if times else ""
        clk = times[1] if len(times) > 1 else ""
        
        splits.append({
            "point_label": label,
            "point_km": km_from_label(label),
            "net_time": net,
            "pass_clock": clk,
            "pace": "",
        })
    
    return {
        'splits': splits,
        'summary': {},
        'assets': [],
        'race_label': None,
        'race_total_km': None
    }


# ============= 헬퍼 함수 =============

def _empty_result() -> Dict[str, Any]:
    """빈 결과 딕셔너리"""
    return {
        'splits': [],
        'summary': {},
        'assets': [],
        'race_label': None,
        'race_total_km': None
    }


def _ensure_defaults(result: Dict[str, Any]) -> Dict[str, Any]:
    """결과 딕셔너리에 기본값 보장"""
    result.setdefault('splits', [])
    result.setdefault('summary', {})
    result.setdefault('assets', [])
    result.setdefault('race_label', None)
    result.setdefault('race_total_km', None)
    return result


# ============= 편의 함수 =============

def can_parse(host: str) -> bool:
    """해당 호스트를 파싱할 수 있는지 확인"""
    return get_parser(host) is not None


def list_supported_hosts() -> list[str]:
    """지원하는 호스트 목록"""
    return list(PARSER_MAP.keys())


# ============= 사용 예시 =============

if __name__ == "__main__":
    # 지원 호스트 확인
    print("Supported hosts:", list_supported_hosts())
    
    # 파서 팩토리
    parser = get_parser("smartchip.co.kr")
    print(f"Parser: {parser.__class__.__name__ if parser else 'None'}")
    
    # 파싱 테스트
    sample = """
    <table>
        <tr><th>Point</th><th>Time</th></tr>
        <tr><td>5km</td><td>00:25:30</td></tr>
    </table>
    """
    
    result = parse(sample, host="unknown.com")
    print(f"Splits: {len(result['splits'])}")
    
    print("✓ Tests passed")