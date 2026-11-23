"""새 주제 폴더 골격 생성.

  python tools/new_topic.py 제주여행
  python tools/new_topic.py 제주여행 --platforms naver instagram youtube

만들어지는 구조:
  content/<주제>/topic.md        주제 메모 (핵심 내용·키워드·말투·사진 설명)
  content/<주제>/media/          이 주제의 이미지·영상 (모든 플랫폼 공용 원본)
  content/<주제>/<플랫폼>/       플랫폼별 글 (naver/post.txt, instagram/caption.txt ...)
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = "<<작성 필요>>"  # 이 문구가 남아 있으면 enqueue 가 대기열 등록을 거부한다

TEMPLATES = {
    "naver": ("post.txt", f"{PLACEHOLDER}\n"
              "본문을 쓰고, 사진 위치에 한 줄로 [[image:../media/01.jpg]] 를 넣는다.\n"
              "여러 장은 [[image:../media/01.jpg|../media/02.jpg]].\n"),
    "instagram": ("caption.txt", f"{PLACEHOLDER}\n캡션 (2200자 이하, 해시태그 30개 이하)\n"),
    "youtube": ("description.txt", f"{PLACEHOLDER}\n설명란\n"),
    "facebook": ("post.txt", f"{PLACEHOLDER}\n게시글\n"),
}

TOPIC_MD = """# {name}

- 핵심 내용:
- 키워드:
- 말투/톤:
- 분량(글자수):
- 사진 설명 (media/ 의 파일별로 무엇인지):
  - 01.jpg:
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("topic")
    ap.add_argument("--platforms", nargs="+", default=["naver", "instagram"], choices=list(TEMPLATES))
    args = ap.parse_args()

    if re.search(r'[\\/:*?"<>|]', args.topic) or args.topic.startswith("_"):
        sys.exit("주제 이름에 \\ / : * ? \" < > | 를 쓸 수 없고 _ 로 시작할 수 없습니다.")
    base = ROOT / "content" / args.topic
    if base.exists():
        sys.exit(f"이미 있는 주제입니다: {base}")
    (base / "media").mkdir(parents=True)
    (base / "topic.md").write_text(TOPIC_MD.format(name=args.topic), encoding="utf-8")
    for p in args.platforms:
        fname, tpl = TEMPLATES[p]
        (base / p).mkdir()
        (base / p / fname).write_text(tpl, encoding="utf-8")
    print(f"생성: {base}")
    print("다음: media/ 에 이미지·영상을 넣고, 각 플랫폼 글을 작성한 뒤 enqueue 로 대기열에 등록")


if __name__ == "__main__":
    main()
