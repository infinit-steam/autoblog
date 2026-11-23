"""자동화 패턴 조절: 하루 게시 한도, 활동 시간대, 시작 지연, 랜덤 휴무일, 점진적 증량, 입력 속도.

config.yaml 의 `pacing:` 섹션으로 설정. 계정별 게시 기록은 state.json 에 저장(.gitignore).
"""
import datetime as dt
import json
import random
from pathlib import Path

DEFAULTS = {
    "daily_limit": 1,            # 계정당 하루 최대 게시 수
    "ramp_up_every_days": 0,     # N일마다 한도 +1 (0 이면 증량 없음)
    "ramp_up_max": 3,            # 증량 상한
    "active_hours": [9, 22],     # 이 시간대(시)에만 실행. [시작, 끝) — 로컬 시각
    "start_jitter_min": [0, 30], # 첫 게시 전 랜덤 대기(분). 스케줄러가 정시에 실행해도 시각이 흩어짐
    "skip_day_prob": 0.0,        # 계정별로 이 확률로 그날은 쉼 (같은 날 재실행해도 결과 동일)
    "type_delay_ms": [40, 110],  # 제목 글자당 입력 간격
    "body_delay_ms": [30, 90],   # 본문 글자당 입력 간격
    "pause_scale": 1.0,          # 동작 사이 대기 배율 (1.5 = 50% 더 느리게)
}


class Pacing:
    def __init__(self, cfg: dict | None, state_path: Path):
        self.c = {**DEFAULTS, **(cfg or {})}
        self.path = Path(state_path)
        try:
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.state = {}

    # --- 상태 ---
    def _posts(self, account: str) -> list:
        return self.state.get(account, {}).get("posts", [])

    def _save(self):
        self.path.write_text(json.dumps(self.state, ensure_ascii=False, indent=1), encoding="utf-8")

    def record(self, account: str):
        now = dt.datetime.now().isoformat(timespec="seconds")
        s = self.state.setdefault(account, {"first": now, "posts": []})
        s["posts"].append(now)
        self._save()

    # --- 판단 ---
    def in_active_hours(self, now=None) -> bool:
        lo, hi = self.c["active_hours"]
        return lo <= (now or dt.datetime.now()).hour < hi

    def limit_today(self, account: str, today=None) -> int:
        n = int(self.c["daily_limit"])
        every = int(self.c["ramp_up_every_days"])
        first = self.state.get(account, {}).get("first")
        if every > 0 and first:
            days = ((today or dt.date.today()) - dt.date.fromisoformat(first[:10])).days
            n = min(int(self.c["ramp_up_max"]), n + days // every)
        return n

    def count_today(self, account: str, today=None) -> int:
        d = (today or dt.date.today()).isoformat()
        return sum(1 for t in self._posts(account) if t.startswith(d))

    def is_rest_day(self, account: str, today=None) -> bool:
        p = float(self.c["skip_day_prob"])
        if p <= 0:
            return False
        d = (today or dt.date.today()).isoformat()
        return random.Random(f"{account}:{d}").random() < p  # 계정+날짜로 고정된 난수

    def allow(self, account: str) -> tuple[bool, str]:
        if self.is_rest_day(account):
            return False, "오늘은 휴무일(skip_day_prob)"
        used, lim = self.count_today(account), self.limit_today(account)
        if used >= lim:
            return False, f"오늘 한도 도달 ({used}/{lim})"
        return True, ""

    def jitter_seconds(self) -> float:
        lo, hi = self.c["start_jitter_min"]
        return random.uniform(lo, hi) * 60

    def typing(self) -> dict:
        return {
            "type_delay": tuple(self.c["type_delay_ms"]),
            "body_delay": tuple(self.c["body_delay_ms"]),
            "pause_scale": float(self.c["pause_scale"]),
        }
