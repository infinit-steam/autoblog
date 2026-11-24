"""주제 폴더 로직 (GUI/CLI 공용, 화면 없음).

content/<주제>/
  topic.md  meta.json  media/  naver/post.txt  instagram/caption.txt
meta.json: {"title": 네이버 글 제목, "media_order": [파일명...], "ig_reel": bool}
"""
import json
import re
import shutil
from pathlib import Path

from common import IMAGE_EXT, VIDEO_EXT

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
PLACEHOLDER = "<<작성 필요>>"  # 미작성 표시. 이 문구가 남은 글은 대기열 등록이 거부된다

PLATFORMS = {
    "naver": {"label": "네이버 블로그", "file": "post.txt",
              "hint": "본문을 쓰고, 사진 위치에 한 줄로 [[image:../media/01.jpg]] 를 넣는다.\n"},
    "instagram": {"label": "인스타그램", "file": "caption.txt",
                  "hint": "캡션 (2200자 이하, 해시태그 30개 이하)\n"},
    "threads": {"label": "스레드", "file": "post.txt",
                "hint": "스레드 글 (500자 이하, 해시태그는 1개 이하 권장). 사진/영상은 선택.\n"},
}
TOPIC_MD = "# {name}\n\n- 핵심 내용:\n- 키워드:\n- 말투/톤:\n- 분량(글자수):\n- 사진 설명:\n"


def name_error(name: str) -> str | None:
    name = (name or "").strip()
    if not name:
        return "주제 이름을 입력하세요."
    if re.search(r'[\\/:*?"<>|]', name):
        return '주제 이름에 \\ / : * ? " < > | 를 쓸 수 없습니다.'
    if name.startswith(("_", ".")):
        return "주제 이름은 _ 나 . 으로 시작할 수 없습니다."
    if (CONTENT / name).exists():
        return f"이미 있는 주제입니다: {name}"
    return None


def topic_dir(topic: str) -> Path:
    return CONTENT / topic


def list_topics() -> list[str]:
    if not CONTENT.is_dir():
        return []
    return sorted(p.name for p in CONTENT.iterdir()
                  if p.is_dir() and not p.name.startswith(("_", ".")))


def create_topic(name: str, platforms=("naver", "instagram", "threads")) -> Path:
    err = name_error(name)
    if err:
        raise ValueError(err)
    base = topic_dir(name.strip())
    (base / "media").mkdir(parents=True)
    (base / "topic.md").write_text(TOPIC_MD.format(name=name.strip()), encoding="utf-8")
    for p in platforms:
        (base / p).mkdir()
        (base / p / PLATFORMS[p]["file"]).write_text(f"{PLACEHOLDER}\n{PLATFORMS[p]['hint']}", encoding="utf-8")
    return base


def delete_topic(topic: str):
    shutil.rmtree(topic_dir(topic))


# ---- 메타 ----
def read_meta(topic: str) -> dict:
    try:
        return json.loads((topic_dir(topic) / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_meta(topic: str, meta: dict):
    (topic_dir(topic) / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


# ---- 글 ----
def text_path(topic: str, platform: str) -> Path:
    return topic_dir(topic) / platform / PLATFORMS[platform]["file"]


def read_text(topic: str, platform: str) -> str:
    """미작성(플레이스홀더)이면 빈 문자열을 돌려준다."""
    try:
        t = text_path(topic, platform).read_text(encoding="utf-8-sig")
    except OSError:
        return ""
    return "" if PLACEHOLDER in t else t


def write_text(topic: str, platform: str, text: str):
    p = text_path(topic, platform)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = text.replace("\r\n", "\n").rstrip("\n")
    p.write_text((text + "\n") if text.strip() else f"{PLACEHOLDER}\n{PLATFORMS[platform]['hint']}",
                 encoding="utf-8")


def read_memo(topic: str) -> str:
    try:
        return (topic_dir(topic) / "topic.md").read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def write_memo(topic: str, text: str):
    (topic_dir(topic) / "topic.md").write_text(text.replace("\r\n", "\n"), encoding="utf-8")


def is_written(topic: str, platform: str) -> bool:
    return bool(read_text(topic, platform).strip())


# ---- 미디어 ----
def _media_dir(topic: str) -> Path:
    return topic_dir(topic) / "media"


def media_files(topic: str) -> list[Path]:
    """media/ 의 이미지·영상. meta 의 media_order 가 우선, 나머지는 이름순."""
    d = _media_dir(topic)
    if not d.is_dir():
        return []
    ok = IMAGE_EXT | VIDEO_EXT
    files = {f.name: f for f in d.iterdir() if f.is_file() and f.suffix.lower() in ok}
    order = [n for n in read_meta(topic).get("media_order", []) if n in files]
    rest = sorted(n for n in files if n not in order)
    return [files[n] for n in order + rest]


def _save_order(topic: str, names: list[str]):
    meta = read_meta(topic)
    meta["media_order"] = names
    write_meta(topic, meta)


def add_media(topic: str, sources) -> list[str]:
    d = _media_dir(topic)
    d.mkdir(parents=True, exist_ok=True)
    added = []
    for s in map(Path, sources):
        if s.suffix.lower() not in IMAGE_EXT | VIDEO_EXT:
            raise ValueError(f"지원하지 않는 형식: {s.name} (이미지 jpg/png/webp, 영상 mp4/mov)")
        dest, i = d / s.name, 1
        while dest.exists():
            dest = d / f"{s.stem}_{i}{s.suffix}"
            i += 1
        shutil.copy2(s, dest)
        added.append(dest.name)
    _save_order(topic, [f.name for f in media_files(topic)])
    return added


def delete_media(topic: str, name: str):
    (_media_dir(topic) / name).unlink()
    _save_order(topic, [f.name for f in media_files(topic)])


def move_media(topic: str, name: str, delta: int):
    names = [f.name for f in media_files(topic)]
    i = names.index(name)
    j = i + delta
    if 0 <= j < len(names):
        names[i], names[j] = names[j], names[i]
        _save_order(topic, names)
