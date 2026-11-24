import argparse, csv, random, time, yaml
from pathlib import Path
from browser import open_browser
import common
import platforms
from pacing import Pacing
import human

ROOT = Path(__file__).parent
QUEUE_FIELDS = ["account", "platform", "title", "body_file", "media", "category", "status"]


def resolve_mode(cfg: dict, platform: str, default: str = "draft") -> str:
    """post_mode: 문자열(전체 공통) 또는 {플랫폼: 모드}. 지정이 없으면 default
    (임시저장을 지원하는 플랫폼은 draft, 지원하지 않는 플랫폼은 publish)."""
    pm = cfg.get("post_mode") or default
    mode = (pm.get(platform) if isinstance(pm, dict) else pm) or default
    mode = str(mode).lower()
    if mode not in ("draft", "publish"):
        raise SystemExit(f"post_mode({platform}) 는 draft 또는 publish 여야 합니다: {mode}")
    return mode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="발행 직전까지만")
    ap.add_argument("--force", action="store_true", help="활동시간·일일한도·휴무일·시작지연 무시")
    ap.add_argument("--login-only", metavar="ACCOUNT", help="프로필만 열어 수동 로그인")
    ap.add_argument("--platform", default="naver", help="--login-only 와 함께 쓸 플랫폼 (naver|instagram|threads)")
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

    def _plat(r):
        return (r.get("platform") or "naver").lower()

    todo = [r for r in rows if r.get("status") == "pending" and (not args.only or _plat(r) == args.only.lower())]
    kind = "dry-run" if args.dry_run else "실제 실행"
    print(f"[시작] {kind} - 대기(pending) {len(todo)}건 / 대기열 전체 {len(rows)}건", flush=True)
    if not todo:
        counts: dict[str, int] = {}
        for r in rows:
            counts[r.get("status") or "(비어 있음)"] = counts.get(r.get("status") or "(비어 있음)", 0) + 1
        print("처리할 글이 없습니다. 대기열 상태: " + (", ".join(f"{k} {v}건" for k, v in counts.items()) or "대기열이 비어 있음"))
        if args.only:
            print(f"(--only {args.only} 필터가 적용되어 있습니다)")
        print("→ 편집 탭에서 '대기열에 등록' 하거나, 대기열 탭에서 행을 선택해 '대기(pending)로 되돌리기'를 누르세요.", flush=True)
        return
    n_done = n_fail = n_skip = 0
    for idx, row in enumerate(todo, 1):
        row["platform"] = _plat(row)
        plat = platforms.get(row["platform"])
        key = f"{row['account']}:{plat.NAME}"  # 한도·기록은 계정×플랫폼 단위
        if not free:
            ok, why = pace.allow(key)
            if not ok:
                print(f"[건너뜀] {key} {row['title']}: {why}", flush=True)
                n_skip += 1
                continue
            if not jittered:
                wait = pace.jitter_seconds()
                print(f"[대기] 시작 지연 {wait / 60:.1f}분")
                time.sleep(wait)
                jittered = True
        print(f"[진행 {idx}/{len(todo)}] {key} '{row['title']}'", flush=True)
        browsed = False  # 브라우저를 실제로 열었는지 (열기 전에 실패했으면 글 사이 대기가 필요 없다)
        try:
            # 준비 단계의 오류(없는 계정, 삭제된 글 파일 등)도 이 행의 실패로 처리하고 다음 행으로 넘어간다
            if row["account"] not in accts:
                raise ValueError(f"config.yaml 에 없는 계정입니다: {row['account']} (등록된 계정: {', '.join(accts)})")
            a = accts[row["account"]]
            mode = resolve_mode(cfg, plat.NAME, "draft" if getattr(plat, "SUPPORTS_DRAFT", False) else "publish")
            body_path = ROOT / row["body_file"]
            if not body_path.is_file():
                raise FileNotFoundError(f"글 파일이 없습니다: {row['body_file']}")
            body = body_path.read_text(encoding="utf-8-sig")
            hcfg = {"pages": plat.BROWSE_PAGES, **(cfg.get("human") or {})}
            if (cfg.get("human") or {}).get("pages") and plat.NAME != "naver":
                hcfg["pages"] = plat.BROWSE_PAGES  # config 의 pages 는 네이버용. 다른 플랫폼은 모듈 기본값
            for m in filter(None, (row.get("media") or "").split("|")):  # 미디어 파일이 지워졌는지 미리 확인
                if not (ROOT / m).exists():
                    raise FileNotFoundError(f"미디어 파일이 없습니다: {m}")
            browsed = True
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
            n_done += 1
            print(f"[완료] {key} '{row['title']}' → {row['status']}", flush=True)
        except Exception as e:
            print(f"[실패] {key} {row['title']}: {e}", flush=True)
            row["status"] = "failed"
            n_fail += 1
        if idx < len(todo) and browsed:  # 마지막 글 뒤, 또는 브라우저를 열지 않은 실패 뒤에는 쉬지 않는다
            lo, hi = cfg["delay"]["between_posts"]
            wait = random.uniform(lo, hi)
            print(f"[대기] 다음 글까지 {wait:.0f}초", flush=True)
            time.sleep(wait)

    with qpath.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", restval="")
        w.writeheader(); w.writerows(rows)
    print(f"[종료] 성공 {n_done}건 / 실패 {n_fail}건 / 건너뜀 {n_skip}건", flush=True)


if __name__ == "__main__":
    main()
