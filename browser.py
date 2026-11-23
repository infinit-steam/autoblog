"""브라우저 백엔드 선택: 일반 Chrome(기본) 또는 Dolphin{Anty}.

config.yaml 의 `browser:` 값으로 전환한다.
  browser: chrome    # 일반 Chrome + 계정별 전용 프로필 폴더 (무료)
  browser: dolphin   # Dolphin{Anty} (유료 플랜의 automation 필요)
"""
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).parent
_dolphin = None


@contextmanager
def _open_chrome(cfg: dict, account: dict):
    """계정별 영구 프로필(profiles/<name>)로 Chrome 실행. 로그인 상태가 폴더에 보존된다."""
    from playwright.sync_api import sync_playwright

    chrome_cfg = cfg.get("chrome") or {}
    user_dir = Path(chrome_cfg.get("profiles_dir", ROOT / "profiles")) / account["name"]
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
