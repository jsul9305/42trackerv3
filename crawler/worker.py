import threading, time, json, os
from queue import Queue, Empty
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# 전역 변수 수정
_MR_WORKER = None
_MR_WORKER_LOCK = threading.Lock()

class _MyResultWorker:
    def __init__(self, chrome_path: str | None = None):
        self.chrome_path = chrome_path
        self.in_q: Queue = Queue()
        self.thread = threading.Thread(target=self._run, daemon=True, name="MyResultWorker")
        self.thread.start()

    def fetch(self, url: str, timeout: int = 12) -> str:
        out_q: Queue = Queue()
        self.in_q.put(("FETCH", url, timeout, out_q))
        try:
            return out_q.get(timeout=timeout + 8)
        except Empty:
            return ""  # 타임아웃 → 상위에서 폴백/로그

    def stop(self):
        q = Queue(); self.in_q.put(("STOP", "", 0, q))
        try: q.get(timeout=2)
        except Empty: pass

    def _run(self):
        pw = browser = ctx = page = None
        try:
            pw = sync_playwright().start()
            launch_kwargs = dict(
                headless=True,
                args=["--no-sandbox","--disable-setuid-sandbox","--ignore-certificate-errors"]
            )
            if self.chrome_path:
                launch_kwargs["executable_path"] = self.chrome_path
            browser = pw.chromium.launch(**launch_kwargs)
            ctx = browser.new_context(
                ignore_https_errors=True,
                java_script_enabled=True,
                viewport={"width": 1200, "height": 800},
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
            )
            page = ctx.new_page()

            # 리소스 차단(속도)
            block_types = {"image","media","font","stylesheet"}
            block_hosts = ("google-analytics.com","googletagmanager.com","g.doubleclick.net",
                           "facebook.com","kakao","naver","daum","hotjar","mixpanel")
            def _route(route, req):
                if req.resource_type in block_types: return route.abort()
                if any(h in req.url for h in block_hosts): return route.abort()
                return route.continue_()
            page.route("**/*", _route)

            while True:
                op, url, timeout, out_q = self.in_q.get()
                if op == "STOP":
                    out_q.put("OK"); break

                try:
                    page.set_default_timeout(max(10000, timeout * 1000))
                    page.goto(url, wait_until="domcontentloaded", timeout=max(12000, timeout*1000))

                    # 1) 네트워크 안정화까지 대기
                    try:
                        page.wait_for_load_state("networkidle", timeout=max(6000, int(timeout*700)))
                    except Exception:
                        pass

                    # 2) 테이블 DOM이 붙을 때까지 적극 대기 (최대 ~8s)
                    dom_ok = False
                    for _ in range(8):
                        try:
                            page.wait_for_selector(".table-row.ant-row .ant-col", state="attached", timeout=1000)
                            dom_ok = True
                            break
                        except Exception:
                            pass

                    if dom_ok:
                        out_q.put(page.content())
                        continue

                    # 3) 그래도 DOM이 없으면 JSON XHR 잡기 시도 (5~7s)
                    data = None
                    deadline = time.time() + 7
                    while time.time() < deadline:
                        try:
                            resp = page.wait_for_event(
                                "response",
                                predicate=lambda r: (
                                    r.request.resource_type in ("xhr","fetch")
                                    and ("json" in (r.headers.get("content-type","").lower())
                                        or r.url.endswith(".json")
                                        or "/api/" in r.url)
                                ),
                                timeout=800,
                            )
                            try:
                                j = resp.json()
                            except Exception:
                                continue
                            data = j
                            break
                        except Exception:
                            pass

                    if data is not None:
                        out_q.put("JSON::" + json.dumps(data, ensure_ascii=False))
                        continue

                    # 4) 최후: 현재 DOM 그대로 반환 (스켈레톤일 수도 있음)
                    out_q.put(page.content())

                except Exception:
                    out_q.put("")  # 이 건만 실패

        finally:
            try: page and page.context.close()
            except: pass
            try: browser and browser.close()
            except: pass
            try: pw and pw.stop()
            except: pass

class _MyResultWorkerPool:
    """MyResult 전용 워커 풀"""
    def __init__(self, pool_size=3):
        self.workers = [_MyResultWorker() for _ in range(pool_size)]
        self.idx = 0
    
    def fetch(self, url: str, timeout: int = 12) -> str:
        worker = self.workers[self.idx]
        self.idx = (self.idx + 1) % len(self.workers)
        return worker.fetch(url, timeout)

def get_mr_worker():
    """MyResult 워커 인스턴스를 반환 (싱글톤)"""
    global _MR_WORKER
    with _MR_WORKER_LOCK:
        if _MR_WORKER is None:
            _MR_WORKER = _MyResultWorker()
    return _MR_WORKER

def get_mr_worker() -> _MyResultWorker:
    global _MR_WORKER
    with _MR_WORKER_LOCK:
        if _MR_WORKER is None or not _MR_WORKER.thread.is_alive():
            _MR_WORKER = _MyResultWorker(os.getenv("CHROME_PATH") or None)
    return _MR_WORKER
