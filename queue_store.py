"""queue.csv 읽기/쓰기 (GUI/CLI 공용)."""
import csv
from pathlib import Path

QPATH = Path(__file__).resolve().parent / "queue.csv"
FIELDS = ["account", "platform", "title", "body_file", "media", "category", "status"]


def load() -> tuple[list[dict], list[str]]:
    if not QPATH.exists():
        return [], list(FIELDS)
    reader = csv.DictReader(QPATH.open(encoding="utf-8-sig"))
    rows, fields = list(reader), list(reader.fieldnames or FIELDS)
    for k in FIELDS:  # 구버전 queue.csv 호환
        if k not in fields:
            fields.insert(min(len(fields), FIELDS.index(k)), k)
    for r in rows:
        r["platform"] = (r.get("platform") or "naver").lower()
    return rows, fields


def save(rows: list[dict], fields: list[str]):
    with QPATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(rows)
