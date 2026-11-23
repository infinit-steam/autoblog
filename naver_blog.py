"""네이버 블로그 글쓰기 (스마트에디터 ONE).
주의: 셀렉터는 네이버가 수시로 바꾸므로 SEL 에 모아두고 실제 화면에서 검증/수정할 것."""
import random
import re
import time
from pathlib import Path

ROOT = Path(__file__).parent

SEL = {
    "frame": "iframe#mainFrame",
    "title": ".se-documentTitle .se-text-paragraph",
    "body": ".se-component.se-text .se-text-paragraph",
    "popup_cancel": ".se-popup-button-cancel",   # '작성 중인 글' 팝업 → 취소(새로 쓰기)
    "save_btn": "button[class*=save_btn]",         # 상단 '저장'(임시저장)
    "image_btn": "button.se-image-toolbar-button",  # 툴바 '사진'
    "image_comp": ".se-component.se-image",
    "help_close": ".se-help-panel-close-button",  # 도움말 패널
}


# 입력 속도/대기 배율. main.py 가 config 의 pacing 값으로 덮어쓴다.
PACE = {"type_delay": (40, 110), "body_delay": (30, 90), "pause_scale": 1.0}


def human_pause(a=0.4, b=1.2):
    time.sleep(random.uniform(a, b) * PACE["pause_scale"])


def is_logged_in(page) -> bool:
    page.goto("https://www.naver.com", wait_until="domcontentloaded")
    # 화면 문구 대신 로그인 쿠키로 판별 (NID_AUT/NID_SES 는 로그인 시에만 존재)
    names = {c["name"] for c in page.context.cookies() if "naver.com" in c["domain"]}
    return "NID_AUT" in names and "NID_SES" in names


def close_help_panel(page, f) -> bool:
    """우측 '도움말' 패널이 열려 있으면 닫는다. 닫았으면 True."""
    btn = f.locator(SEL["help_close"])
    if not btn.count():
        # 클래스가 바뀐 경우 대비: '도움말' 제목이 있는 패널 안의 닫기(X) 버튼
        btn = f.locator("[class*=help] button[class*=close], [class*=help] button[aria-label*=닫기]")
    if btn.count() and btn.first.is_visible():
        btn.first.click()
        human_pause()
        return True
    # 마지막 수단: 패널이 떠 있는데 버튼을 못 찾은 경우 Esc
    if f.locator("[class*=help-panel], [class*=helpPanel]").count():
        page.keyboard.press("Escape")
        human_pause()
        return True
    return False


IMAGE_RE = re.compile(r"^\s*\[\[image:(.+?)\]\]\s*$")  # [[image:a.jpg]] 또는 [[image:a.jpg|b.jpg]]


def resolve_image(path: str, base_dir) -> Path:
    """상대경로는 본문 파일 폴더 → 프로젝트 루트 순으로 찾는다."""
    p = Path(path)
    if p.is_absolute():
        cands = [p]
    else:
        cands = [Path(base_dir) / p, ROOT / p] if base_dir else [ROOT / p]
    for c in cands:
        if c.is_file():
            return c
    raise FileNotFoundError(f"이미지 파일 없음: {path} (찾은 위치: {', '.join(map(str, cands))})")


def upload_image(page, path: Path):
    """툴바 '사진' 버튼 → 파일 선택창에 파일 지정 → 업로드 완료까지 대기. 커서는 이미지 아래로 이동."""
    before = page.locator(SEL["image_comp"]).count()
    with page.expect_file_chooser(timeout=15000) as fc:
        page.locator(SEL["image_btn"]).first.click()
    fc.value.set_files(str(path))
    # 이미지 컴포넌트가 늘고 업로드 중 표시가 사라질 때까지
    page.wait_for_function(
        "([sel, n]) => document.querySelectorAll(sel).length > n", arg=[SEL["image_comp"], before], timeout=60000)
    page.locator(f"{SEL['image_comp']} img").nth(before).wait_for(timeout=60000)
    human_pause(1.5, 3)


def write_post(page, blog_id: str, title: str, body: str, dry_run: bool = False, base_dir=None,
               mode: str = "draft"):
    """mode: 'draft'(임시저장, 기본) | 'publish'(즉시 발행). dry_run 이면 입력만 하고 중단."""
    page.goto(f"https://blog.naver.com/{blog_id}/postwrite", wait_until="domcontentloaded")
    # 에디터는 현재 최상위 페이지에 렌더링됨(예전엔 iframe#mainFrame). 둘 다 지원.
    page.wait_for_selector(f"{SEL['frame']}, {SEL['title']}", timeout=30000)
    f = page.frame_locator(SEL["frame"]) if page.locator(SEL["frame"]).count() else page
    f.locator(SEL["title"]).first.wait_for(timeout=30000)
    human_pause(1.5, 3)

    close_help_panel(page, f)
    popup = f.locator(SEL["popup_cancel"])
    if popup.count():
        popup.first.click()  # '작성 중인 글' 팝업 → 새로 쓰기
        human_pause()

    # 제목
    f.locator(SEL["title"]).first.click()
    page.keyboard.type(title, delay=random.randint(*PACE["type_delay"]))
    human_pause()

    # 본문 (줄 단위 입력). `[[image:경로]]` 한 줄은 그 위치에 사진 업로드.
    f.locator(SEL["body"]).first.click()
    after_image = True  # 첫 줄 / 이미지 직후에는 이미 새 문단에 커서가 있으므로 Enter 불필요
    for line in body.splitlines():
        m = IMAGE_RE.match(line)
        if m:
            if not after_image:
                page.keyboard.press("Enter")
            for path in m.group(1).split("|"):
                upload_image(page, resolve_image(path.strip(), base_dir))
            after_image = True
            continue
        if not after_image:
            page.keyboard.press("Enter")
        if line:
            page.keyboard.type(line, delay=random.randint(*PACE["body_delay"]))
        after_image = False
    human_pause(1, 2)

    if dry_run:
        page.screenshot(path=f"logs/dryrun_{int(time.time())}.png")
        print("[dry-run] 발행 직전에서 중단 (logs/dryrun_*.png 확인)")
        return

    if mode == "draft":
        # 임시저장: 상단 '저장' 버튼 → '임시저장이 완료되었습니다.' 토스트 확인. 발행은 사람이 직접.
        page.locator(SEL["save_btn"]).first.click()
        page.get_by_text("임시저장이 완료되었습니다").first.wait_for(timeout=20000)
        human_pause(1, 2)
        return

    # 발행: 상단 '발행' → 레이어의 '발행' 확인
    # exact=True: '예약 발행 0건' 버튼이 '발행' 부분일치로 잡히는 것을 방지
    f.get_by_role("button", name="발행", exact=True).first.click()
    human_pause(1, 2)
    f.get_by_role("button", name="발행", exact=True).last.click()
    page.wait_for_url("**/PostView**", timeout=30000)
