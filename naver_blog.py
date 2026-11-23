"""네이버 블로그 글쓰기 (스마트에디터 ONE).
주의: 셀렉터는 네이버가 수시로 바꾸므로 SEL 에 모아두고 실제 화면에서 검증/수정할 것."""
import random
import time

SEL = {
    "frame": "iframe#mainFrame",
    "title": ".se-documentTitle .se-text-paragraph",
    "body": ".se-component.se-text .se-text-paragraph",
    "popup_cancel": ".se-popup-button-cancel",   # '작성 중인 글' 팝업 → 취소(새로 쓰기)
    "help_close": ".se-help-panel-close-button",  # 도움말 패널
}


def human_pause(a=0.4, b=1.2):
    time.sleep(random.uniform(a, b))


def is_logged_in(page) -> bool:
    page.goto("https://www.naver.com", wait_until="domcontentloaded")
    return page.locator("text=로그인").count() == 0 or page.locator("#account").count() > 0


def write_post(page, blog_id: str, title: str, body: str, dry_run: bool = False):
    page.goto(f"https://blog.naver.com/{blog_id}/postwrite", wait_until="domcontentloaded")
    page.wait_for_selector(SEL["frame"], timeout=30000)
    f = page.frame_locator(SEL["frame"])
    human_pause(1.5, 3)

    # 방해 팝업/도움말 닫기 (있을 때만)
    for key in ("popup_cancel", "help_close"):
        loc = f.locator(SEL[key])
        if loc.count():
            loc.first.click()
            human_pause()

    # 제목
    f.locator(SEL["title"]).first.click()
    page.keyboard.type(title, delay=random.randint(40, 110))
    human_pause()

    # 본문 (줄 단위 입력)
    f.locator(SEL["body"]).first.click()
    for i, line in enumerate(body.splitlines()):
        if i:
            page.keyboard.press("Enter")
        page.keyboard.type(line, delay=random.randint(30, 90))
    human_pause(1, 2)

    if dry_run:
        print("[dry-run] 발행 직전에서 중단")
        return

    # 발행: 상단 '발행' → 레이어의 '발행' 확인
    f.get_by_role("button", name="발행").first.click()
    human_pause(1, 2)
    f.get_by_role("button", name="발행").last.click()
    page.wait_for_url("**/PostView**", timeout=30000)
