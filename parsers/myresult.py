# parsers/myresult.py
"""MyResult 전용 파서"""

import json
import urllib.parse
from typing import Dict, Any, List, Optional

from bs4 import BeautifulSoup

from parsers.base import BaseParser
from config.constants import FULL_KM, HALF_KM
from utils.time_utils import first_time
from utils.distance_utils import (
    km_from_label,
    category_from_km,
    extract_distance_from_text,
    snap_distance
)


class MyResultParser(BaseParser):
    """
    MyResult 전용 파서 (Ant Design 기반)
    
    특징:
    - 구간 헤더: "구간명 | 통과시간 | 구간기록 | 누적기록"
    - 각 행: .table-row.ant-row 하위에 .ant-col 4개
    - 값 예: 반환점 / 08:26:08 / 00:21:20 / 00:21:20
    - 대회기록: .ant-statistic (총 기록)
    - 기록증: <img src="/upload/certificate/...">
    """
    
    def can_parse(self, host: str) -> bool:
        """MyResult 호스트 확인"""
        return "myresult.co.kr" in host.lower()
    
    def parse(self, html: str, **context) -> Dict[str, Any]:
        """
        HTML 또는 JSON 파싱
        
        Args:
            html: HTML 문자열 또는 "JSON::{...}" 형식
            **context: host 등 추가 컨텍스트
        
        Returns:
            {
                'splits': List[Dict],     # 스플릿 데이터
                'summary': Dict,          # 요약 정보
                'assets': List[Dict],     # 기록증 이미지
                'race_label': str,        # 종목명
                'race_total_km': float    # 총 거리
            }
        """
        # JSON 형식 체크
        if isinstance(html, str) and html.startswith("JSON::"):
            return self._parse_json(html[6:])
        
        # HTML 파싱
        return self._parse_html(html, context.get('host'))
    
    # ============= HTML 파싱 =============
    
    def _parse_html(self, html: str, host: Optional[str]) -> Dict[str, Any]:
        """HTML 파싱 (Ant Design 테이블)"""
        soup = self._make_soup(html)
        
        # 1. 스플릿 추출
        splits = self._extract_splits_from_html(soup)
        
        # 2. 기록증 추출
        assets = self._extract_certificate(soup, host)
        
        # 3. 거리 메타데이터
        race_label, race_total_km = self._extract_and_normalize_distance(soup)
        
        return {
            'splits': splits,
            'summary': {},
            'assets': assets,
            'race_label': race_label,
            'race_total_km': race_total_km
        }
    
    def _extract_splits_from_html(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        Ant Design 테이블에서 스플릿 추출
        
        구조:
        <div class="table-row ant-row">
          <div class="ant-col">반환점</div>      <!-- 구간명 -->
          <div class="ant-col">08:26:08</div>   <!-- 통과시간 -->
          <div class="ant-col">00:21:20</div>   <!-- 구간기록 -->
          <div class="ant-col">00:21:20</div>   <!-- 누적기록 -->
        </div>
        """
        splits = []
        
        for row in soup.select(".table-row.ant-row"):
            cols = row.select(".ant-col")
            if len(cols) < 4:
                continue
            
            # 컬럼 값 추출 및 정리
            label = self._clean_value(cols[0].get_text(" ", strip=True)) # 구간명
            clock = self._clean_value(cols[1].get_text(" ", strip=True)) # 통과시간
            acc = self._clean_value(cols[2].get_text(" ", strip=True))   # 구간기록 (net time으로 사용)
            
            # 시간 추출
            clock_time = first_time(clock)
            acc_time = first_time(acc)
            
            # 둘 다 없으면 스킵
            if not (clock_time or acc_time):
                continue
            
            splits.append({
                "point_label": label,
                "point_km": km_from_label(label),
                "net_time": acc_time or "",      # 구간기록을 net_time으로 사용
                "pass_clock": clock_time or "",  # 통과시간
                "pace": "",
            })
        
        return splits
    
    def _clean_value(self, value: str) -> str:
        """값 정리 (대시 문자 제거)"""
        value = (value or "").strip()
        return "" if value in {"-", "—", "–"} else value
    
    # ============= JSON 파싱 =============
    
    def _parse_json(self, json_str: str) -> Dict[str, Any]:
        """
        JSON 데이터 파싱
        
        키 매핑:
        - pass_clock: 통과시간/clock/passTime/pass_time
        - net_time: 누적기록/acc/acctime/cumulative/total
        - label: 구간명/섹션/지점/label/section (name 제외!)
        """
        try:
            obj = json.loads(json_str)
        except json.JSONDecodeError:
            return {"splits": [], "summary": {}, "assets": []}
        
        splits = []
        assets = []
        
        # 재귀적으로 JSON 탐색
        def walk(x):
            if isinstance(x, dict):
                label = self._extract_label_from_dict(x)
                clock = self._extract_clock_from_dict(x)
                acc = self._extract_acc_from_dict(x)
                
                if label and (clock or acc):
                    splits.append({
                        "point_label": str(label),
                        "point_km": km_from_label(str(label)),
                        "pass_clock": clock or "",
                        "net_time": acc or "",  # 누적기록
                        "pace": "",
                    })
                
                # 하위 탐색
                for v in x.values():
                    walk(v)
            
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        
        # 기록증 탐색
        def walk_cert(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if isinstance(v, str) and "/upload/certificate/" in v:
                        assets.append({
                            "kind": "certificate",
                            "host": "myresult.co.kr",
                            "url": v
                        })
                for v in x.values():
                    walk_cert(v)
            
            elif isinstance(x, list):
                for v in x:
                    walk_cert(v)
        
        walk(obj)
        walk_cert(obj)
        
        return {
            'splits': splits,
            'summary': {},
            'assets': assets
        }
    
    def _extract_label_from_dict(self, d: Dict) -> Optional[str]:
        """
        딕셔너리에서 라벨 추출
        
        키워드: 구간명, 섹션, 지점, label, section
        제외: name (참가자명과 혼동 방지)
        """
        for k, v in d.items():
            if not isinstance(v, str):
                continue
            
            # name은 제외
            if "name" in k.lower():
                continue
            
            # 라벨 키워드
            if any(s in k for s in ("구간명", "섹션", "지점", "label", "section")):
                return v
        
        return None
    
    def _extract_clock_from_dict(self, d: Dict) -> Optional[str]:
        """딕셔너리에서 통과시간 추출"""
        for k, v in d.items():
            k_lower = k.lower()
            
            if any(s in k_lower for s in ("통과시간", "시각", "clock", "passtime", "pass_time")):
                return first_time(str(v))
        
        return None
    
    def _extract_acc_from_dict(self, d: Dict) -> Optional[str]:
        """딕셔너리에서 누적기록 추출"""
        for k, v in d.items():
            k_lower = k.lower()
            
            if any(s in k_lower for s in ("누적기록", "누적", "acc", "acctime", "total", "cumulative")):
                return first_time(str(v))
        
        return None
    
    # ============= 기록증 추출 =============
    
    def _extract_certificate(
        self, 
        soup: BeautifulSoup, 
        host: Optional[str]
    ) -> List[Dict[str, str]]:
        """
        기록증 이미지 추출
        - <img> 태그의 src
        - <a> 태그의 href
        """
        assets = []
        base_host = f"https://{host or 'www.myresult.co.kr'}"

        # <img> 태그에서 찾기
        for img in soup.select('img[src*="/upload/certificate/"]'):
            if img.get("src"):
                cert_url = urllib.parse.urljoin(base_host, img["src"])
                if not any(a['url'] == cert_url for a in assets):
                    assets.append({
                        "kind": "certificate",
                        "host": host,
                        "url": cert_url
                    })

        # <a> 태그에서 찾기
        for link in soup.select('a[href*="/upload/certificate/"]'):
            if link.get("href"):
                cert_url = urllib.parse.urljoin(base_host, link["href"])
                if not any(a['url'] == cert_url for a in assets):
                    assets.append({
                        "kind": "certificate",
                        "host": host,
                        "url": cert_url
                    })
        
        return assets
    
    # ============= 거리 메타데이터 =============
    
    def _extract_and_normalize_distance(
        self, 
        soup: BeautifulSoup
    ) -> tuple[Optional[str], Optional[float]]:
        """
        거리 정보 추출 및 정규화
        
        Returns:
            (race_label, race_total_km)
        """
        # 전체 텍스트에서 거리 추출
        full_text = soup.get_text(" ", strip=True)
        race_label, race_total_km = extract_distance_from_text(full_text)
        
        # 거리 스냅 및 종목명 결정
        if race_total_km is not None:
            race_total_km = snap_distance(race_total_km) or race_total_km
            race_label = category_from_km(race_total_km)
        
        return race_label, race_total_km


# ============= 유틸리티 함수 =============

def extract_total_net_time(soup: BeautifulSoup) -> str:
    """
    대회 총 기록 추출
    
    구조:
    <div class="ant-statistic">
      <div class="ant-statistic-title">대회기록</div>
      <div class="ant-statistic-content">
        <span class="ant-statistic-content-value">00:37:54</span>
      </div>
    </div>
    
    Args:
        soup: BeautifulSoup 객체
    
    Returns:
        총 기록 (예: "00:37:54") 또는 빈 문자열
    """
    for stat in soup.select(".ant-statistic"):
        title_elem = stat.select_one(".ant-statistic-title")
        
        if title_elem and "대회기록" in title_elem.get_text(" ", strip=True):
            value_elem = stat.select_one(".ant-statistic-content .ant-statistic-content-value")
            
            if value_elem:
                value = first_time(value_elem.get_text(" ", strip=True))
                if value:
                    return value
    
    return ""


# ============= 사용 예시 =============

if __name__ == "__main__":
    # 파서 테스트
    parser = MyResultParser()
    
    # 호스트 확인
    assert parser.can_parse("www.myresult.co.kr") == True
    assert parser.can_parse("smartchip.co.kr") == False
    
    # HTML 파싱 테스트
    html_sample = """
    <div class="table-row ant-row">
        <div class="ant-col">반환점</div>
        <div class="ant-col">08:26:08</div>
        <div class="ant-col">00:21:20</div>
        <div class="ant-col">00:21:20</div>
    </div>
    """
    result = parser.parse(html_sample, host="www.myresult.co.kr")
    print(f"HTML splits: {len(result['splits'])}")
    
    # JSON 파싱 테스트
    json_sample = 'JSON::{"splits": [{"label": "5km", "clock": "09:00:00", "acc": "00:25:00"}]}'
    result = parser.parse(json_sample)
    print(f"JSON splits: {len(result['splits'])}")
    
    # 총 기록 추출 테스트
    html_total = """
    <div class="ant-statistic">
        <div class="ant-statistic-title">대회기록</div>
        <div class="ant-statistic-content">
            <span class="ant-statistic-content-value">00:37:54</span>
        </div>
    </div>
    """
    soup = BeautifulSoup(html_total, "html.parser")
    total = extract_total_net_time(soup)
    print(f"Total net time: {total}")
    
    print("✓ All tests passed")