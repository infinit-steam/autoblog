"""인스타그램 웹 게시 (사진 게시물 / 캐러셀 / 릴스).

!! 이 모듈의 셀렉터는 아직 실제 화면에서 검증되지 않았다 (인스타 로그인 후 --dry-run 으로 확인할 것).
인스타 웹은 UI 가 자주 바뀌므로 한/영 문구를 정규식으로 모아 TXT 에 두었다. 실패 시 logs/ 스크린샷 확인.

미디어 규칙: 이미지 1~10장(캐러셀) 또는 동영상 1개(릴스). 이미지와 동영상 혼합 불가.
캡션: 2200자 이하, 해시태그 30개 이하. 인스타 웹에는 임시저장이 없어 post_mode 는 publish 만 가능.
"""
import random
import re
import time

from common import PACE, IMAGE_EXT, VIDEO_EXT, human_pause, resolve_media

NAME = "instagram"
LOGIN_URL = "https://www.instagram.com/accounts/login/"
BROWSE_PAGES = ["https://www.instagram.com/", "https://www.instagram.com/explore/"]
SUPPORTS_DRAFT = False

CAPTION_MAX = 2200
HASHTAG_MAX = 30
MAX_IMAGES = 10
MIN_BYTES = 1024

# 한국어/영어 UI 모두 대응하는 문구 패턴
TXT = {
    "not_now": re.compile(r"^(나중에 하기|나중에|Not now)$", re.I),
    "create": re.compile(r"^(만들기|새로운 게시물|새 게시물|Create|New post)$", re.I),
    "post_item": re.compile(r"^(게시물|Post)$", re.I),
    "select_pc": re.compile(r"(컴퓨터에서 선택|Select from computer|Select from device)", re.I),
    "next": re.compile(r"^(다음|Next)$", re.I),
    "ok": re.compile(r"^(확인|OK)$", re.I),
    "fb_once": re.compile(r"^(이 게시물 공유하기|Share this post)$", re.I),  # (영구 설정인 '게시물 항상 공유하기' 와 구분)
    "upload_fail": re.compile(r"(파일을 업로드하지 못했습니다|Couldn.t upload|couldn.t be uploaded)", re.I),
    "share": re.compile(r"^(공유하기|공유|Share)$", re.I),
    "shared": re.compile(r"(게시물이 공유되었습니다|릴스가 공유되었습니다|Your post has been shared|Your reel has been shared|공유되었습니다)", re.I),
}
SEL = {
    "file_input": "input[type=file]",
    "caption": '[aria-label="문구를 입력하세요..."], [aria-label="Write a caption..."], '
               'div[role=textbox][contenteditable=true]',
}


def is_logged_in(page) -> bool:
    page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
    names = {c["name"] for c in page.context.cookies() if "instagram.com" in c["domain"]}
    return "sessionid" in names and "ds_user_id" in names


def _dismiss_popups(page):
    """'알림 설정', '로그인 정보 저장' 등 방해 팝업을 '나중에 하기'로 닫는다 (있을 때만)."""
    for _ in range(3):
        btn = page.get_by_role("button", name=TXT["not_now"])
        if btn.count() and btn.first.is_visible():
            btn.first.click()
            human_pause()
        else:
            break


def _click(page, name_re, role="button", timeout=15000):
    loc = page.get_by_role(role, name=name_re).first
    loc.wait_for(state="visible", timeout=timeout)
    loc.click()
    human_pause(0.8, 1.8)


def _validate(files, caption: str):
    for f in files:
        if f.stat().st_size < MIN_BYTES:  # 인스타가 업로드 단계에서 거부함 ("파일 크기가 1KB 이상이어야 합니다")
            raise ValueError(f"파일이 너무 작습니다 (1KB 미만): {f.name}")
    imgs = [f for f in files if f.suffix.lower() in IMAGE_EXT]
    vids = [f for f in files if f.suffix.lower() in VIDEO_EXT]
    if len(imgs) + len(vids) != len(files):
        raise ValueError("지원하지 않는 파일 형식이 있습니다 (이미지: jpg/png/webp, 동영상: mp4/mov)")
    if imgs and vids:
        raise ValueError("이미지와 동영상은 한 게시물에 섞을 수 없습니다")
    if len(vids) > 1:
        raise ValueError("릴스는 동영상 1개만 올릴 수 있습니다")
    if len(imgs) > MAX_IMAGES:
        raise ValueError(f"이미지는 최대 {MAX_IMAGES}장입니다 (현재 {len(imgs)})")
    if len(caption) > CAPTION_MAX:
        raise ValueError(f"캡션이 {CAPTION_MAX}자를 넘습니다 ({len(caption)}자)")
    tags = len(re.findall(r"#\w+", caption))
    if tags > HASHTAG_MAX:
        raise ValueError(f"해시태그가 {HASHTAG_MAX}개를 넘습니다 ({tags}개)")
    return bool(vids)


def _open_composer(page, files):
    page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    _dismiss_popups(page)
    _click(page, TXT["create"], role="link")
    # 일부 UI 는 '만들기' 뒤에 '게시물' 하위 메뉴가 나온다
    sub = page.get_by_role("link", name=TXT["post_item"])
    if sub.count() and sub.first.is_visible():
        sub.first.click()
        human_pause(0.8, 1.8)
    # 파일 선택: 버튼 클릭으로 파일선택창을 열고, 안 되면 숨은 input 에 직접 지정
    try:
        with page.expect_file_chooser(timeout=10000) as fc:
            _click(page, TXT["select_pc"])
        fc.value.set_files([str(f) for f in files])
    except Exception:
        page.locator(SEL["file_input"]).first.set_input_files([str(f) for f in files])
    human_pause(2, 4)


