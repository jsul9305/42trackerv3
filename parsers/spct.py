# parsers/spct.py
"""SPCT 전용 파서"""

import re
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


class SPCTParser(BaseParser):
    """
    SPCT (Seoul Photo & Chip Timing) 전용 파서
    
    특징:
    - 총기록: .record .time
    - Start/Finish: .record p 텍스트
    - 구간표: <table><tbody><tr><td>Section 1</td><td>시계시각 (구간기록)</td></tr>
    - 기록증: .image-container img 또는 /PhotoResultsJPG/images/
    """
    
    def can_parse(self, host: str) -> bool:
        """SPCT 호스트 확인"""
        host_lower = host.lower()
        return "spct.co.kr" in host_lower or "time.spct.co.kr" in host_lower
    
    def parse(self, html: str, **context) -> Dict[str, Any]:
        """
        HTML 파싱
        
        Args:
            html: HTML 문자열
            **context: host 등 추가 컨텍스트
        
        Returns:
            {
                'splits': List[Dict],     # 스플릿 데이터
                'summary': Dict,          # 요약 정보 (total_net, start_time, finish_time)
                'assets': List[Dict],     # 기록증 이미지
                'race_label': str,        # 종목명
                'race_total_km': float    # 총 거리
            }
        """
        soup = self._make_soup(html)
        host = context.get('host')
        
        # 1. 요약 정보 추출 (총기록, Start/Finish 시각)
        summary = self._extract_summary(soup)
        
        # 2. 구간 스플릿 추출
        splits = self._extract_splits(soup)
        
        # 3. 완주 정보 보강 (요약에만 있고 스플릿에 없는 경우)
        splits = self._ensure_finish_split(splits, summary)
        
        # 4. 기록증 추출
        assets = self._extract_certificate(soup, host)
        
        # 5. 거리 메타데이터 추출 및 정규화
        race_label, race_total_km = self._extract_and_normalize_distance(soup)
        
        return {
            'splits': splits,
            'summary': summary,
            'assets': assets,
            'race_label': race_label,
            'race_total_km': race_total_km
        }
    
    # ============= 요약 정보 추출 =============
    
    def _extract_summary(self, soup: BeautifulSoup) -> Dict[str, str]:
        """
        요약 정보 추출
        - 총기록: .record .time
        - Start Time: .record p 텍스트
        - Finish Time: .record p 텍스트
        """
        summary = {}
        
        # 총기록 (예: 03:53:41.25)
        time_elem = soup.select_one(".record .time")
        if time_elem:
            total = time_elem.get_text(strip=True)
            if total:
                summary["total_net"] = total
        
        # Start/Finish 시각
        for p in soup.select(".record p"):
            text = p.get_text(" ", strip=True)
            
            if "Start Time" in text:
                start_time = first_time(text)
                if start_time:
                    summary["start_time"] = start_time
            
            elif "Finish Time" in text:
                finish_time = first_time(text)
                if finish_time:
                    summary["finish_time"] = finish_time
        
        return summary
    
    # ============= 스플릿 추출 =============
    
    def _extract_splits(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        구간 스플릿 추출
        
        테이블 형식:
        <tr>
          <td>Section 1</td>
          <td>09:27:56.78 (00:26:16.51)</td>
        </tr>
        
        - 괄호 밖: 통과 시각 (시계)
        - 괄호 안: 구간 기록
        """
        splits = []
        
        for tr in soup.select("table tbody tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            
            label = tds[0].get_text(" ", strip=True)  # "Section 1"
            value = tds[1].get_text(" ", strip=True)  # "09:27:56.78 (00:26:16.51)"
            
            # 괄호 안 = 구간기록
            net_time = ""
            paren_match = re.search(r"\(([^)]*)\)", value)
            if paren_match:
                net_time = first_time(paren_match.group(1))
            
            # 괄호 밖 = 통과시각
            value_no_paren = re.sub(r"\([^)]*\)", " ", value)
            pass_clock = first_time(value_no_paren)
            
            # 유효한 시간이 하나라도 있으면 추가
            if net_time or pass_clock:
                splits.append({
                    "point_label": label,
                    "point_km": km_from_label(label),
                    "net_time": net_time or "",
                    "pass_clock": pass_clock or "",
                    "pace": "",  # SPCT는 pace 별도 컬럼 없음
                })
        
        return splits
    
    def _ensure_finish_split(
        self, 
        splits: List[Dict], 
        summary: Dict
    ) -> List[Dict]:
        """
        완주 정보 보강
        
        요약에는 완주 정보가 있지만 스플릿에는 없는 경우,
        Finish 행을 추가하여 웹앱에서 완주 판정이 가능하도록 함
        """
        # 이미 Finish 행이 있는지 확인
        has_finish = any(
            "finish" in (s.get("point_label", "").lower()) or
            "도착" in s.get("point_label", "")
            for s in splits
        )
        
        # Finish 행이 없고, 요약에 완주 정보가 있으면 추가
        if not has_finish and (summary.get("total_net") or summary.get("finish_time")):
            splits.append({
                "point_label": "Finish",
                "point_km": None,
                "net_time": summary.get("total_net", ""),
                "pass_clock": summary.get("finish_time", ""),
                "pace": "",
            })
        
        return splits
    
    # ============= 기록증 추출 =============
    
    def _extract_certificate(
        self, 
        soup: BeautifulSoup, 
        host: Optional[str]
    ) -> List[Dict[str, str]]:
        """
        기록증 이미지 추출
        
        예시:
        <img src="https://img.spct.kr/PhotoResultsJPG/images/2025092102/2025092102-45155.jpg">
        """
        assets = []
        
        # .image-container img 또는 /PhotoResultsJPG/images/ 경로
        img = (
            soup.select_one(".image-container img") or
            soup.select_one('img[src*="/PhotoResultsJPG/images/"]')
        )
        
        if img and img.get("src"):
            cert_url = img["src"]
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

def extract_event_no(usedata: str) -> str:
    """
    usedata에서 EVENT_NO만 추출
    
    예시:
    - "EVENT_NO=2025092102&TargetYear=2025" → "2025092102"
    - "2025092102" → "2025092102"
    
    Args:
        usedata: 대회 ID 문자열
    
    Returns:
        추출된 EVENT_NO
    """
    if not usedata:
        return ""
    
    ev = usedata.strip()
    ev = ev.replace("EVENT_NO=", "")
    ev = ev.split("&")[0].strip()
    
    return ev


def generate_bib_variants(bib: str) -> List[str]:
    """
    SPCT 서버가 요구할 수 있는 bib 포맷들을 생성
    
    우선순위:
    1. 원본
    2. 좌측 0 제거
    3. 6자리 제로패딩 (원본 기준)
    4. 6자리 제로패딩 (0 제거 기준)
    
    예시:
    - "123" → ["123", "123", "000123", "000123"]
    - "001234" → ["001234", "1234", "001234", "001234"]
    - "ABC123" → ["ABC123"]  (숫자 아니면 원본만)
    
    Args:
        bib: 참가번호
    
    Returns:
        가능한 포맷 리스트 (중복 제거됨)
    """
    if not bib:
        return []
    
    b = bib.strip()
    variants = []
    
    # 1. 원본 그대로
    variants.append(b)
    
    # 숫자 전용일 때만 변형 시도
    if b.isdigit():
        # 2. 좌측 0 제거
        b_no_zero = b.lstrip("0") or "0"
        variants.append(b_no_zero)
        
        # 3. 6자리 제로패딩 (원본 기준)
        b_padded_raw = b if len(b) >= 6 else b.zfill(6)
        variants.append(b_padded_raw)
        
        # 4. 6자리 제로패딩 (0 제거 기준)
        b_padded_trim = b_no_zero if len(b_no_zero) >= 6 else b_no_zero.zfill(6)
        variants.append(b_padded_trim)
    
    # 중복 제거 (순서 유지)
    seen = set()
    unique_variants = []
    for variant in variants:
        if variant and variant not in seen:
            seen.add(variant)
            unique_variants.append(variant)
    
    return unique_variants