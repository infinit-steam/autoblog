import argparse, csv, random, time, yaml
from pathlib import Path
from dolphin import Dolphin, open_profile
import naver_blog

ROOT = Path(__file__).parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="발행 직전까지만")
    ap.add_argument("--login-only", metavar="ACCOUNT", help="프로필만 열어 수동 로그인")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    accts = {a["name"]: a for a in cfg["accounts"]}
    dol = Dolphin(cfg["dolphin"]["local_api"], cfg["dolphin"]["token"])

    if args.login_only:
        a = accts[args.login_only]
        with open_profile(dol, a["profile_id"]) as page:
            page.goto("https://nid.naver.com/nidlogin.login")
            input("브라우저에서 직접 로그인 후 Enter... ")
        return

    qpath = ROOT / "queue.csv"
    rows = list(csv.DictReader(qpath.open(encoding="utf-8")))
    for row in rows:
        if row["status"] != "pending":
            continue
        a = accts[row["account"]]
        body = (ROOT / row["body_file"]).read_text(encoding="utf-8")
        try:
            with open_profile(dol, a["profile_id"]) as page:
                if not naver_blog.is_logged_in(page):
                    raise RuntimeError("로그아웃 상태 - --login-only 로 먼저 로그인")
                try:
                    naver_blog.write_post(page, a["blog_id"], row["title"], body, args.dry_run)
                except Exception:
                    page.screenshot(path=str(ROOT / "logs" / f"{row['account']}_{int(time.time())}.png"))
                    raise
            row["status"] = "dry" if args.dry_run else "done"
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
