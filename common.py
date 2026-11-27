"""플랫폼 공통: 입력 속도/대기 배율, 대기 함수, 미디어 경로 해석."""
import random
import re
import time
from pathlib import Path

ROOT = Path(__file__).parent

# 입력 속도/대기 배율. main.py 가 config 의 pacing 값으로 덮어쓴다.
PACE = {"type_delay": (40, 110), "body_delay": (30, 90), "pause_scale": 1.0}

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXT = {".mp4", ".mov"}


_MARKER = re.compile(r"\[\[image:[^\[\]]+\]\]")


def normalize_image_markers(body: str) -> str:
    """문장 중간에 들어간 [[image:...]] 를 한 줄짜리 마커로 옮긴다.

    문장이 끊기지 않도록 마커를 빼낸 문단은 그대로 두고, 사진은 그 문단 아래에 둔다
    (문단이 마커로 시작하면 문단 위에 둔다). 이미 한 줄에 혼자 있는 마커는 그대로. 여러 번 적용해도 결과가 같다.
    """
    out = []
    for line in body.splitlines():
        marks = _MARKER.findall(line)
        if not marks or line.strip() == marks[0]:
            out.append(line)
            continue
        before, rest = [], line.strip()
        while True:
            m = _MARKER.match(rest)
            if not m:
                break
            before.append(m.group(0))
            rest = rest[m.end():].lstrip()
        after = _MARKER.findall(rest)
        text = re.sub(r"[ \t]{2,}", " ", _MARKER.sub("", rest)).strip()
        out += before + ([text] if text else []) + after
    return "\n".join(out)


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
