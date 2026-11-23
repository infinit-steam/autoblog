"""플랫폼 공통: 입력 속도/대기 배율, 대기 함수, 미디어 경로 해석."""
import random
import time
from pathlib import Path

ROOT = Path(__file__).parent

# 입력 속도/대기 배율. main.py 가 config 의 pacing 값으로 덮어쓴다.
PACE = {"type_delay": (40, 110), "body_delay": (30, 90), "pause_scale": 1.0}

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXT = {".mp4", ".mov"}


def human_pause(a=0.4, b=1.2):
    time.sleep(random.uniform(a, b) * PACE["pause_scale"])


def resolve_path(path: str, base_dir=None) -> Path:
    """상대경로는 base_dir → 프로젝트 루트 → content/ 순으로 찾는다."""
    p = Path(path)
    if p.is_absolute():
        cands = [p]
    else:
        cands = ([Path(base_dir) / p] if base_dir else []) + [ROOT / p, ROOT / "content" / p]
    for c in cands:
        if c.exists():
            return c
    raise FileNotFoundError(f"파일/폴더 없음: {path} (찾은 위치: {', '.join(map(str, cands))})")


def resolve_media(spec: str, base_dir=None) -> list[Path]:
    """`a.jpg|b.jpg` 또는 폴더 경로를 파일 목록으로. 폴더면 이름순 정렬."""
    out: list[Path] = []
    for part in (s.strip() for s in spec.split("|") if s.strip()):
        p = resolve_path(part, base_dir)
        if p.is_dir():
            out += sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXT | VIDEO_EXT)
        else:
            out.append(p)
    if not out:
        raise FileNotFoundError(f"미디어 없음: {spec}")
    return out
