# parsers/smartchip.py
"""스마트칩 전용 파서"""

import re
import urllib.parse
from html import unescape
from typing import Optional, Dict, Any, List, Tuple

from bs4 import BeautifulSoup

from parsers.base import BaseParser
from config.constants import FULL_KM, HALF_KM
from utils.network_utils import get_session, normalize_url
from utils.distance_utils import extract_distance_from_text, snap_distance, km_from_label, category_from_km
from utils.time_utils import first_time


class SmartchipParser(BaseParser):
    """
    스마트칩 전용 파서
    - 진행 중/종료 자동 감지
    - 3가지 테이블 포맷 지원 (v1, v2, v3)
    """
    
    def can_parse(self, host: str) -> bool:
        """스마트칩 호스트 확인"""
        return "smartchip.co.kr" in host.lower()
    
    def parse(self, html: str, **context) -> Dict[str, Any]:
        """
        HTML 파싱
        
        Args:
            html: HTML 문자열
            **context: usedata, bib 등 추가 컨텍스트
        
        Returns:
            {
                'splits': List[Dict],  # 스플릿 데이터
                'summary': Dict,       # 요약 정보
                'assets': List[Dict],  # 기록증 등
                'race_label': str,     # 종목명
                'race_total_km': float,# 총 거리
                'state': str           # 진행 상태
            }
        """
        usedata = context.get('usedata')
        bib = context.get('bib')
        host = context.get('host')
        
        # 1) 상세 페이지 확보 (진행중/종료 자동 구분)
        if usedata and bib:
            soup, state = self._resolve_detail_soup(usedata, bib, host)
        else:
            soup = self._make_soup(html)
            state = "unknown"
        
        if not soup:
            soup = self._make_soup(html)
            state = "fallback"
        
        # 2) 테이블 파싱
        parsed = self._parse_table(soup)
        
        # 에셋 추출
        parsed['assets'] = self._extract_assets(soup, host)
        
        # 3) 거리 메타데이터 추출 및 정규화
        race_label, race_total_km = self._extract_and_normalize_distance(
            soup, 
            parsed.get('splits')
        )
        
        parsed['race_label'] = race_label
        parsed['race_total_km'] = race_total_km
        parsed['state'] = state
        parsed['host'] = host # ✅ 호스트 정보 추가
        
        return parsed
    
    # ============= 테이블 파싱 =============
    
    def _parse_table(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """
        테이블 파싱 (3가지 포맷 시도)
        우선순위: v1 → v2 → v3
        """
        # v1: <table class="result-table">
        result_v1 = self._parse_table_v1(soup)
        if result_v1 and result_v1.get('splits'):
            return result_v1
        
        # v2: POINT | TIME | TIME OF DAY | PACE 헤더
        result_v2 = self._parse_table_v2(soup)
        if result_v2 and result_v2.get('splits'):
            return result_v2
        
        # v3: td.userinfo 반복
        return self._parse_table_v3(soup) or result_v2 or result_v1 or {"splits": [], "summary": {}, "assets": []}
    
    def _parse_table_v1(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """
        v1 테이블 파싱
        <table class="result-table">
          <tr><td>POINT</td><td>TIME</td><td>PASS TIME</td><td>PACE</td></tr>
          <tr><td>5.0km</td><td>00:25:30</td><td>09:25:30</td><td>05:06</td></tr>
        </table>
        """
        table = soup.select_one("table.result-table")
        if not table:
            return {"splits": [], "summary": {}, "assets": []}
        
        rows = []
        for tr in table.select("tr")[1:]:  # 헤더 제외
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) < 4:
                continue
            
            point, net, clk, pace = tds[0], tds[1], tds[2], tds[3]
            point_km = km_from_label(point)
            
            rows.append({
                "point_label": point,
                "point_km": point_km,
                "net_time": net,
                "pass_clock": clk,
                "pace": pace,
            })
        
        return {"splits": rows, "summary": {}, "assets": []}
    
    def _parse_table_v2(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """
        v2 테이블 파싱 (진행 중 페이지)
        헤더: POINT | TIME | TIME OF DAY | PACE(min/km)
        """
        table, header_idx = self._find_table_with_headers(
            soup, 
            ["POINT", "TIME", "TIME OF DAY", "PACE"]
        )
        
        if not table:
            return {"splits": [], "summary": {}, "assets": []}
        
        # 컬럼 인덱스 매핑
        col_map = {
            "POINT": self._get_col_index(header_idx, "POINT"),
            "TIME": self._get_col_index(header_idx, "TIME"),
            "TIME OF DAY": self._get_col_index(header_idx, "TIME OF DAY"),
            "PACE": self._get_col_index(header_idx, "PACE"),
        }
        
        rows = []
        data_started = False
        
        for tr in table.select("tr"):
            cols = [c.get_text(" ", strip=True) for c in tr.select("td,th")]
            
            # 헤더 행 스킵
            if not data_started:
                if set([c.upper() for c in cols]) & {"POINT", "TIME", "TIME OF DAY", "PACE"}:
                    data_started = True
                continue
            
            if not cols:
                continue
            
            # 데이터 추출
            point = self._get_col_value(cols, col_map["POINT"])
            net = self._get_col_value(cols, col_map["TIME"])
            clk = self._get_col_value(cols, col_map["TIME OF DAY"])
            pace = self._get_col_value(cols, col_map["PACE"])
            
            # 유효성 검증
            if not point or not any([net, clk, pace]):
                continue
            
            point_km = km_from_label(point)
            
            rows.append({
                "point_label": point,
                "point_km": point_km,
                "net_time": net,
                "pass_clock": clk,
                "pace": pace,
            })
        
        return {"splits": rows, "summary": {}, "assets": []}
    
    def _parse_table_v3(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """
        v3 테이블 파싱
        td.userinfo가 4개 이상 반복되는 행
        첫 셀: '43.0Km' 같은 지점 라벨
        """
        rows = []
        
        for tr in soup.select("table tr"):
            tds = tr.select("td.userinfo")
            if len(tds) < 4:
                continue
            
            point = tds[0].get_text(" ", strip=True)
            net = tds[1].get_text(" ", strip=True)
            clk = tds[2].get_text(" ", strip=True)
            pace = tds[3].get_text(" ", strip=True)
            
            # 'Km' 패턴 확인
            if not re.search(r"\d+(?:\.\d+)?\s*(?:km|k)\b", point, re.I):
                continue
            
            point_km = km_from_label(point)
            
            rows.append({
                "point_label": point,
                "point_km": point_km,
                "net_time": first_time(net) or net.strip(),
                "pass_clock": first_time(clk) or clk.strip(),
                "pace": pace.strip(),
            })
        
        return {"splits": rows, "summary": {}, "assets": []}
    
    def _extract_assets(self, soup: BeautifulSoup, host: str) -> List[Dict[str, Any]]:
        """라이브포토, 기록증 등 이미지 에셋 추출"""
        assets = []
        base_url = f"https://{host or 'smartchip.co.kr'}"

        # 1. 기록증 (<a> 태그)
        for link in soup.select('a[href*="certificate"]'):
            href = link.get('href')
            if href:
                cert_url = urllib.parse.urljoin(base_url, href)
                if not any(a['url'] == cert_url for a in assets):
                    assets.append({
                        "kind": "certificate",
                        "host": host,
                        "url": cert_url
                    })

        # 2. 라이브포토 (<img> 태그)
        for img in soup.select('img[src*="livephoto"]'):
            src = img.get('src')
            if src:
                img_url = urllib.parse.urljoin(base_url, src)
                if not any(a['url'] == img_url for a in assets):
                    assets.append({
                        "kind": "livephoto",
                        "host": host,
                        "url": img_url
                    })
        
        return assets

    # ============= 거리 메타데이터 =============
    
    def _extract_and_normalize_distance(
        self, 
        soup: BeautifulSoup, 
        splits: List[Dict]
    ) -> Tuple[Optional[str], Optional[float]]:
        """
        거리 정보 추출 및 정규화
        
        우선순위:
        1. 헤더 텍스트 (h6.green 등)
        2. iframe rallyname 파라미터
        3. 테이블 최대 km
        
        Returns:
            (race_label, race_total_km)
        """
        # 1) 헤더에서 추출
        race_label, race_total_km = self._extract_distance_from_header(soup)
        
        # 2) iframe에서 추출
        if race_total_km is None:
            race_label, race_total_km = self._extract_distance_from_iframe(soup)
        
        # 3) 테이블 최대값
        if race_total_km is None and splits:
            kms = [s.get("point_km") for s in splits if s.get("point_km") is not None]
            if kms:
                race_total_km = max(kms)
                race_label = race_label or f"{race_total_km:g}K"
        
        # 0 또는 1km 미만은 무시 (스타트 행만 있는 경우)
        if race_total_km is not None and race_total_km < 1.0:
            return None, None
        
        # 거리 스냅 및 종목명 결정
        if race_total_km is not None:
            race_total_km = snap_distance(race_total_km) or race_total_km
            race_label = category_from_km(race_total_km)
        
        return race_label, race_total_km
    
    def _extract_distance_from_header(
        self, 
        soup: BeautifulSoup
    ) -> Tuple[Optional[str], Optional[float]]:
        """헤더 텍스트에서 거리 추출 (h6.green 등)"""
        for el in soup.select("h6.green, .green, h6"):
            txt = el.get_text(" ", strip=True).lower()
            label, km = extract_distance_from_text(txt)
            if km is not None:
                return (label or f"{km:g}K", km)
        return None, None
    
    def _extract_distance_from_iframe(
        self, 
        soup: BeautifulSoup
    ) -> Tuple[Optional[str], Optional[float]]:
        """iframe rallyname 파라미터에서 거리 추출"""
        iframe = soup.select_one('iframe#main_frame[src*="rallyname="], iframe[src*="rallyname="]')
        if not iframe or not iframe.get("src"):
            return None, None
        
        query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(iframe["src"]).query,
            keep_blank_values=True
        )
        rallyname = (query.get("rallyname") or [""])[0]
        
        label, km = extract_distance_from_text(rallyname)
        if km is not None:
            return (label or f"{km:g}K", km)
        
        return None, None
    
    # ============= 상세 페이지 해결 =============
    
    def _resolve_detail_soup(
        self, 
        usedata: str, 
        bib: str, 
        host: Optional[str] = "smartchip.co.kr",
        timeout: int = 10
    ) -> Tuple[Optional[BeautifulSoup], str]:
        """
        진행 중/종료 페이지 자동 해결
        
        Returns:
            (soup, state)
            state: 'in_progress' | 'finished' | 'in_progress_no_table' | 'unknown'
        """
        session = get_session()
        
        target_host = host or "smartchip.co.kr"
        
        # 1) 진행 중 페이지 시도
        soup1 = self._fetch_url_both_schemes(
            f"/Expectedrecord_data.asp?usedata={usedata}&nameorbibno={bib}",
            target_host, session,
            timeout
        )
        if soup1 and self._has_split_table(soup1):
            return soup1, "in_progress"
        
        # 2) 종료 페이지 시도
        soup2 = self._fetch_url_both_schemes(
            f"/return_data_livephoto.asp?usedata={usedata}&nameorbibno={bib}",
            target_host, session,
            timeout
        )
        if soup2 and self._has_split_table(soup2):
            return soup2, "finished"
        
        # 둘 다 테이블이 없으면 우선순위로 반환
        return (soup1 or soup2), "in_progress_no_table" if (soup1 or soup2) else "unknown"
    
    def _fetch_url_both_schemes(
        self, 
        url_path: str, 
        host: str,
        session, 
        timeout: int = 10
    ) -> Optional[BeautifulSoup]:
        """https/http 양쪽 시도"""
        for scheme in ("https://", "http://"):
            url = scheme + host + (url_path if url_path.startswith("/") else "/" + url_path)
            try:
                r = session.get(url, timeout=timeout, allow_redirects=True)
                r.raise_for_status()
                return BeautifulSoup(r.text, "html.parser")
            except Exception:
                continue
        return None
    
    # ============= 유틸리티 =============
    
    def _has_split_table(self, soup: BeautifulSoup) -> bool:
        """스플릿 테이블이 있는지 확인"""
        # v1: result-table 클래스
        if soup.select_one("table.result-table"):
            return len(soup.select("table.result-table tr")) >= 2
        
        # v2: POINT/TIME/TIME OF DAY/PACE 헤더
        for tr in soup.select("table tr"):
            headers = [h.get_text(" ", strip=True).upper() for h in tr.select("td,th")]
            if {"POINT", "TIME", "TIME OF DAY", "PACE"}.issubset(set(headers)):
                return True
        
        # v3: td.userinfo 반복
        for tr in soup.select("table tr"):
            tds = tr.select("td.userinfo")
            if len(tds) >= 4:
                first = tds[0].get_text(" ", strip=True)
                if re.search(r"\d+(?:\.\d+)?\s*(?:km|k)\b", first, re.I):
                    return True
        
        return False
    
    def _is_wrapper_home(self, soup: BeautifulSoup) -> bool:
        """PWA 홈 래퍼 페이지인지 확인"""
        return soup.select_one('iframe#myFrame[src*="main.html"]') is not None
    
    def _looks_detail_page(self, soup: BeautifulSoup) -> bool:
        """상세 페이지인지 확인"""
        # 지도 iframe 확인
        if soup.select_one('iframe#main_frame[src*="mapsub/nogpx_map_marathon"]'):
            return True
        
        # 종목 텍스트 확인
        for el in soup.select("h6.green, .green, h6"):
            if re.search(r'\b\d+(?:\.\d+)?\s*km\b', el.get_text(" ", strip=True).lower()):
                return True
        
        return False
    
    def _find_table_with_headers(
        self, 
        soup: BeautifulSoup, 
        required_headers: List[str]
    ) -> Tuple[Optional[BeautifulSoup], Optional[List[str]]]:
        """특정 헤더를 가진 테이블 찾기"""
        for tr in soup.select("table tr"):
            cols = [c.get_text(" ", strip=True) for c in tr.select("td,th")]
            upper_cols = [x.upper() for x in cols]
            
            if set(required_headers).issubset(set(upper_cols)):
                return tr.find_parent("table"), upper_cols
        
        return None, None
    
    def _get_col_index(self, header: List[str], name: str) -> Optional[int]:
        """헤더에서 컬럼 인덱스 찾기"""
        try:
            return header.index(name.upper())
        except (ValueError, AttributeError):
            return None
    
    def _get_col_value(self, cols: List[str], index: Optional[int]) -> str:
        """인덱스로 컬럼 값 가져오기"""
        if index is None or index >= len(cols):
            return ""
        return cols[index]


# ============= 고급 페이지 페칭 (선택적) =============

def fetch_smartchip_page(
    base_url: str,
    *,
    usedata: Optional[str] = None,
    bib: Optional[str] = None,
    rallyinfo: Optional[Dict] = None,
    timeout: int = 15
) -> BeautifulSoup:
    """
    스마트칩 페이지 페칭 (여러 시도 전략)
    
    우선순위:
    1. usedata+bib → Expectedrecord_data.asp 직접 접근
    2. rallyinfo → 지도 페이지 직접 접근
    3. base_url → 리다이렉트/링크 추적
    
    Args:
        base_url: 기본 URL
        usedata: 대회 ID
        bib: 참가번호
        rallyinfo: 대회 상세 정보 (yeargbn, rallyno, rallyname)
        timeout: 타임아웃 (초)
    
    Returns:
        BeautifulSoup 객체
    """
    session = get_session()
    parser = SmartchipParser()
    
    # 1) usedata+bib 직접 접근
    if usedata and bib:
        for scheme in ("https://", "http://"):
            target = f"{scheme}smartchip.co.kr/Expectedrecord_data.asp?usedata={usedata}&nameorbibno={bib}"
            try:
                r = session.get(target, timeout=timeout, allow_redirects=True)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                
                if parser._looks_detail_page(soup) and not parser._is_wrapper_home(soup):
                    return soup
            except Exception:
                pass
    
    # 2) rallyinfo 직접 접근
    if rallyinfo and bib:
        soup = _try_rally_info_url(session, rallyinfo, bib, timeout)
        if soup:
            return soup
    
    # 3) base_url 추적
    return _fetch_with_redirect_tracking(session, base_url, usedata, bib, timeout, parser)


def _try_rally_info_url(
    session, 
    rallyinfo: Dict, 
    bib: str, 
    timeout: int
) -> Optional[BeautifulSoup]:
    """rallyinfo로 지도 페이지 접근 시도"""
    yeargbn = rallyinfo.get("yeargbn")
    rallyno = rallyinfo.get("rallyno")
    rallyname = rallyinfo.get("rallyname")
    
    if not all([yeargbn, rallyno, rallyname]):
        return None
    
    for scheme in ("https://", "http://"):
        map_url = (
            f"{scheme}smartchip.co.kr/mapsub/nogpx_map_marathon.html"
            f"?yeargbn={yeargbn}&rallyno={rallyno}"
            f"&rallyname={urllib.parse.quote(rallyname)}&bib={bib}"
        )
        try:
            r = session.get(map_url, timeout=timeout, allow_redirects=True)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except Exception:
            pass
    
    return None


def _fetch_with_redirect_tracking(
    session, 
    base_url: str, 
    usedata: Optional[str], 
    bib: Optional[str], 
    timeout: int,
    parser: SmartchipParser
) -> BeautifulSoup:
    """리다이렉트/링크 추적하며 페이지 가져오기"""
    url = normalize_url(base_url)
    r = session.get(url, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    html = r.text
    base = r.url
    
    # 1) Expectedrecord_data 링크 찾기
    m = re.search(r'(Expectedrecord_data\.asp\?[^"\'>\s]+)', html, re.I)
    if m:
        target = urllib.parse.urljoin(base, unescape(m.group(1)))
        soup = _try_fetch_detail(session, target, timeout, parser)
        if soup:
            return soup
    
    # 2) JS redirect
    m2 = re.search(r'location\.href\s*=\s*["\']([^"\']+)["\']', html, re.I)
    if m2:
        target = urllib.parse.urljoin(base, unescape(m2.group(1)))
        soup = _try_fetch_detail(session, normalize_url(target), timeout, parser)
        if soup:
            return soup
    
    # 3) 메타 리프레시
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.select_one('meta[http-equiv="refresh" i]')
    if meta and meta.get("content"):
        mm = re.search(r'url\s*=\s*([^;]+)', meta["content"], re.I)
        if mm:
            target = urllib.parse.urljoin(base, mm.group(1).strip(' "\''))
            r2 = session.get(normalize_url(target), timeout=timeout, allow_redirects=True)
            r2.raise_for_status()
            return BeautifulSoup(r2.text, "html.parser")
    
    return soup


def _try_fetch_detail(
    session, 
    url: str, 
    timeout: int, 
    parser: SmartchipParser
) -> Optional[BeautifulSoup]:
    """상세 페이지 가져오기 시도"""
    try:
        r = session.get(url, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        
        if parser._looks_detail_page(soup) and not parser._is_wrapper_home(soup):
            return soup
    except Exception:
        pass
    
    return None