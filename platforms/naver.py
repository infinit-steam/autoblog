"""네이버 블로그 글쓰기 (스마트에디터 ONE).
주의: 셀렉터는 네이버가 수시로 바꾸므로 SEL 에 모아두고 실제 화면에서 검증/수정할 것."""
import random
import re
import time
from pathlib import Path

from common import ROOT, PACE, human_pause, normalize_image_markers

NAME = "naver"
LOGIN_URL = "https://nid.naver.com/nidlogin.login"
BROWSE_PAGES = [
    "https://www.naver.com",
    "https://section.blog.naver.com/BlogHome.naver",
    "https://news.naver.com",
]
SUPPORTS_DRAFT = True

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


UPLOAD_TIMEOUT_MS = 180000  # 사진 한 장 업로드 대기 (느린 PC/네트워크 대비 3분)


def check_images(body: str, base_dir):
    """본문의 [[image:...]] 파일이 모두 있는지 브라우저를 열기 전에 확인한다 (글을 절반 치다가 멈추는 것을 방지)."""
    missing = []
    for line in normalize_image_markers(body).splitlines():
        m = IMAGE_RE.match(line)
        if m:
            for path in m.group(1).split("|"):
                try:
                    resolve_image(path.strip(), base_dir)
                except FileNotFoundError:
                    missing.append(path.strip())
    if missing:
        raise FileNotFoundError(
            "본문에 쓴 사진 파일이 이 PC에 없습니다: " + ", ".join(dict.fromkeys(missing)) +
            " — 글과 함께 media 폴더(content/<주제>/media)도 복사했는지 확인하세요")


def verify_typed(f, body: str):
    """입력이 끝난 뒤 화면의 본문이 기대한 글과 맞는지 확인한다. 일부만 들어갔으면 예외."""
    exp = re.sub(r"\s+", "", "".join(l for l in body.splitlines() if not IMAGE_RE.match(l)))
    got = re.sub(r"[\s​]+", "", "".join(f.locator(SEL["body"]).all_inner_texts()))
    if "[[image:" in got:
        raise RuntimeError("사진 마커가 사진으로 바뀌지 않고 글자로 입력되었습니다. 본문의 [[image:...]] 형식을 확인하세요")
    n_img = sum(len(IMAGE_RE.match(l).group(1).split("|")) for l in body.splitlines() if IMAGE_RE.match(l))
    have_img = f.locator(SEL["image_comp"]).count()
    print(f"[입력] 확인: 본문 {len(got)}/{len(exp)}자, 사진 {have_img}/{n_img}장", flush=True)
    if exp and len(got) < len(exp) * 0.9:
        raise RuntimeError(f"본문이 일부만 입력되었습니다 (기대 {len(exp)}자, 화면 {len(got)}자)")
    if have_img < n_img:
        raise RuntimeError(f"사진이 일부만 올라갔습니다 ({have_img}/{n_img}장)")


def upload_image(page, path: Path):
    """툴바 '사진' 버튼 → 파일 선택창에 파일 지정 → 업로드 완료까지 대기. 커서는 이미지 아래로 이동."""
    before = page.locator(SEL["image_comp"]).count()
    with page.expect_file_chooser(timeout=20000) as fc:
        page.locator(SEL["image_btn"]).first.click()
    fc.value.set_files(str(path))
    # 이미지 컴포넌트가 늘고 업로드 중 표시가 사라질 때까지
    page.wait_for_function(
        "([sel, n]) => document.querySelectorAll(sel).length > n", arg=[SEL["image_comp"], before],
        timeout=UPLOAD_TIMEOUT_MS)
    page.locator(f"{SEL['image_comp']} img").nth(before).wait_for(timeout=UPLOAD_TIMEOUT_MS)
    human_pause(1.5, 3)


