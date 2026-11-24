"""스레드(Threads) 웹 게시 (텍스트 + 선택적으로 사진/영상).

로그인: python main.py --login-only <계정> --platform threads  (인스타 계정으로 계속하기)
셀렉터는 한/영 문구 정규식으로 TXT 에 모았다. 실패 시 logs/ 스크린샷 확인.

규칙: 글 500자 이하. 미디어는 선택(없으면 텍스트만). 이미지 1~10장 또는 동영상 1개, 혼합 불가.
주제 태그(#)는 한 게시물에 하나만 인정되는 것으로 알려져 있어 2개 이상이면 경고한다.
임시저장: 작성 화면에 '임시 저장본' 이 있으나 이 모듈은 아직 지원하지 않는다 (post_mode 는 publish).
"""
import random
import re
import time

from common import PACE, IMAGE_EXT, VIDEO_EXT, human_pause, resolve_media

NAME = "threads"
LOGIN_URL = "https://www.threads.com/login"
BROWSE_PAGES = ["https://www.threads.com/"]
SUPPORTS_DRAFT = False

TEXT_MAX = 500
MAX_IMAGES = 10
MIN_BYTES = 1024

TXT = {
    "post": re.compile(r"^(게시|Post)$", re.I),
    "later": re.compile(r"^(나중에|나중에 하기|Not now|닫기|Close)$", re.I),
}
SEL = {
    "new_thread": "[aria-label='새로운 스레드'], [aria-label='New thread'], [aria-label='만들기'], [aria-label='Create']",
    "textbox": "[role=textbox][contenteditable=true], [contenteditable=true]",
    "file_input": "input[type=file]",
}


def is_logged_in(page) -> bool:
    page.goto("https://www.threads.com/", wait_until="domcontentloaded")
    names = {c["name"] for c in page.context.cookies() if "threads" in c["domain"]}
    return "sessionid" in names


def _validate(text: str, files) -> bool:
    """검증하고 동영상 여부를 돌려준다. 글만 올리는 경우 files 는 빈 목록."""
    if not text.strip():
        raise ValueError("스레드 글이 비어 있습니다")
    if len(text) > TEXT_MAX:
        raise ValueError(f"스레드 글이 {TEXT_MAX}자를 넘습니다 ({len(text)}자). 스레드용으로 줄여 쓰세요")
    for f in files:
        if f.stat().st_size < MIN_BYTES:
            raise ValueError(f"파일이 너무 작습니다 (1KB 미만): {f.name}")
    imgs = [f for f in files if f.suffix.lower() in IMAGE_EXT]
    vids = [f for f in files if f.suffix.lower() in VIDEO_EXT]
    if len(imgs) + len(vids) != len(files):
        raise ValueError("지원하지 않는 파일 형식이 있습니다 (이미지 jpg/png/webp, 동영상 mp4/mov)")
    if imgs and vids:
        raise ValueError("이미지와 동영상은 한 게시물에 섞을 수 없습니다")
    if len(vids) > 1:
        raise ValueError("동영상은 1개만 올릴 수 있습니다")
    if len(imgs) > MAX_IMAGES:
        raise ValueError(f"이미지는 최대 {MAX_IMAGES}장입니다 (현재 {len(imgs)}장)")
    tags = re.findall(r"#\w+", text)
    if len(tags) > 1:
        print(f"[주의] 해시태그 {len(tags)}개: 스레드는 주제 태그를 게시물당 하나만 인정하는 것으로 알려져 있습니다")
    return bool(vids)


def _open_composer(page):
    page.goto("https://www.threads.com/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    for _ in range(2):  # 안내 말풍선/알림 팝업 닫기 (있을 때만)
        b = page.get_by_role("button", name=TXT["later"])
        if b.count() and b.first.is_visible():
            b.first.click()
            human_pause()
    page.locator(SEL["new_thread"]).first.click(timeout=15000)
    dlg = page.locator("[role=dialog]").last
    dlg.locator(SEL["textbox"]).first.wait_for(state="visible", timeout=15000)
    human_pause(0.8, 1.6)
    return dlg


def _type_text(page, dlg, text: str):
    box = dlg.locator(SEL["textbox"]).first
    box.click()
    for i, line in enumerate(text.strip().splitlines()):
        if i:
            page.keyboard.press("Enter")
        if line:
            page.keyboard.type(line, delay=random.randint(*PACE["body_delay"]))
    human_pause(1, 2)


def _attach(page, dlg, files, is_video: bool):
    dlg.locator(SEL["file_input"]).first.set_input_files([str(f) for f in files])
    # 미리보기가 나타날 때까지 대기 (동영상은 오래 걸릴 수 있음)
    wait_ms = 120000 if is_video else 45000
    dlg.locator("img[src^='blob:'], video, [aria-label*='삭제'], [aria-label*='Remove']").first.wait_for(
        state="visible", timeout=wait_ms)
    human_pause(1.5, 3)


def post(page, account: dict, row: dict, body: str, base_dir, mode: str, dry_run: bool):
    if mode != "publish":
        raise ValueError("스레드는 임시저장을 지원하지 않습니다. config 의 post_mode 에 threads: publish 를 지정하세요")
    text = body.strip()
    spec = (row.get("media") or "").strip()
    files = resolve_media(spec, base_dir) if spec else []
    is_video = _validate(text, files)

    dlg = _open_composer(page)
    _type_text(page, dlg, text)
    if files:
        _attach(page, dlg, files, is_video)

    if dry_run:
        page.screenshot(path=f"logs/dryrun_threads_{int(time.time())}.png")
        print("[dry-run] 스레드 게시 직전에서 중단 (logs/dryrun_threads_*.png 확인)")
        return

    btn = dlg.get_by_role("button", name=TXT["post"]).last
    btn.wait_for(state="visible", timeout=10000)
    if not btn.is_enabled():
        raise RuntimeError("게시 버튼이 비활성 상태입니다 (글 또는 첨부가 아직 처리 중일 수 있음)")
    btn.click()
    # 작성 창이 닫히면 게시된 것으로 본다
    dlg.wait_for(state="hidden", timeout=180000 if is_video else 60000)
    human_pause(2, 4)
