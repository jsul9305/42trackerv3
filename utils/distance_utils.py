from config.constants import STANDARD_DISTANCES, FULL_KM, HALF_KM, KM_RX,FINISH_KEYWORDS_EN, FINISH_KEYWORDS_KO
import re

def km_from_label(label: str) -> float | None:
    if not label:
        return None
    # e.g., "5km", "5.0km", "10.5 km"
    m = re.search(r"(\d+(?:\.\d+)?)\s*km", label, re.I)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    
    # 숫자만 있는 경우 (e.g., "42.195")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)", label.strip())
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    # Section N → 숫자만 추정치로 넣지 말고 None 유지(거리 모름)
    return None

def snap_distance(km: float|None) -> float|None:
    if not km or km <= 0:
        return None
    # 가까운 표준 거리로 스냅(±0.6km)
    best = min(STANDARD_DISTANCES, key=lambda d: abs(d-km))
    return best if abs(best-km) <= 0.6 else km

def extract_distance_from_text(text: str) -> tuple[str | None, float | None]:
    """
    텍스트 안에서 거리/키워드를 찾아서 (레이블, km) 반환.
    - "Half/하프" → 21.0
    - "Full/풀(코스)" → 42.1
    - "109K" "5km" 등 숫자+단위 → 해당 수치
    """
    t = (text or "").strip().lower()

    # ① 키워드 우선
    if re.search(r"\b(full|풀코스|풀)\b", t):
        return ("Full", float(FULL_KM))
    if re.search(r"\b(half|하프)\b", t):
        return ("Half", float(HALF_KM))

    # ② 숫자 + 단위(KM/K)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|k)\b", t)
    if m:
        km = float(m.group(1))
        return (f"{km:g}K", km)

    return (None, None)

def normalize_category_from_label(label: str | None) -> tuple[str | None, float | None]:
    """라벨 문자열에서 종목명/거리 추출. ex) '5km', '10K', 'Half', 'Full'"""
    s = (label or "").strip().lower()
    if not s:
        return (None, None)
    # 명시 키워드 우선
    if "half" in s or "하프" in s:
        return ("Half", 21.1)
    if "full" in s or "풀" in s:
        return ("Full", 42.2)
    # 숫자 km/k
    m = KM_RX.search(s)
    if m:
        try:
            km = float(m.group(1))
        except Exception:
            km = None
        # 대표 표기
        if km is not None:
            if 4.0 <= km <= 6.5:   return ("5km", 5.0)
            if 9.0 <= km <= 11.5:  return ("10km", 10.0)
            if 20.0 <= km <= 22.8: return ("Half", 21.1)
            if 39.0 <= km <= 45.0: return ("Full", 42.2)
            return (f"{km:g}km", km)
    return (None, None)

def category_from_km(km: float | None) -> str:
    """거리 숫자만으로 종목명 추론(여유 범위 포함)"""
    if km is None:
        return "미분류"
    if 39.0 <= km <= 45.0:  return "Full"
    if 20.0 <= km <= 22.8:  return "Half"
    if 9.0  <= km <= 11.5:  return "10km"
    if 4.0  <= km <= 6.5:   return "5km"
    # 모호하면 숫자 그대로 보여주기
    return f"{km:g}km"

def label_for_distance(d: float | None) -> str:
    if d is None: return "Unknown"
    if abs(d-42.195) <= 0.5: return "Full"
    if abs(d-32.0)   <= 0.5: return "32K"
    if abs(d-21.1)   <= 0.4: return "Half"
    if abs(d-10.0)   <= 0.3: return "10K"
    if abs(d-5.0)    <= 0.25:return "5K"
    if abs(d-3.0)    <= 0.2: return "3K"
    return f"{d:g}K"

def dist_from_label(lbl: str | None) -> float | None:
    if not lbl: return None
    s = lbl.lower()
    if "full" in s or "42.195" in s: return 42.195
    if "32" in s and ("k" in s or "km" in s): return 32.0
    if "half" in s or "21.1" in s: return 21.1
    if "10" in s and ("k" in s or "km" in s): return 10.0
    if "5"  in s and ("k" in s or "km" in s): return 5.0
    if "3"  in s and ("k" in s or "km" in s): return 3.0
    return None

_ZWSP_RE = re.compile(r"[\u200b\u200c\u200d\uFEFF]")
_WS_RE   = re.compile(r"\s+")

def _clean_text(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = _ZWSP_RE.sub("", s)          # 제로폭 문자 제거
    s = s.replace("\xa0", " ")       # NBSP 정규화
    s = s.strip()
    s = _WS_RE.sub(" ", s)           # 연속 공백 1칸
    return s

def is_finish_label(label: str) -> bool:
    raw = _clean_text(label)
    low = raw.lower()
    return any(k in raw for k in FINISH_KEYWORDS_KO) or any(k in low for k in FINISH_KEYWORDS_EN)

def ensure_finish_label(splits, race_total_km=None):
    """마지막 스플릿이 완주로 간주되면 point_label을 Finish로 보강."""
    if not isinstance(splits, list) or not splits:
        return splits
    last = splits[-1]
    label = _clean_text(last.get("point_label") or "")
    if is_finish_label(label):
        return splits
    km = last.get("point_km")
    try:
        kmf = float(km) if km is not None else None
    except Exception:
        kmf = None
    if race_total_km:
        try:
            target = float(race_total_km)
        except Exception:
            target = None
    else:
        target = None

    # 거리 기반 판정
    if target is not None and kmf is not None and kmf >= target - 1.0:
        last["point_label"] = "Finish"
    elif target is None and kmf is not None and 41.5 <= kmf <= 43.0:
        last["point_label"] = "Finish"
    return splits