def write_post(page, blog_id: str, title: str, body: str, dry_run: bool = False, base_dir=None,
               mode: str = "draft"):
    """mode: 'draft'(임시저장, 기본) | 'publish'(즉시 발행). dry_run 이면 입력만 하고 중단."""
    page.goto(f"https://blog.naver.com/{blog_id}/postwrite", wait_until="domcontentloaded")
    # 에디터는 현재 최상위 페이지에 렌더링됨(예전엔 iframe#mainFrame). 둘 다 지원.
    try:
        page.wait_for_selector(f"{SEL['frame']}, {SEL['title']}", timeout=30000)
        f = page.frame_locator(SEL["frame"]) if page.locator(SEL["frame"]).count() else page
        f.locator(SEL["title"]).first.wait_for(timeout=30000)
    except Exception as e:
        raise RuntimeError(
            f"글쓰기 편집기가 열리지 않았습니다 (블로그 ID '{blog_id}', 현재 주소 {page.url}). "
            "로그인한 계정의 블로그가 맞는지, 블로그가 개설되어 있는지, 네이버의 추가 확인 화면이 없는지 "
            "logs 폴더의 스크린샷으로 확인하세요") from e
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
    body = normalize_image_markers(body)  # 문장 중간의 마커는 문단 아래 한 줄로 옮긴다
    f.locator(SEL["body"]).first.click()
    lines = body.splitlines()
    n_chars = sum(len(l) for l in lines if not IMAGE_RE.match(l))
    lo, hi = PACE["body_delay"]
    est = int(n_chars * (lo + hi) / 2000 * max(PACE.get("pause_scale", 1.0), 1.0))
    print(f"[입력] 본문 {n_chars}자 입력 시작 (글자마다 {lo}~{hi}ms 간격이라 약 {est // 60}분 {est % 60}초 걸립니다. "
          f"전체 입력 시간 제한은 없습니다)", flush=True)
    after_image = True  # 첫 줄 / 이미지 직후에는 이미 새 문단에 커서가 있으므로 Enter 불필요
    done_chars, last_report = 0, 0
    for i, line in enumerate(lines, 1):
        m = IMAGE_RE.match(line)
        if m:
            if not after_image:
                page.keyboard.press("Enter")
            for path in m.group(1).split("|"):
                img = resolve_image(path.strip(), base_dir)
                print(f"[입력] 사진 업로드 중: {img.name} ({img.stat().st_size // 1024}KB)", flush=True)
                upload_image(page, img)
            after_image = True
            continue
        if not after_image:
            page.keyboard.press("Enter")
        if line:
            page.keyboard.type(line, delay=random.randint(*PACE["body_delay"]))
            done_chars += len(line)
        after_image = False
        if done_chars - last_report >= 300 and n_chars:  # 300자마다 진행 상황
            last_report = done_chars
            print(f"[입력] 본문 {done_chars}/{n_chars}자 ({i}/{len(lines)}줄)", flush=True)
    human_pause(1, 2)
    verify_typed(f, body)

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


def precheck(account: dict, row: dict, body: str, base_dir):
    """브라우저를 열기 전에 main.py 가 호출하는 사전 검사."""
    check_images(body, base_dir)


def current_blog_id(page) -> str | None:
    """로그인한 계정의 블로그 ID. 네이버의 '내 블로그' 주소가 본인 블로그로 이동하는 것을 이용한다."""
    page.goto("https://blog.naver.com/MyBlog.naver", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    m = re.match(r"https?://(?:m\.)?blog\.naver\.com/([A-Za-z0-9_\-]+)(?:[/?#]|$)", page.url)
    return m.group(1) if m else None  # 'MyBlog.naver' 처럼 점이 있는 주소는 매치되지 않는다


def _configured_blog_id(account: dict) -> str:
    v = str(account.get("blog_id") or "").strip()
    return "" if v.startswith("네이버블로그ID") else v  # 예시 설정값은 비어 있는 것으로 본다


def resolve_blog_id(page, account: dict) -> str:
    """게시에 쓸 블로그 ID. 비어 있으면 로그인한 계정의 블로그를 쓰고, 다르면 중단한다."""
    want, actual = _configured_blog_id(account), current_blog_id(page)
    if actual is None:
        if want:
            return want  # 확인할 수 없으면 설정값으로 시도
        raise ValueError("로그인한 계정의 블로그를 찾지 못했습니다. 네이버 블로그가 개설되어 있는지 확인하거나 config.yaml 에 blog_id 를 적으세요")
    if want and want.lower() != actual.lower():
        raise ValueError(
            f"config.yaml 의 blog_id '{want}' 와 이 PC 에서 로그인한 계정의 블로그 '{actual}' 가 다릅니다. "
            f"'{actual}' 에 올리려면 blog_id 를 '{actual}' 로 바꾸거나 비워 두고(blog_id: \"\"), "
            f"'{want}' 에 올리려면 login.bat 으로 그 계정에 다시 로그인하세요")
    return actual


def describe_login(page, account: dict) -> str:
    """로그인 확인 때 보여줄 추가 정보."""
    want, actual = _configured_blog_id(account), current_blog_id(page)
    if actual is None:
        return "[블로그] 로그인한 계정의 블로그를 찾지 못했습니다 (블로그 개설 여부 확인)"
    if want and want.lower() != actual.lower():
        return f"[블로그] 주의: 로그인한 블로그는 '{actual}' 인데 config.yaml 의 blog_id 는 '{want}' 입니다. 맞게 고치세요"
    return f"[블로그] 블로그 ID: {actual}" + ("" if want else " (config 의 blog_id 가 비어 있어 이 값을 자동 사용)")


def post(page, account: dict, row: dict, body: str, base_dir, mode: str, dry_run: bool):
    """main.py 가 호출하는 공통 진입점."""
    check_images(body, base_dir)  # 사진 파일 확인
    blog_id = resolve_blog_id(page, account)
    write_post(page, blog_id, row["title"], body, dry_run, base_dir=base_dir, mode=mode)
