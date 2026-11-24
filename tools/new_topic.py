"""새 주제 폴더 골격 생성.

  python tools/new_topic.py 제주여행
  python tools/new_topic.py 제주여행 --platforms naver instagram

content/<주제>/  topic.md, media/, naver/post.txt, instagram/caption.txt
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import topics  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("topic")
    ap.add_argument("--platforms", nargs="+", default=["naver", "instagram", "threads"], choices=list(topics.PLATFORMS))
    a = ap.parse_args()
    try:
        base = topics.create_topic(a.topic, a.platforms)
    except ValueError as e:
        sys.exit(str(e))
    print(f"생성: {base}")


if __name__ == "__main__":
    main()
