import argparse, csv, random, time, yaml
from pathlib import Path
from browser import open_browser
import naver_blog
from pacing import Pacing
import human

ROOT = Path(__file__).parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="발행 직전까지만")
    ap.add_argument("--force", action="store_true", help="활동시간·일일한도·휴무일·시작지연 무시")
    ap.add_argument("--login-only", metavar="ACCOUNT", help="프로필만 열어 수동 로그인")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    mode = (cfg.get("post_mode") or "draft").lower()  # draft(임시저장, 기본) | publish
    if mode not in ("draft", "publish"):
        raise SystemExit(f"post_mode 는 draft 또는 publish 여야 합니다: {mode}")
    accts = {a["name"]: a for a in cfg["accounts"]}

    if args.login_only:
        a = accts[args.login_only]
        with open_browser(cfg, a) as page:
            page.goto("https://nid.naver.com/nidlogin.login")
            input("브라우저에서 직접 로그인 후 Enter... ")
        return

    pace = Pacing(cfg.get("pacing"), ROOT / "state.json")
    naver_blog.PACE.update(pace.typing())
    # --dry-run / --force 는 시간대·한도·휴무일·지연을 무시 (테스트용). 입력 속도는 항상 적용.
    free = args.dry_run or args.force
    if not free and not pace.in_active_hours():
        raise SystemExit(f"활동 시간대 밖입니다 (active_hours={pace.c['active_hours']}). 무시하려면 --force")

    qpath = ROOT / "queue.csv"
    rows = list(csv.DictReader(qpath.open(encoding="utf-8")))
    jittered = free
    for row in rows:
        if row["status"] != "pending":
            continue
        if not free:
            ok, why = pace.allow(row["account"])
            if not ok:
                print(f"[건너뜀] {row['account']} {row['title']}: {why}")
                continue
            if not jittered:
                wait = pace.jitter_seconds()
                print(f"[대기] 시작 지연 {wait / 60:.1f}분")
                time.sleep(wait)
                jittered = True
        a = accts[row["account"]]
        body = (ROOT / row["body_file"]).read_text(encoding="utf-8")
        try:
            with open_browser(cfg, a) as page:
                if not naver_blog.is_logged_in(page):
                    raise RuntimeError("로그아웃 상태 - --login-only 로 먼저 로그인")
                human.browse(page, cfg.get("human"))  # 게시 전 스크롤/둘러보기
                try:
                    naver_blog.write_post(page, a["blog_id"], row["title"], body, args.dry_run,
                                          base_dir=(ROOT / row["body_file"]).parent, mode=mode)
                except Exception:
                    page.screenshot(path=str(ROOT / "logs" / f"{row['account']}_{int(time.time())}.png"))
                    raise
                if not args.dry_run:
                    human.browse(page, cfg.get("human"), post=True)  # 게시 후(설정 시)
            row["status"] = "dry" if args.dry_run else ("draft" if mode == "draft" else "done")
            if not args.dry_run:
                pace.record(row["account"])
        except Exception as e:
            print(f"[실패] {row['account']} {row['title']}: {e}")
            row["status"] = "failed"
        lo, hi = cfg["delay"]["between_posts"]
        time.sleep(random.uniform(lo, hi))

    with qpath.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
