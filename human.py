"""사람 같은 브라우징 동작: 스크롤, 마우스 이동, 다른 페이지 둘러보기.

게시 전/후에 잠깐 실행한다. 링크 클릭이나 입력은 하지 않고 페이지 이동·스크롤·대기만 한다.
config.yaml 의 `human:` 섹션으로 설정.
"""
import random
import time

DEFAULTS = {
    "enabled": True,
    "pages": [                     # 둘러볼 페이지 후보 (이 중 무작위로 골라 방문)
        "https://www.naver.com",
        "https://section.blog.naver.com/BlogHome.naver",
        "https://news.naver.com",
    ],
    "pages_to_visit": [1, 3],      # 방문할 페이지 수 범위
    "dwell_sec": [8, 25],          # 페이지당 머무는 시간(초)
    "after_post_dwell_sec": [0, 0],  # 게시 후 추가 둘러보기(0 이면 안 함)
}


def _scroll_page(page, seconds: float):
    """seconds 동안 불규칙하게 스크롤·멈춤·살짝 되올리기·마우스 이동."""
    end = time.time() + seconds
    try:
        vw = page.viewport_size or {"width": 1200, "height": 800}
    except Exception:
        vw = {"width": 1200, "height": 800}
    while time.time() < end:
        try:
            page.mouse.move(random.randint(100, vw["width"] - 100),
                            random.randint(100, vw["height"] - 100), steps=random.randint(8, 25))
            step = random.randint(250, 700)
            if random.random() < 0.15:
                step = -random.randint(100, 300)  # 가끔 위로
            page.mouse.wheel(0, step)
        except Exception:
            return  # 페이지 이동/종료 중이면 조용히 중단
        time.sleep(random.uniform(0.6, 2.8))


def browse(page, cfg: dict | None, post: bool = False):
    c = {**DEFAULTS, **(cfg or {})}
    if not c["enabled"]:
        return
    if post:
        lo, hi = c["after_post_dwell_sec"]
        if hi <= 0:
            return
        urls, dwell = [random.choice(c["pages"])], (lo, hi)
    else:
        n_lo, n_hi = c["pages_to_visit"]
        n = min(random.randint(n_lo, n_hi), len(c["pages"]))
        urls, dwell = random.sample(c["pages"], n), c["dwell_sec"]
    for url in urls:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"[둘러보기 건너뜀] {url}: {e}")
            continue
        _scroll_page(page, random.uniform(*dwell))
