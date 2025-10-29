import urllib, time, re
import traceback
from typing import Optional

from bs4 import BeautifulSoup
from utils.network_utils import (
    add_cache_buster,
    normalize_url,
    get_session,          # ✅ 세션은 함수로 얻는다
    verify_for_host,      # ✅ 호스트별 SSL 검증 결정
)
from crawler.worker import get_mr_worker

_CACHE = {}
_CACHE_TTL = 30

def _dbg(msg: str):
    print(f"[fetcher] {msg}")

def fetch(url: str, timeout: int = 10, verify: Optional[bool] = None) -> str:
    """
    단일 URL을 가져온다.
    - myresult/spct는 먼저 브라우저 워커 시도
    - 실패 시 requests 세션으로 폴백
    - verify가 명시되지 않으면 호스트별 verify_for_host()로 자동 결정
    """
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        url2 = add_cache_buster(url)

        if verify is None:
            verify = verify_for_host(host)

        # 1) myresult/spct/smartchip은 워커 우선
        if any(h in host for h in ["myresult.co.kr", "spct.co.kr", "smartchip.co.kr"]):
            try:
                html = get_mr_worker().fetch(url2, timeout=timeout)
                if html:
                    _dbg(f"worker_fetch success host={host} len={len(html) if isinstance(html, (str, bytes)) else 'n/a'}")
                    return html
                _dbg("worker_fetch returned empty -> fallback to requests")
            except Exception as e:
                traceback.print_exc()
                _dbg(f"worker_fetch error host={host}: {e} -> fallback to requests")

        # 2) requests 세션으로 폴백
        s = get_session()                      # ✅ 여기서 항상 초기화 보장
        r = s.get(url2, timeout=timeout, verify=verify)
        r.raise_for_status()
        # 인코딩 추정 (EUC-KR 등)
        r.encoding = r.apparent_encoding or r.encoding
        # _dbg(f"requests_get success host={host} status={r.status_code} enc={r.encoding}")
        return r.text

    except Exception as e:
        traceback.print_exc()
        _dbg(f"fetch failed url={url}: {e}")
        # 실패는 상위에서 핸들할 수 있게 예외 그대로 던진다
        raise

def fetch_cached(url: str, timeout: int = 10, verify: Optional[bool] = None) -> str:
    """캐싱이 적용된 fetch"""
    now = time.time()
    key = (url, timeout, verify)
    hit = _CACHE.get(key)
    if hit:
        data, ts = hit
        if now - ts < _CACHE_TTL:
            _dbg(f"cache_hit url={url}")
            return data

    html = fetch(url, timeout=timeout, verify=verify)
    _CACHE[key] = (html, now)
    return html

def fetch_html_follow_js_redirect(url: str, timeout: int = 15, verify: Optional[bool] = None) -> BeautifulSoup:
    """
    HTML 로드 후 JS location.href / meta refresh 리다이렉트까지 따라가서 최종 HTML을 반환
    - 세션 전역 헤더를 오염시키지 않도록 요청별 headers 파라미터 사용
    """
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if verify is None:
        verify = verify_for_host(host)

    s = get_session()

    # 1차 요청
    resp = s.get(url, timeout=timeout, allow_redirects=True, verify=verify)
    resp.raise_for_status()
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    # 1) <script> location.href="..."; 형태 감지
    m = re.search(r'location\.href\s*=\s*"([^"]+)"', html, re.I)
    if m:
        target = normalize_url(m.group(1))
        base = normalize_url(resp.url)
        target_abs = urllib.parse.urljoin(base, target)

        # 세션 전역 headers 오염 방지: 요청별 헤더로 Referer 전달
        headers = dict(s.headers)
        headers["Referer"] = base

        resp2 = s.get(target_abs, timeout=timeout, allow_redirects=True, verify=verify, headers=headers)
        resp2.raise_for_status()
        return BeautifulSoup(resp2.text, "html.parser")

    # 2) <meta http-equiv="refresh" content="0; url=..."> 대비
    meta = soup.select_one('meta[http-equiv="refresh" i]')
    if meta and meta.get("content"):
        m2 = re.search(r'url\s*=\s*([^;]+)', meta["content"], re.I)
        if m2:
            target = normalize_url(m2.group(1).strip(' "\''))
            base = normalize_url(resp.url)
            target_abs = urllib.parse.urljoin(base, target)

            headers = dict(s.headers)
            headers["Referer"] = base

            resp2 = s.get(target_abs, timeout=timeout, allow_redirects=True, verify=verify, headers=headers)
            resp2.raise_for_status()
            return BeautifulSoup(resp2.text, "html.parser")

    return soup
