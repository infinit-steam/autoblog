"""주제 폴더의 글/미디어를 queue.csv 에 등록.

  python tools/enqueue.py 제주여행 --account acc1
  python tools/enqueue.py 제주여행 --account acc1 --platforms naver --title "제주 3박4일 후기"
  python tools/enqueue.py 제주여행 --account acc1 --platforms instagram --reel     # media/ 의 동영상을 릴스로

- 네이버: content/<주제>/naver/post.txt (제목은 --title, 없으면 주제 이름)
- 인스타: content/<주제>/instagram/caption.txt + media/ 의 이미지(이름순). --reel 이면 동영상 1개
- 같은 계정·플랫폼·파일이 이미 대기열에 있으면 중복 등록하지 않는다
- `<<작성 필요>>` 가 남아 있는 글은 등록을 거부한다
"""
import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from common import IMAGE_EXT, VIDEO_EXT  # noqa: E402

FIELDS = ["account", "platform", "title", "body_file", "media", "category", "status"]
BODY_FILE = {"naver": "post.txt", "instagram": "caption.txt"}
PLACEHOLDER = "<<작성 필요>>"


def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def build_row(topic: str, plat: str, account: str, title: str, reel: bool):
    base = ROOT / "content" / topic
    body = base / plat / BODY_FILE[plat]
    if not body.is_file():
        raise SystemExit(f"[{plat}] 글 파일이 없습니다: {rel(body)}")
    if PLACEHOLDER in body.read_text(encoding="utf-8-sig"):
        raise SystemExit(f"[{plat}] 아직 작성되지 않은 글입니다 ({PLACEHOLDER} 가 남아 있음): {rel(body)}")
    media = ""
    if plat == "instagram":
        files = sorted((base / "media").glob("*")) if (base / "media").is_dir() else []
        vids = [f for f in files if f.suffix.lower() in VIDEO_EXT]
        imgs = [f for f in files if f.suffix.lower() in IMAGE_EXT]
        chosen = vids[:1] if reel else imgs
        if reel and not vids:
            raise SystemExit(f"[instagram] media/ 에 동영상(mp4/mov)이 없습니다: {rel(base / 'media')}")
        if not chosen:
            raise SystemExit(f"[instagram] media/ 에 이미지(jpg/png/webp)가 없습니다: {rel(base / 'media')}")
        if len(chosen) > 10:
            raise SystemExit(f"[instagram] 이미지가 10장을 넘습니다 ({len(chosen)}장). media/ 를 정리하세요")
        media = "|".join(rel(f) for f in chosen)
    return {"account": account, "platform": plat, "title": title or topic,
            "body_file": rel(body), "media": media, "category": "", "status": "pending"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("topic")
    ap.add_argument("--account", required=True)
    ap.add_argument("--platforms", nargs="+", default=["naver", "instagram"], choices=list(BODY_FILE))
    ap.add_argument("--title", default="")
    ap.add_argument("--reel", action="store_true", help="인스타: 이미지 대신 media/ 의 동영상 1개를 릴스로")
    args = ap.parse_args()

    if not (ROOT / "content" / args.topic).is_dir():
        raise SystemExit(f"주제 폴더가 없습니다: content/{args.topic}")

    qpath = ROOT / "queue.csv"
    if qpath.exists():
        reader = csv.DictReader(qpath.open(encoding="utf-8-sig"))
        rows, fields = list(reader), list(reader.fieldnames or FIELDS)
    else:
        rows, fields = [], FIELDS
    for k in FIELDS:
        if k not in fields:
            fields.insert(min(len(fields), FIELDS.index(k)), k)

    new = [build_row(args.topic, p, args.account, args.title, args.reel and p == "instagram")
           for p in args.platforms]
    added = 0
    for r in new:
        dup = any(x.get("account") == r["account"] and (x.get("platform") or "naver") == r["platform"]
                  and x.get("body_file") == r["body_file"] and x.get("media", "") == r["media"] for x in rows)
        if dup:
            print(f"[중복 건너뜀] {r['account']} {r['platform']} {r['body_file']}")
            continue
        rows.append(r)
        added += 1
        print(f"[등록] {r['account']} {r['platform']} {r['body_file']} {r['media']}")

    with qpath.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(rows)
    print(f"{added}건 등록")


if __name__ == "__main__":
    main()
