"""브라우저 백엔드 선택: 일반 Chrome(기본) 또는 Dolphin{Anty}.

config.yaml 의 `browser:` 값으로 전환한다.
  browser: chrome    # 일반 Chrome + 계정별 전용 프로필 폴더 (무료)
  browser: dolphin   # Dolphin{Anty} (유료 플랜의 automation 필요)
"""
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).parent
_dolphin = None

# 로그인 쿠키를 유지할 사이트. 세션 쿠키(만료일 없음)는 브라우저를 닫으면 사라지므로,
# 닫기 직전에 만료일을 붙여 Chrome 자신의 쿠키 저장소에 남긴다 ('로그인 상태 유지' 를 놓쳐도 로그인이 유지됨).
PERSIST_DOMAINS = ("naver.com", "instagram.com", "threads.com", "threads.net", "facebook.com")
PERSIST_DAYS = 90


def profile_dir(cfg: dict, account: dict) -> Path:
    chrome_cfg = cfg.get("chrome") or {}
    return Path(chrome_cfg.get("profiles_dir", ROOT / "profiles")) / account["name"]


def _persist_session_cookies(ctx):
    exp = time.time() + PERSIST_DAYS * 86400
    fix = []
    for c in ctx.cookies():
        if (c.get("expires") or -1) > 0:
            continue  # 이미 만료일이 있는 쿠키는 그대로 둔다
        if not any(d in c.get("domain", "") for d in PERSIST_DOMAINS):
            continue
        fix.append({k: c[k] for k in ("name", "value", "domain", "path", "httpOnly", "secure", "sameSite") if k in c}
                   | {"expires": exp})
    if fix:
        ctx.add_cookies(fix)


@contextmanager
def _open_chrome(cfg: dict, account: dict):
    """계정별 영구 프로필(profiles/<name>)로 Chrome 실행. 로그인 상태가 폴더에 보존된다."""
    from playwright.sync_api import sync_playwright

    chrome_cfg = cfg.get("chrome") or {}
    user_dir = profile_dir(cfg, account)
    user_dir.mkdir(parents=True, exist_ok=True)
    kwargs = dict(
        user_data_dir=str(user_dir),
        headless=False,
        no_viewport=True,
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )
    if chrome_cfg.get("channel", "chrome"):
        kwargs["channel"] = chrome_cfg.get("channel", "chrome")  # 설치된 Chrome 사용
    if chrome_cfg.get("proxy"):
        kwargs["proxy"] = {"server": chrome_cfg["proxy"]}

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(**kwargs)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            yield page
        finally:
            try:
                _persist_session_cookies(ctx)
            except Exception:
                pass  # 쿠키 보존 실패가 작업을 막지 않게 한다
            try:
                ctx.close()
            except Exception:
                pass


@contextmanager
def _open_dolphin(cfg: dict, account: dict):
    global _dolphin
    from dolphin import Dolphin, open_profile

    if _dolphin is None:
        d = cfg["dolphin"]
        _dolphin = Dolphin(d["local_api"], d["token"])
    with open_profile(_dolphin, account["profile_id"]) as page:
        yield page


def open_browser(cfg: dict, account: dict):
    """cfg['browser'] 에 따라 페이지를 yield 하는 컨텍스트 매니저를 반환."""
    mode = (cfg.get("browser") or "chrome").lower()
    if mode == "chrome":
        return _open_chrome(cfg, account)
    if mode == "dolphin":
        return _open_dolphin(cfg, account)
    raise ValueError(f"알 수 없는 browser 값: {mode} (chrome | dolphin)")
