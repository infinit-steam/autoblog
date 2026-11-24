"""주제 폴더의 글/미디어를 queue.csv 에 등록.

  python tools/enqueue.py 제주여행 --account acc1
  python tools/enqueue.py 제주여행 --account acc1 --platforms naver --title "제주 3박4일 후기"
  python tools/enqueue.py 제주여행 --account acc1 --platforms instagram --reel     # media/ 의 동영상을 릴스로

- 네이버: content/<주제>/naver/post.txt (제목은 --title → meta.json 의 title → 주제 이름 순)
- 인스타: content/<주제>/instagram/caption.txt + media/ 의 이미지(GUI 에서 정한 순서). --reel 이면 동영상 1개
- 같은 계정·플랫폼·파일이 이미 대기열에 있으면 중복 등록하지 않는다
- 미작성(`<<작성 필요>>`)이거나 빈 글은 등록을 거부한다
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import queue_store  # noqa: E402
import topics  # noqa: E402
from common import IMAGE_EXT, VIDEO_EXT  # noqa: E402


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def build_row(topic: str, plat: str, account: str, title: str, reel: bool) -> dict:
    if plat not in topics.PLATFORMS:
        raise ValueError(f"지원하지 않는 플랫폼: {plat}")
    body = topics.text_path(topic, plat)
    label = topics.PLATFORMS[plat]["label"]
    if not body.is_file():
        raise ValueError(f"[{label}] 글 파일이 없습니다: {_rel(body)}")
    if not topics.is_written(topic, plat):
        raise ValueError(f"[{label}] 아직 작성되지 않은 글입니다: {_rel(body)}")
    media = ""
    if plat == "instagram":
        files = topics.media_files(topic)
        vids = [f for f in files if f.suffix.lower() in VIDEO_EXT]
        imgs = [f for f in files if f.suffix.lower() in IMAGE_EXT]
        if reel and not vids:
            raise ValueError(f"[{label}] media/ 에 동영상(mp4/mov)이 없습니다")
        chosen = vids[:1] if reel else imgs
        if not chosen:
            raise ValueError(f"[{label}] media/ 에 이미지(jpg/png/webp)가 없습니다")
        if len(chosen) > 10:
            raise ValueError(f"[{label}] 이미지가 10장을 넘습니다 ({len(chosen)}장). media/ 를 정리하세요")
        media = "|".join(_rel(f) for f in chosen)
    elif plat == "threads":  # 스레드는 글만 올려도 되므로 미디어는 선택 (있으면 이미지, --reel 이면 동영상 1개)
        files = topics.media_files(topic)
        vids = [f for f in files if f.suffix.lower() in VIDEO_EXT]
        imgs = [f for f in files if f.suffix.lower() in IMAGE_EXT]
        if reel and not vids:
            raise ValueError(f"[{label}] media/ 에 동영상(mp4/mov)이 없습니다")
        chosen = vids[:1] if reel else imgs[:10]
        media = "|".join(_rel(f) for f in chosen)
    default_title = topics.read_meta(topic).get("title") or topic
    return {"account": account, "platform": plat, "title": title or default_title,
            "body_file": _rel(body), "media": media, "category": "", "status": "pending"}


def add_to_queue(topic: str, account: str, platforms, title: str = "", reel: bool = False) -> list[str]:
    """등록 결과 메시지 목록을 돌려준다. 문제가 있으면 ValueError (하나도 등록하지 않음)."""
    if not topics.topic_dir(topic).is_dir():
        raise ValueError(f"주제 폴더가 없습니다: content/{topic}")
    if not account:
        raise ValueError("계정을 선택하세요.")
    if not platforms:
        raise ValueError("플랫폼을 하나 이상 선택하세요.")
    new = [build_row(topic, p, account, title, reel and p in ("instagram", "threads")) for p in platforms]
    rows, fields = queue_store.load()
    msgs = []
    for r in new:
        dup = any(x.get("account") == r["account"] and x.get("platform") == r["platform"]
                  and x.get("body_file") == r["body_file"] and x.get("media", "") == r["media"]
                  and x.get("status") == "pending" for x in rows)
        label = topics.PLATFORMS[r["platform"]]["label"]
        if dup:
            msgs.append(f"[중복 건너뜀] {r['account']} {label} (이미 대기 중)")
            continue
        rows.append(r)
        msgs.append(f"[등록] {r['account']} {label}")
    queue_store.save(rows, fields)
    return msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("topic")
    ap.add_argument("--account", required=True)
    ap.add_argument("--platforms", nargs="+", default=["naver", "instagram"], choices=list(topics.PLATFORMS))
    ap.add_argument("--title", default="")
    ap.add_argument("--reel", action="store_true", help="인스타: 이미지 대신 media/ 의 동영상 1개를 릴스로")
    a = ap.parse_args()
    try:
        for m in add_to_queue(a.topic, a.account, a.platforms, a.title, a.reel):
            print(m)
    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
