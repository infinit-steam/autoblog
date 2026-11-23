import argparse, csv, random, time, yaml
from pathlib import Path
from browser import open_browser
import common
import platforms
from pacing import Pacing
import human

ROOT = Path(__file__).parent
QUEUE_FIELDS = ["account", "platform", "title", "body_file", "media", "category", "status"]


def resolve_mode(cfg: dict, platform: str) -> str:
    """post_mode: 문자열(전체 공통) 또는 {플랫폼: 모드}. 기본은 안전하게 draft."""
    pm = cfg.get("post_mode") or "draft"
    mode = (pm.get(platform) if isinstance(pm, dict) else pm) or "draft"
    mode = str(mode).lower()
    if mode not in ("draft", "publish"):
        raise SystemExit(f"post_mode({platform}) 는 draft 또는 publish 여야 합니다: {mode}")
    return mode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="발행 직전까지만")
    ap.add_argument("--force", action="store_true", help="활동시간·일일한도·휴무일·시작지연 무시")
    ap.add_argument("--login-only", metavar="ACCOUNT", help="프로필만 열어 수동 로그인")
    ap.add_argument("--platform", default="naver", help="--login-only 와 함께 쓸 플랫폼 (naver|instagram)")
    ap.add_argument("--only", metavar="PLATFORM", help="해당 플랫폼의 글만 처리")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    accts = {a["name"]: a for a in cfg["accounts"]}

    if args.login_only:
        a = accts[args.login_only]
        plat = platforms.get(args.platform)
        with open_browser(cfg, a) as page:
            page.goto(plat.LOGIN_URL)
            input("브라우저에서 직접 로그인 후 Enter... ")
        return

    pace = Pacing(cfg.get("pacing"), ROOT / "state.json")
    common.PACE.update(pace.typing())
    # --dry-run / --force 는 시간대·한도·휴무일·지연을 무시 (테스트용). 입력 속도는 항상 적용.
    free = args.dry_run or args.force
    if not free and not pace.in_active_hours():
        raise SystemExit(f"활동 시간대 밖입니다 (active_hours={pace.c['active_hours']}). 무시하려면 --force")

    qpath = ROOT / "queue.csv"
    reader = csv.DictReader(qpath.open(encoding="utf-8-sig"))
    rows = list(reader)
    fields = list(reader.fieldnames or QUEUE_FIELDS)
    for k in QUEUE_FIELDS:  # 구버전 queue.csv 호환: 없는 열은 추가
        if k not in fields:
            fields.insert(min(len(fields), QUEUE_FIELDS.index(k)), k)
    jittered = free
    for row in rows:
        if row.get("status") != "pending":
            continue
        row.setdefault("platform", "")
        row["platform"] = (row["platform"] or "naver").lower()
        if args.only and row["platform"] != args.only.lower():
            continue
        plat = platforms.get(row["platform"])
        key = f"{row['account']}:{plat.NAME}"  # 한도·기록은 계정×플랫폼 단위
        if not free:
            ok, why = pace.allow(key)
            if not ok:
                print(f"[건너뜀] {key} {row['title']}: {why}")
                continue
            if not jittered:
                wait = pace.jitter_seconds()
                print(f"[대기] 시작 지연 {wait / 60:.1f}분")
                time.sleep(wait)
                jittered = True
        a = accts[row["account"]]
        mode = resolve_mode(cfg, plat.NAME)
        body_path = ROOT / row["body_file"]
        body = body_path.read_text(encoding="utf-8-sig")
        hcfg = {"pages": plat.BROWSE_PAGES, **(cfg.get("human") or {})}
        if (cfg.get("human") or {}).get("pages") and plat.NAME != "naver":
            hcfg["pages"] = plat.BROWSE_PAGES  # config 의 pages 는 네이버용. 다른 플랫폼은 모듈 기본값
        try:
            with open_browser(cfg, a) as page:
                if not plat.is_logged_in(page):
                    raise RuntimeError(f"{plat.NAME} 로그아웃 상태 - --login-only {a['name']} --platform {plat.NAME} 로 먼저 로그인")
                human.browse(page, hcfg)  # 게시 전 스크롤/둘러보기
                try:
                    plat.post(page, a, row, body, body_path.parent, mode, args.dry_run)
                except Exception:
                    page.screenshot(path=str(ROOT / "logs" / f"{row['account']}_{plat.NAME}_{int(time.time())}.png"))
                    raise
                if not args.dry_run:
                    human.browse(page, hcfg, post=True)  # 게시 후(설정 시)
            row["status"] = "dry" if args.dry_run else ("draft" if mode == "draft" else "done")
            if not args.dry_run:
                pace.record(key)
        except Exception as e:
            print(f"[실패] {key} {row['title']}: {e}")
            row["status"] = "failed"
        lo, hi = cfg["delay"]["between_posts"]
        time.sleep(random.uniform(lo, hi))

    with qpath.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", restval="")
        w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
