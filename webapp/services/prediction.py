# webapp/services/prediction.py
"""예측/분석 비즈니스 로직"""

from typing import List, Dict, Optional

from config.constants import FINISH_KEYWORDS_KO, FINISH_KEYWORDS_EN, DISTANCE_TOLERANCE
from utils.time_utils import looks_time, sec_from_mmss, eta_from_clock, sec_per_km
from utils.distance_utils import km_from_label, snap_distance, ensure_finish_label
import re

# --- 로컬 정규화 유틸 ---
_ZWSP_RE = re.compile(r"[\u200b\u200c\u200d\uFEFF]")
_WS_RE   = re.compile(r"\s+")
def _clean(s: Optional[str]) -> str:
    if not isinstance(s, str):
        return ""
    s = _ZWSP_RE.sub("", s).replace("\xa0"," ").strip()
    return _WS_RE.sub(" ", s)
def _is_finish_label(label: Optional[str]) -> bool:
    raw = _clean(label)
    low = raw.lower()
    return any(k in raw for k in FINISH_KEYWORDS_KO) or any(k in low for k in FINISH_KEYWORDS_EN)

class PredictionService:
    @staticmethod
    def calculate_prediction(splits: List[Dict], total_km: float) -> Dict:
        if not splits:
            return {"finished": False, "status_text": "대기중"}

        # ✅ 먼저 라벨 보강(모든 파서 공통)
        splits = ensure_finish_label(splits, total_km)

        # 1) 완주 여부
        finish_check = PredictionService.check_finish_status(splits, total_km)
        if finish_check['finished']:
            net = finish_check['finish_net'] or ""
            clk = finish_check['finish_clock'] or ""
            point = finish_check['finish_point'] or "완주"
            return {
                "finished": True,
                "status_text": "완주",
                "finish_point": point,
                "finish_eta": f"완주 @ {clk}" if clk else "완주",
                "finish_net_pred": net,
                "display_point_time": net or clk
            }

        # 2) 주행 중 예측
        last_split = splits[-1]
        psecs = [sec_per_km(s.get("pace")) for s in splits if sec_per_km(s.get("pace")) is not None]
        use_spk = sec_per_km(last_split.get("pace")) or (sum(psecs) / len(psecs) if psecs else None)
        if use_spk is None:
            return {"finished": False, "status_text": "주행중",
                    "next_point_km": None, "next_point_eta": None,
                    "finish_eta": None, "finish_net_pred": None}
        last_km = km_from_label(_clean(last_split.get("point_label"))) or last_split.get("point_km") or 0.0
        remain_fin = max(0.0, (total_km or 0.0) - float(last_km))
        delta_fin = int(remain_fin * use_spk)
        base_clock = _clean(last_split.get("pass_clock"))
        fin_eta = eta_from_clock(base_clock, delta_fin) if looks_time(base_clock) else None
        last_net = sec_from_mmss(_clean(last_split.get("net_time"))) or 0
        fin_net = last_net + delta_fin
        h, m, s = fin_net // 3600, (fin_net % 3600) // 60, fin_net % 60
        fin_net_str = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
        return {"finished": False, "status_text": "주행중",
                "finish_eta": fin_eta, "finish_net_pred": fin_net_str}

    @staticmethod
    def check_finish_status(splits: List[Dict], total_km: float) -> Dict:
        if not splits:
            return {'finished': False, 'finish_point': None, 'finish_net': None, 'finish_clock': None}

        #✅ 디버그: 마지막 3개 프린트 (옵션, 필요시 활성화)
        # print("[pred] tail:", [ { "label": _clean(s.get("point_label")),
        #                           "km": s.get("point_km"),
        #                           "net": _clean(s.get("net_time")),
        #                           "clk": _clean(s.get("pass_clock")) }
        #                        for s in splits[-3:] ])

        # 1) 라벨이 완주 계열인지
        finish_rows = [s for s in splits if _is_finish_label(s.get("point_label"))]
        if finish_rows:
            last_finish = finish_rows[-1]
            net = _clean(last_finish.get("net_time"))
            clk = _clean(last_finish.get("pass_clock"))
            # ⚠ looks_time이 엄격해 실패할 수도 있으니 널이더라도 완주 처리는 해주자
            if looks_time(net) or looks_time(clk) or net or clk:
                return {
                    'finished': True,
                    'finish_point': _clean(last_finish.get("point_label")) or "Finish",
                    'finish_net': net if looks_time(net) else (net or None),
                    'finish_clock': clk if looks_time(clk) else (clk or None)
                }

        # 2) 목표거리 근접
        snapped_km = snap_distance(total_km) or total_km
        tolerance = 0.5
        for (min_km, max_km), tol in DISTANCE_TOLERANCE.items():
            if min_km <= snapped_km < max_km:
                tolerance = tol
                break

        for s in reversed(splits):
            point_km = s.get("point_km") or km_from_label(_clean(s.get("point_label")))
            if point_km is None:
                continue
            if abs(float(point_km) - float(snapped_km)) <= tolerance:
                net = _clean(s.get("net_time"))
                clk = _clean(s.get("pass_clock"))
                if looks_time(net) or looks_time(clk) or net or clk:
                    return {
                        'finished': True,
                        'finish_point': _clean(s.get("point_label")) or "Finish",
                        'finish_net': net if looks_time(net) else (net or None),
                        'finish_clock': clk if looks_time(clk) else (clk or None)
                    }

        # 3) 90% 이상 진행(시간이 보이면 완주로 간주)
        try:
            total = float(total_km or 0.0)
        except Exception:
            total = 0.0
        if total > 0:
            last = splits[-1]
            last_km = last.get("point_km") or km_from_label(_clean(last.get("point_label")))
            try:
                last_km_f = float(last_km) if last_km is not None else None
            except Exception:
                last_km_f = None
            if last_km_f is not None and (last_km_f / total) >= 0.9:
                net = _clean(last.get("net_time"))
                clk = _clean(last.get("pass_clock"))
                if looks_time(net) or looks_time(clk) or net or clk:
                    return {
                        'finished': True,
                        'finish_point': _clean(last.get("point_label")) or "Finish",
                        'finish_net': net if looks_time(net) else (net or None),
                        'finish_clock': clk if looks_time(clk) else (clk or None)
                    }

        return {'finished': False, 'finish_point': None, 'finish_net': None, 'finish_clock': None}

    @staticmethod
    def is_finish_label(label: Optional[str]) -> bool:
        # 기존 외부 호출 호환
        return _is_finish_label(label)