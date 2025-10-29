# crawler/engine.py
"""크롤링 엔진 - 메인 루프 및 작업 조정"""

import time, os, traceback, json, threading
import random
import urllib.parse
from queue import Queue
from datetime import datetime
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple, Any, Optional

from bs4 import BeautifulSoup

from core.database import get_db, init_database, migrate_database
from config.settings import BASE_DIR, CERT_DIR
from crawler.fetcher import fetch_cached
from crawler.worker import get_mr_worker
from parsers.utils import parse
from parsers.myresult import MyResultParser, extract_total_net_time # noqa
from utils.time_utils import first_time, looks_time
from utils.file_utils import save_certificate_to_disk
from utils.network_utils import get_session
from utils.distance_utils import ensure_finish_label
from config.settings import CRAWLER_MAX_WORKERS
from webapp.services.records import RecordsService # ✅ 완주 시간 계산기 import


class CrawlerEngine:
    """
    크롤링 엔진
    
    주요 기능:
    - 활성화된 대회별로 주기적 크롤링
    - 참가자 스플릿 데이터 수집
    - 기록증 이미지 다운로드
    - 배치 업데이트로 DB 부하 최소화
    """
    
    def __init__(self, use_adaptive_scheduler: bool = False):
        """
        Args:
            use_adaptive_scheduler: True면 적응형 스케줄러 사용 (실패 시 백오프)
        """
        # 스케줄러 (실행 주기 관리)
        from crawler.scheduler import CrawlerScheduler, AdaptiveScheduler
        
        if use_adaptive_scheduler:
            self.scheduler = AdaptiveScheduler()
            print("[Engine] Using AdaptiveScheduler (with backoff)")
        else:
            self.scheduler = CrawlerScheduler()
            print("[Engine] Using CrawlerScheduler (basic)")
        
        # 이미지 다운로드 큐
        self.image_queue: Queue = Queue()
        self.image_workers: List[threading.Thread] = []
        
        # 실행 상태
        self.running = False

    def _dbg_preview_list(self, lst, n: int = 3) -> str:
        try:
            if not isinstance(lst, list):
                return f"type={type(lst).__name__}"
            out = []
            for i, x in enumerate(lst[:n]):
                xtype = type(x).__name__
                xrepr = repr(x)
                if len(xrepr) > 200:
                    xrepr = xrepr[:200] + "...(trunc)"
                out.append(f"[{i}] {xtype}: {xrepr}")
            if len(lst) > n:
                out.append(f"... (+{len(lst)-n} more)")
            return " | ".join(out)
        except Exception as e:
            return f"<preview_error:{e}>"
    
    # ============= 메인 루프 =============
    
    def run(self):
        """크롤러 메인 루프 시작"""
        print("[Engine] Initializing...")
        init_database()
        migrate_database()

        # 세션 워밍업 (선택)
        try:
            s = get_session()
            print(f"[Engine] HTTP session ready: {type(s).__name__}")
        except Exception as e:
            print(f"[fatal] HTTP session init failed: {e}")
            raise
        
        print("[Engine] Starting image workers...")
        self._start_image_workers(num_workers=3)
        
        print(f"[Engine] Starting main loop (workers={CRAWLER_MAX_WORKERS})...")
        self.running = True
        
        try:
            self._main_loop()
        except KeyboardInterrupt:
            print("\n[Engine] Shutting down...")
            self.shutdown()
    
    def shutdown(self):
        """크롤러 종료"""
        self.running = False
        
        # 이미지 워커 종료
        for _ in self.image_workers:
            self.image_queue.put(None)
        
        for worker in self.image_workers:
            worker.join(timeout=5)
        
        print("[Engine] Shutdown complete")
    
    def _main_loop(self):
        """메인 크롤링 루프"""
        while self.running:
            tick = time.time()
            
            try:
                # 활성화된 대회 조회
                with get_db() as conn:
                    marathons = conn.execute(
                        "SELECT * FROM marathons WHERE enabled=1"
                    ).fetchall()
                
                # 각 대회 처리
                for marathon in marathons:
                    self._process_marathon(marathon)
                
            except Exception as e:
                print(f"[fatal] {type(e).__name__}: {e}")
            
            # 짧은 대기 (CPU 부하 감소)
            time.sleep(0.1)
    
    # ============= 대회별 처리 =============
    
    def _process_marathon(self, marathon):
        """특정 대회 크롤링 처리"""
        mid = marathon["id"]
        refresh_sec = int(marathon["refresh_sec"] or 60)
        event_date_str = marathon["event_date"] if "event_date" in marathon.keys() else None

        # ✅ 대회 날짜 확인
        if event_date_str:
            try:
                event_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
                today = datetime.now().date()
                if today < event_date:
                    return # 아직 대회 날짜가 아님
            except ValueError:
                print(f"[warn] mid={mid} has invalid event_date format: {event_date_str}. Ignoring date check.")
        
        # ✅ 스케줄러로 실행 가능 여부 확인
        if not self.scheduler.should_run_marathon(mid, refresh_sec):
            return
        
        tick = time.time()
        
        try:
            # 참가자 조회
            with get_db() as conn:
                participants = conn.execute(
                    "SELECT * FROM participants WHERE marathon_id=? AND active=1",
                    (mid,)
                ).fetchall()
            
            if not participants:
                # ✅ 참가자 없어도 실행 기록 (다음 주기까지 대기)
                self.scheduler.mark_marathon_run(mid)
                return
            
            # 크롤링 실행
            results = self._crawl_participants(marathon, participants)
            
            # DB 업데이트
            self._save_results(results, marathon, participants)
            
            duration = round(time.time() - tick, 2)
            print(f"[ok] mid={mid} participants={len(participants)} dur={duration}s")
            
            # ✅ 성공 기록 (AdaptiveScheduler면 백오프 리셋)
            if hasattr(self.scheduler, 'record_success'):
                self.scheduler.record_success(mid)
            else:
                self.scheduler.mark_marathon_run(mid)
        
        except Exception as e:
            print(f"[err] mid={mid} -> {type(e).__name__}: {e}")
            
            # ✅ 실패 기록 (AdaptiveScheduler면 백오프 증가)
            if hasattr(self.scheduler, 'record_failure'):
                self.scheduler.record_failure(mid)
                backoff = self.scheduler.get_backoff_time(mid, refresh_sec)
                print(f"[backoff] mid={mid} next try in {backoff:.0f}s")
            else:
                self.scheduler.mark_marathon_run(mid)
    
    # ============= 참가자 크롤링 =============
    
    def _crawl_participants(
        self,
        marathon,
        participants: List
    ) -> List[Tuple]:
        """
        참가자들의 데이터 크롤링
        
        Returns:
            [(participant_id, splits, meta, assets), ...]
        """
        url_template = marathon["url_template"]
        usedata = marathon["usedata"] or ""
        
        results = []
        futures = []
        myresult_jobs = []
        future_ctx = {}  # ✅ future → (pid, url, bib)
        
        # 작업 분배
        with ThreadPoolExecutor(max_workers=CRAWLER_MAX_WORKERS) as executor:
            for p in participants:
                pid = p["id"]
                
                # ✅ 스케줄러로 페치 가능 여부 확인 (rate limiting)
                if not self.scheduler.can_fetch_participant(pid):
                    continue
                
                # ✅ 페치 시작 기록
                self.scheduler.mark_participant_fetch(pid)
                
                # URL 생성
                url = self._build_url(url_template, p["nameorbibno"], usedata)
                host = (urllib.parse.urlsplit(url).hostname or "").lower()
                
                # MyResult는 직렬 처리 (워커 안정성)
                if "myresult.co.kr" in host:
                    myresult_jobs.append((pid, url, p["nameorbibno"], usedata))
                else:
                    # 나머지는 병렬 처리
                    future = executor.submit(
                        self._crawl_one,
                        pid, url, p["nameorbibno"], usedata
                    )
                    futures.append(future)
                    future_ctx[future] = (pid, url, p["nameorbibno"])  # ✅ 컨텍스트 저장

            
            # 병렬 작업 결과 수집
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result and isinstance(result, tuple):
                        results.append(result)
                    else:
                        ctx = future_ctx.get(future, (None, None, None))
                        print(f"[warn] future returned unexpected: type={type(result).__name__} ctx={ctx}")
                except Exception as e:
                    ctx = future_ctx.get(future, (None, None, None))
                    traceback.print_exc()
                    print(f"[err] thread -> {type(e).__name__}: {e} | ctx(pid,url,bib)={ctx}")
        
        # MyResult 직렬 처리
        for pid, url, bib, usedata in myresult_jobs:
            try:
                result = self._crawl_one(pid, url, bib, usedata)
                if result and isinstance(result, tuple):
                    results.append(result)
            except Exception as e:
                print(f"[err] myresult -> {type(e).__name__}: {e}")
        
        return results
    
    def _crawl_one(
        self,
        pid: int,
        url: str,
        bib: Optional[str] = None,
        usedata: Optional[str] = None
    ) -> Tuple[int, List, Dict, List]:
        """
        단일 참가자 크롤링
        
        Returns:
            (participant_id, splits, meta, assets)
        """
        print(f"[crawl_one] pid={pid} bib={bib}")
        # HTML 페칭 (캐시 사용)
        html = None
        try:
            html = fetch_cached(url)
        except Exception as e:
            traceback.print_exc()
            print(f"[err] fetch_cached failed pid={pid} url={url}: {e}")
            html = ""
        host = urllib.parse.urlsplit(url).hostname or ""
        # print(f"[dbg] fetched host={host} len={len(html) if isinstance(html, (str, bytes)) else 'n/a'} pid={pid}")
        
        # 파싱
        try:
            data = parse(html, host=host, url=url, usedata=usedata, bib=bib) or {}
        except Exception as e:
            traceback.print_exc()
            print(f"[err] parse failed pid={pid} url={url}: {e}")
            data = {}

        if not isinstance(data, dict):
            print(f"[warn] parse returned {type(data).__name__} → forcing dict | pid={pid} url={url}")
            data = {}
        
        # MyResult JSON 특별 처리fsdfsdfsdfjl
        try:
            if isinstance(html, str) and html.startswith("JSON::"):
                data2 = self._handle_myresult_json(html, url, host, data) or data
                if not isinstance(data2, dict):
                    print(f"[warn] _handle_myresult_json returned {type(data2).__name__} → keep original dict | pid={pid}")
                else:
                    data = data2
        except Exception as e:
            traceback.print_exc()
            print(f"[err] _handle_myresult_json error pid={pid} url={url}: {e}")
        
        # ✅ 강제 정규화 + 프리뷰
        raw_splits = data.get("splits") or []
        raw_assets = data.get("assets") or []
        if not isinstance(raw_splits, list):
            print(f"[warn] splits is {type(raw_splits).__name__} (expected list) | pid={pid}")
            raw_splits = []
        if not isinstance(raw_assets, list):
            print(f"[warn] assets is {type(raw_assets).__name__} (expected list) | pid={pid}")
            raw_assets = []

        # print(f"[dbg] raw splits len={len(raw_splits)} preview={self._dbg_preview_list(raw_splits)} | pid={pid}")
        # print(f"[dbg] raw assets len={len(raw_assets)} preview={self._dbg_preview_list(raw_assets)} | pid={pid}")

        splits = [r for r in raw_splits if isinstance(r, dict)]
        assets = [a for a in raw_assets if isinstance(a, dict)]
        if len(splits) != len(raw_splits):
            print(f"[warn] filtered non-dict splits: {len(raw_splits) - len(splits)} removed | pid={pid}")
        if len(assets) != len(raw_assets):
            print(f"[warn] filtered non-dict assets: {len(raw_assets) - len(assets)} removed | pid={pid}")

        meta = {
            "race_label": data.get("race_label"),
            "race_total_km": data.get("race_total_km"),
            "group": data.get("race_label") # 호환성을 위해 group도 추가
        }
        # ✅ 여기서 Finish 라벨 보강
        splits = ensure_finish_label(splits, meta.get("race_total_km"))

        if not assets:
            inferred = []
            h = (host or "").lower()
            b = str(bib or "").strip()
            u = str(usedata or "").strip()
                
            bib6 = b.zfill(6) if b.isdigit() else b
            dest_dir = os.path.join(CERT_DIR, u)
            base_name = f"{u}-{bib6}"
            dest_path = os.path.join(dest_dir, base_name, ".jpg")

            # 1) MyResult: https://myresult.co.kr/upload/certificate/{usedata}/{bib}
            if "myresult.co.kr" in h and u and b:
                inferred.append({
                    "kind": "certificate",
                    "host": "myresult.co.kr",
                    "url": f"https://myresult.co.kr/upload/certificate/{u}/{b}"
                })

            # 2) SmartChip(기록증 뷰어 PHP): https://image.smartchip.co.kr/record_data/TriRun_Record.php?Rally_id={usedata}&Bally_no={bib}
            #    (참고: 참조 페이지는 smartchip.co.kr/return_data_livephoto.asp?... 를 referer로 사용)
            if "smartchip.co.kr" in h and u and b:
                inferred.append({
                    "kind": "certificate",
                    "host": "image.smartchip.co.kr",
                    "url": f"https://image.smartchip.co.kr/record_data/TriRun_Record.php?Rally_id={u}&Bally_no={b}"
                })

            # 3) SPCT(정적 이미지 직링크): https://img.spct.kr/PhotoResultsJPG/images/{usedata}/{usedata}-{bib6}.jpg
            #    referer는 ResultsPhotoResults.php?EVENT_NO={usedata}&BIB_NO={bib_spct6} 를 사용해야 핫링크 방지 통과 확률↑
            if ("spct.kr" in h or "img.spct.kr" in h) and u and b:
                bib6 = b.zfill(6) if b.isdigit() else b
                inferred.append({
                    "kind": "certificate",
                    "host": "img.spct.kr",
                    "url": f"https://img.spct.kr/PhotoResultsJPG/images/{u}/{u}-{bib6}.jpg"
                })

            if inferred:
                # 파서 결과 대신 폴백 사용
                assets = inferred
                # print(f"[dbg] inferred assets pid={pid} count={len(assets)} host={host} url={url}")
            else:
                print(f"[dbg] no assets pid={pid} url={url}")

        if not assets: print(f"[dbg] no assets pid={pid} url={url}")
        # print(f"[dbg] normalized splits={len(splits)} assets={len(assets)} meta={meta} | pid={pid}")
        
        return (pid, splits, meta, assets)
    
    def _handle_myresult_json(
        self,
        html: str,
        url: str,
        host: str,
        data: Dict
    ) -> Dict:
        """
        MyResult JSON 특별 처리
        
        JSON에 Finish가 없으면 HTML에서 추출하여 보강
        """
        if "myresult.co.kr" not in host.lower():
            return data

        splits = data.get("splits") or []
        if not isinstance(splits, list):
            print(f"[warn] MR splits not list ({type(splits).__name__}) url={url}")
            return data

        safe_splits = [r for r in splits if isinstance(r, dict)]
        if len(safe_splits) != len(splits):
            print(f"[warn] MR filtered non-dict splits: {len(splits) - len(safe_splits)} removed | url={url}")

        # print(f"[dbg] MR precheck splits len={len(safe_splits)} preview={self._dbg_preview_list(safe_splits)} | url={url}")

        has_finish = any(
            ((r.get("point_label") or "").lower() == "finish")
            for r in safe_splits
        )
        if has_finish:
            return data

        try:
            html2 = get_mr_worker().fetch(url, timeout=10) or ""
            if not html2 or html2.startswith("JSON::"):
                return data

            soup = BeautifulSoup(html2, "html.parser")
            total = extract_total_net_time(soup)

            finish_clock = ""
            for row in soup.select(".table-row.ant-row"):
                cols = row.select(".ant-col")
                if len(cols) >= 4 and "도착" in cols[0].get_text(" ", strip=True):
                    finish_clock = first_time(cols[1].get_text(" ", strip=True))
                    break

            if looks_time(total):
                data.setdefault("splits", []).append({
                    "point_label": "Finish",
                    "point_km": None,
                    "net_time": total,
                    "pass_clock": finish_clock,
                    "pace": "",
                })
                print(f"[dbg] MR appended Finish total={total} clock={finish_clock} | url={url}")

        except Exception as e:
            traceback.print_exc()
            print(f"[err] MR finish backfill failed url={url}: {e}")

        return data
    
    # ============= URL 생성 =============
    
    def _build_url(
        self,
        template: str,
        nameorbibno: str,
        usedata: str
    ) -> str:
        """
        URL 템플릿에서 실제 URL 생성
        
        지원 플레이스홀더:
        - {nameorbibno}: 참가번호/이름
        - {usedata}: 대회 ID
        - {bib_spct6}: SPCT 6자리 제로패딩
        """
        url = template.replace("{nameorbibno}", nameorbibno)
        url = url.replace("{usedata}", usedata or "")
        
        # SPCT 6자리 제로패딩 지원
        if "{bib_spct6}" in url:
            bib6 = nameorbibno.zfill(6) if nameorbibno.isdigit() else nameorbibno
            url = url.replace("{bib_spct6}", bib6)
        
        return url
    
    # ============= DB 저장 =============
    
    def _save_results(self, results: List[Tuple], marathon, participants: List):
        """
        크롤링 결과를 DB에 배치 저장
        
        배치 업데이트로 성능 최적화
        """
        if not results:
            print("[dbg] save_results: empty results")
            return

        # print(f"[dbg] save_results: results_count={len(results)} mid={marathon['id']}")

        # ✅ 여기에 추가: sqlite3.Row 안전 추출
        m_usedata = (marathon["usedata"] or "") if "usedata" in marathon.keys() else ""
        m_urltpl  = marathon["url_template"] if "url_template" in marathon.keys() else ""
        # ✅ pid → bib 매핑 생성
        pid_to_bib = {p["id"]: p["nameorbibno"] for p in participants}
        now_iso = datetime.now().isoformat()
        split_batch, meta_batch, asset_batch = [], [], []
        num_assets_enq = 0  # ← 바깥에서 누적

        for idx, r in enumerate(results):
            if not r:
                print(f"[warn] result[{idx}] is falsy: {r}")
                continue
            if not isinstance(r, tuple):
                print(f"[warn] result[{idx}] not tuple: type={type(r).__name__} repr={repr(r)[:200]}")
                continue

            pid, splits, meta, assets = None, None, None, None
            if len(r) == 4:
                pid, splits, meta, assets = r
            elif len(r) == 3:
                pid, splits, meta = r
                assets = []
            else:
                pid, splits = r[0], r[1] if len(r) > 1 else []
                meta, assets = {}, []

            # 메타
            # ✅ 완주 여부 확인
            is_finished = False
            if splits:
                for s in splits:
                    if isinstance(s, dict):
                        point_label = (s.get("point_label") or "").lower()
                        if "finish" in point_label or "도착" in point_label:
                            is_finished = True
                            break
            if isinstance(meta, dict) and meta:
                meta_batch.append((
                    meta.get("race_label"),
                    meta.get("race_total_km"),
                    pid
                ))

            # 스플릿
            for s in (splits or []):
                if not isinstance(s, dict):
                    print(f"[warn] split item not dict pid={pid} item={repr(s)[:120]}")
                    continue
                split_batch.append((
                    pid,
                    s.get("point_label"),
                    s.get("point_km"),
                    s.get("net_time"),
                    s.get("pass_clock"),
                    s.get("pace"),
                    now_iso
                ))

            # ✅ 에셋 — 반드시 각 r 내부에서 처리!
            for a in (assets or []):
                if not isinstance(a, dict):
                    print(f"[warn] asset item not dict pid={pid} item={repr(a)[:120]}")
                    continue
                url = a.get("url")
                if not url:
                    continue

                asset_batch.append((
                    pid,
                    a.get("kind") or "certificate",
                    a.get("host"),
                    url,
                    None,
                    now_iso
                ))

                # 이미지 다운로드 큐
                bib = pid_to_bib.get(pid)
                if bib and is_finished: # ✅ 완주한 경우에만 이미지 다운로드 큐에 추가
                    referer_url = self._build_url(
                        m_urltpl,
                        bib,
                        m_usedata
                    )
                    self.image_queue.put((
                        a.get("host"),
                        m_usedata,
                        bib, url,
                        referer_url, pid
                    ))
                    num_assets_enq += 1

        # ✅ 완주 시간 재계산 및 split_batch에 반영
        # pass_clock 기반 계산이 필요한 참가자 ID 목록 생성
        pids_to_recalc = {
            s[0] for s in split_batch 
            if "finish" in (s[1] or "").lower() and (s[4] or "").strip() and not looks_time(s[3])
        }


        print(f"[dbg] batches -> splits={len(split_batch)} meta={len(meta_batch)} assets={len(asset_batch)} enqueued={num_assets_enq}")

        try:
            with get_db() as conn:
                if meta_batch:
                    conn.executemany(
                        """UPDATE participants
                        SET race_label = COALESCE(?, race_label),
                            race_total_km = COALESCE(?, race_total_km)
                        WHERE id = ?""",
                        meta_batch
                    )
                
                # ✅ 완주 시간 계산 및 업데이트 준비
                if pids_to_recalc:
                    for pid in pids_to_recalc:
                        calculated_net = RecordsService._calculate_net_time_from_clocks(conn, pid)
                        if calculated_net:
                            # split_batch에서 해당 참가자의 Finish 기록을 찾아 net_time 업데이트
                            for i, s in enumerate(split_batch):
                                if s[0] == pid and "finish" in (s[1] or "").lower():
                                    # 튜플은 수정 불가하므로 리스트로 변환 후 수정, 다시 튜플로
                                    s_list = list(s)
                                    s_list[3] = calculated_net # net_time 필드
                                    split_batch[i] = tuple(s_list)
                                    print(f"[dbg] Recalculated net_time for pid={pid}: {calculated_net}")

                if split_batch:
                    conn.executemany(
                        """INSERT INTO splits(participant_id, point_label, point_km, 
                                            net_time, pass_clock, pace, seen_at)
                        VALUES(?,?,?,?,?,?,?)
                        ON CONFLICT(participant_id, point_label)
                        DO UPDATE SET net_time=excluded.net_time,
                                        pass_clock=excluded.pass_clock,
                                        pace=excluded.pace,
                                        seen_at=excluded.seen_at""",
                        split_batch
                    )

                if asset_batch:
                    conn.executemany(
                        """INSERT INTO assets(participant_id, kind, host, url, 
                                            local_path, seen_at)
                        VALUES(?,?,?,?,?,?)
                        ON CONFLICT(participant_id, kind)
                        DO UPDATE SET url=excluded.url,
                                        host=excluded.host,
                                        seen_at=excluded.seen_at""",
                        asset_batch
                    )
                conn.commit()
        except Exception as e:
            traceback.print_exc()
            print(f"[fatal] DB batch failed mid={marathon['id']}: {e}")
    
    # ============= 이미지 다운로드 워커 =============
    
    def _start_image_workers(self, num_workers: int = 3):
        """이미지 다운로드 워커 시작"""
        for i in range(num_workers):
            worker = threading.Thread(
                target=self._image_worker,
                daemon=True,
                name=f"ImageWorker-{i+1}"
            )
            worker.start()
            self.image_workers.append(worker)
    
    def _image_worker(self):
        """이미지 다운로드 워커 (백그라운드)"""
        while True:
            task = self.image_queue.get()
            if task is None:
                break
            
            # task unpacking 실패 시 로깅을 위해 변수 초기화
            pid, img_url = None, None
            try:
                host, usedata, bib, img_url, referer, pid = task # ✅ task unpacking
                
                # 1. DB에서 기존 이미지 경로 확인
                with get_db() as conn:
                    p_row = conn.execute(
                        "SELECT finish_image_path FROM participants WHERE id=?",
                        (pid,)
                    ).fetchone()
                
                # 2. DB에 경로가 있고, 실제 파일도 존재하면 건너뛰기
                if p_row and p_row['finish_image_path'] and os.path.exists(p_row['finish_image_path']):
                    # print(f"[img_worker] SKIP pid={pid} | already exists: {p_row['finish_image_path']}")
                    continue
                
                # 3. 이미지 다운로드 시도
                saved_path = save_certificate_to_disk(host, usedata, bib, img_url, referer)
                
                if saved_path:
                    # 4. 성공 시 DB에 경로 업데이트
                    print(f"[img_worker] OK pid={pid} path={saved_path}")
                    with get_db() as conn:
                        conn.execute(
                            "UPDATE participants SET finish_image_url=?, finish_image_path=? WHERE id=?",
                            (img_url, saved_path, pid)
                        )
                        conn.commit()
                else:
                    print(f"[img_worker] FAIL pid={pid} | save_certificate_to_disk returned None")
            except Exception as e:
                traceback.print_exc()
                print(f"[err] image save: {type(e).__name__}: {e} | pid={pid} url={img_url}")
            finally:
                self.image_queue.task_done()


# ============= 실행 함수 =============

def main_loop():
    """
    레거시 함수 (호환성 유지)
    
    Deprecated: CrawlerEngine().run() 사용 권장
    """
    engine = CrawlerEngine()
    engine.run()


# ============= 사용 예시 =============

if __name__ == "__main__":
    print("=" * 50)
    print("SmartChip Crawler Engine")
    print("=" * 50)
    
    # 옵션 1: 기본 스케줄러 (고정 주기)
    print("\n[Option 1] Basic Scheduler")
    print("- Fixed refresh intervals")
    print("- No backoff on failures")
    engine = CrawlerEngine(use_adaptive_scheduler=False)
    
    # 옵션 2: 적응형 스케줄러 (실패 시 백오프)
    # print("\n[Option 2] Adaptive Scheduler")
    # print("- Exponential backoff on failures")
    # print("- Auto-recovery on success")
    # engine = CrawlerEngine(use_adaptive_scheduler=True)
    
    try:
        engine.run()
    except KeyboardInterrupt:
        print("\n[Shutdown] Stopping crawler...")
        engine.shutdown()
        print("Crawler stopped")
