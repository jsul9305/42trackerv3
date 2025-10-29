import requests, urllib, os, re, threading
from requests.exceptions import SSLError
# (선택) 경고 숨기고 싶으면:
# from urllib3.exceptions import InsecureRequestWarning
# import urllib3; urllib3.disable_warnings(InsecureRequestWarning)
from urllib.parse import urlsplit
from config.settings import BASE_DIR, CERT_DIR, VERIFY_SSL_DEFAULT, INSECURE_HOSTS
from config.constants import DEFAULT_HEADERS
from utils.network_utils import _SESSION

def safe_filepart(s: str) -> str:
    # 파일명 안전화(한글은 그대로 두고, 위험 문자만 제거)
    return re.sub(r'[\\/:*?"<>|]+', "_", s or "").strip()

def guess_ext_from_headers(url: str, resp: requests.Response) -> str:
    ct = (resp.headers.get("content-type") or "").lower()
    if "image/jpeg" in ct or "image/jpg" in ct: return ".jpg"
    if "image/png" in ct: return ".png"
    if "image/webp" in ct: return ".webp"
    # URL 확장자 힌트
    path_ext = os.path.splitext(urllib.parse.urlsplit(url).path)[1].lower()
    if path_ext in (".jpg",".jpeg",".png",".webp"): return path_ext
    return ".jpg"  # 기본

def verify_for_host(host: str) -> bool:
    """
    호스트별 SSL 검증 여부 결정.
    INSECURE_HOSTS에 있으면 False, 아니면 VERIFY_SSL_DEFAULT.
    """
    try:
        h = (host or "").lower().strip()
        return (h not in INSECURE_HOSTS) and bool(VERIFY_SSL_DEFAULT)
    except Exception:
        return bool(VERIFY_SSL_DEFAULT)

def download_image_to(dest_path: str,
                      url: str,
                      host: str = "",
                      referer: str = "",
                      timeout: int = 20,           # ← timeout 파라미터 추가 (엔진 호출과 일치)
                      min_ok_size: int = 512) -> str | None:
    """
    url에서 이미지를 받아 dest_path로 저장하고, 최종 저장 경로(확장자 보정된)를 반환.
    실패하면 None.
    - dest_path: 확장자 없으면 Content-Type/URL에서 추론해 자동 부착
    - 임시파일(.part.PID.TID)로 쓰고 원자적 rename
    - min_ok_size보다 작으면 실패로 간주
    """
    try:
        sess = _SESSION or requests.Session()
        headers = dict(DEFAULT_HEADERS)
        if referer:
            headers["Referer"] = referer

        dest_dir = os.path.dirname(dest_path)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)

        verify = verify_for_host(host)

        # 1차 시도 (검증 on/off는 verify_for_host에 따름)
        try:
            resp = sess.get(
                url, headers=headers, stream=True, timeout=timeout,
                allow_redirects=True, verify=verify
            )
        except SSLError as e:
            # ✅ SSL 인증 실패 시, 한 번만 verify=False로 재시도
            print(f"[warn] download_image_to: SSL error on {host} -> retry with verify=False | url={url}")
            resp = sess.get(
                url, headers=headers, stream=True, timeout=timeout,
                allow_redirects=True, verify=False
            )

        if resp.status_code != 200:
            print(f"[warn] download_image_to: non-200 status={resp.status_code} url={url}")
            return None

        # 확장자 보정
        root, ext = os.path.splitext(dest_path)
        if not ext:
            ext = guess_ext_from_headers(url, resp) or ".jpg"
            dest_path = root + ext

        # 임시 파일 경로
        pid = os.getpid()
        tid = threading.get_ident()
        tmp_path = dest_path + f".part.{pid}.{tid}"

        # 스트림 저장
        total = 0
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    total += len(chunk)

        if total < min_ok_size:
            print(f"[warn] download_image_to: too small size={total} url={url}")
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            return None

        os.replace(tmp_path, dest_path)
        return dest_path.replace("\\", "/")

    except Exception as e:
        print(f"[err] download_image_to: {type(e).__name__}: {e} | url={url}")
        return None
    
def save_certificate_to_disk(host: str,
                             usedata: str,
                             bib: str,
                             image_url: str,
                             referer: str = "") -> str | None:
    """
    기록증(이미지)을 로컬로 저장하고 경로를 반환.
    - 저장 규칙: CERT_DIR/{usedata}/{usedata}-{bib6}.(jpg/png/webp)
    - 실패 시 None
    """
    try:
        u = (usedata or "").strip()
        b = (str(bib) if bib is not None else "").strip()
        if not u or not b or not image_url:
            print(f"[warn] save_certificate_to_disk: invalid args usedata={u} bib={b} url={image_url}")
            return None

        bib6 = b.zfill(6) if b.isdigit() else b
        dest_dir = os.path.join(CERT_DIR, u)
        base_name = f"{u}-{bib6}"
        dest_path = os.path.join(dest_dir, base_name)  # 확장자는 download_image_to에서 자동 부착

        saved = download_image_to(
            dest_path=dest_path,
            url=image_url,
            host=host,
            referer=referer,
            timeout=20  # ← 엔진/워커 기대와 동일
        )
        if saved:
            return saved

        print(f"[warn] save_certificate_to_disk: download failed url={image_url}")
        return None

    except Exception as e:
        print(f"[err] save_certificate_to_disk: {type(e).__name__}: {e} | url={image_url}")
        return None

def to_web_static_url(local_path: str | None) -> str | None:
    """윈도 경로(C:\\...)나 절대 경로를 /static/... 웹 경로로 바꿔준다."""
    if not local_path:
        return None
    p = str(local_path).replace("\\", "/")
    # 경로 안에 /static/가 포함돼 있으면 그 뒤를 그대로 씀
    idx = p.lower().rfind("/static/")
    if idx != -1:
        return p[idx:]  # '/static/...' 형태

    # 프로젝트 static 디렉토리 하위에 있으면 그 상대경로로 변환
    static_root = os.path.join(BASE_DIR, "static").replace("\\", "/")
    if p.startswith(static_root):
        rel = p[len(static_root):]
        if not rel.startswith("/"):
            rel = "/" + rel
        return "/static" + rel

    # 못 찾겠으면 None
    return None
