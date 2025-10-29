from datetime import datetime, timedelta
from config.constants import TIME_RX

def looks_time(text: str) -> bool:
    if not text:
        return False
    return bool(TIME_RX.search(str(text)))

def all_times(text: str) -> list[str]:
    return TIME_RX.findall(text or "")

def first_time(text: str) -> str:
    m = TIME_RX.search(text or "")
    return m.group(0) if m else ""

def sec_from_mmss(mmss: str):
    """
    'mm:ss', 'mm:ss.sss', 'hh:mm:ss', 'hh:mm:ss.sss' 모두 지원.
    반환값은 반올림한 정수 초.
    """
    if not mmss:
        return None
    t = mmss.strip()
    try:
        parts = t.split(":")
        if len(parts) == 3:
            h = int(parts[0])
            m = int(parts[1])
            s = float(parts[2])   # ← 소수 초 지원
            return int(round(h*3600 + m*60 + s))
        if len(parts) == 2:
            m = int(parts[0])
            s = float(parts[1])   # ← 소수 초 지원
            return int(round(m*60 + s))
    except Exception:
        return None

def sec_per_km(pace: str):
    x = sec_from_mmss(pace)
    return float(x) if x is not None else None

def eta_from_clock(clock: str, delta_sec: int):
    try:
        base = datetime.strptime(clock, "%H:%M:%S")
        return (base + timedelta(seconds=delta_sec)).time().strftime("%H:%M:%S")
    except:
        return None

def parse_time_to_sec(t: str):
    if not t:
        return None
    t = t.strip()
    try:
        if t.count(":") == 2:
            h, m, s = map(int, t.split(":"))
            return h * 3600 + m * 60 + s
        if t.count(":") == 1:
            m, s = map(int, t.split(":"))
            return m * 60 + s
    except:
        return None