def _step_to_caption(page, is_reel: bool):
    """'다음' 을 눌러 캡션 입력 화면까지 진행 (자르기 → 편집 → 문구). 릴스 안내 팝업은 확인."""
    for _ in range(5):
        if page.locator(SEL["caption"]).first.is_visible():
            return
        err = page.get_by_text(TXT["upload_fail"])
        if err.count() and err.first.is_visible():
            detail = page.locator("[role=dialog]").last.inner_text()[:200].replace("\n", " ")
            raise RuntimeError(f"인스타가 파일 업로드를 거부했습니다: {detail}")
        ok = page.get_by_role("button", name=TXT["ok"])
        if is_reel and ok.count() and ok.first.is_visible():
            ok.first.click()  # "동영상 게시물은 이제 릴스로 공유됩니다"
            human_pause(1, 2)
            continue
        nxt = page.get_by_role("button", name=TXT["next"])
        if nxt.count() and nxt.first.is_visible():
            nxt.first.click()
            human_pause(1.5, 3)
        else:
            human_pause(1, 2)
    page.locator(SEL["caption"]).first.wait_for(state="visible", timeout=15000)


def _type_caption(page, caption: str):
    box = page.locator(SEL["caption"]).first
    box.click()
    for i, line in enumerate(caption.splitlines()):
        if i:
            page.keyboard.press("Enter")
        if line:
            page.keyboard.type(line, delay=random.randint(*PACE["body_delay"]))
    if re.search(r"#\w+$", caption):
        page.keyboard.type(" ")  # 끝이 해시태그면 추천 목록이 열려 있으니 공백으로 닫는다
    human_pause(1, 2)


def _enable_facebook_share(page):
    """공유 화면의 'Facebook' 스위치(이 게시물만 페이스북에도 공유)를 켠다.
    '고급 설정'의 'Facebook에 자동으로 공유'(모든 게시물 자동 공유 설정)는 건드리지 않는다."""
    label_js = """e => { let n = e; for (let k = 0; k < 6 && n; k++, n = n.parentElement) {
        const t = (n.innerText || '').trim(); if (t && t.length < 160) return t; } return ''; }"""

    def find_switch():
        """공유 화면에서 'Facebook' 스위치 핸들을 찾는다. (자동 공유 설정 스위치는 제외)"""
        dlg = page.locator("[role=dialog]").last
        for h in dlg.locator("[role=switch], input[type=checkbox]").element_handles():
            label = h.evaluate(label_js)
            if "facebook" in label.lower() and "자동으로" not in label:
                return h
        return None

    # 공유 화면은 비동기로 다시 그려지므로, 요소를 한 번 붙잡아 다루고 안 되면 잠시 뒤 다시 찾는다
    for _ in range(8):
        try:
            h = find_switch()
            if h is None:
                time.sleep(1)
                continue
            if h.get_attribute("aria-checked") == "true":
                return
            h.click()
            human_pause(0.8, 1.5)
            # 확인 팝업 'Facebook에 공유하기': 반드시 '이 게시물 공유하기' 만 누른다.
            # '게시물 항상 공유하기' 는 이후 모든 게시물을 자동 공유하는 영구 설정이므로 절대 누르지 않는다.
            once = page.get_by_role("button", name=TXT["fb_once"])
            if not (once.count() and once.first.is_visible()):
                once = page.get_by_text(TXT["fb_once"])
            try:
                once.first.wait_for(state="visible", timeout=4000)
                once.first.click()
                human_pause(0.8, 1.5)
            except Exception:
                pass  # 팝업 없이 바로 켜지는 경우
            h = find_switch()
            if h is not None and h.get_attribute("aria-checked") == "true":
                return
            raise RuntimeError("Facebook 공유 스위치를 켜지 못했습니다")
        except RuntimeError:
            raise
        except Exception:
            time.sleep(1)  # 화면이 다시 그려지는 중 - 재시도
    raise RuntimeError("공유 화면에 Facebook 스위치가 없습니다. 인스타 계정을 Meta 계정 센터에서 페이스북과 연결했는지 확인하세요")


def post(page, account: dict, row: dict, body: str, base_dir, mode: str, dry_run: bool):
    if mode != "publish":
        raise ValueError("인스타는 임시저장을 지원하지 않습니다. config 의 post_mode 에 instagram: publish 를 지정하세요")
    spec = (row.get("media") or "").strip()
    if not spec:
        raise ValueError("queue.csv 의 media 열이 비었습니다 (이미지 폴더/파일, 또는 동영상 1개)")
    files = resolve_media(spec, base_dir)
    caption = body.strip()
    is_reel = _validate(files, caption)

    _open_composer(page, files)
    _step_to_caption(page, is_reel)
    _type_caption(page, caption)
    if account.get("crosspost_facebook"):
        _enable_facebook_share(page)  # 같은 글을 연결된 페이스북에도 올린다 (config.yaml 계정의 crosspost_facebook: true)

    if dry_run:
        page.screenshot(path=f"logs/dryrun_ig_{int(time.time())}.png")
        print("[dry-run] 인스타 공유 직전에서 중단 (logs/dryrun_ig_*.png 확인)")
        return

    _click(page, TXT["share"])
    # 업로드/처리 완료 대기 (동영상은 오래 걸릴 수 있음)
    page.get_by_text(TXT["shared"]).first.wait_for(timeout=180000 if is_reel else 90000)
    human_pause(2, 4)
