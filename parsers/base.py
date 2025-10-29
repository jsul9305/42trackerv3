from abc import ABC, abstractmethod
from typing import Dict, List, Any
from bs4 import BeautifulSoup

class BaseParser(ABC):
    """파서 베이스 클래스"""
    
    @abstractmethod
    def can_parse(self, host: str) -> bool:
        """이 파서가 해당 호스트를 처리할 수 있는지"""
        pass
    
    @abstractmethod
    def parse(self, html: str, **context) -> Dict[str, Any]:
        """
        HTML을 파싱하여 표준 포맷으로 반환
        
        Returns:
            {
                'splits': List[Dict],  # 스플릿 데이터
                'summary': Dict,       # 요약 정보
                'assets': List[Dict],  # 기록증 등
                'race_label': str,     # 종목명
                'race_total_km': float # 총 거리
            }
        """
        pass
    
    def _make_soup(self, html: str) -> BeautifulSoup:
        """BeautifulSoup 객체 생성"""
        return BeautifulSoup(html, "html.parser")

