"""플랫폼 모듈 레지스트리. 새 플랫폼은 모듈을 만들고 여기에 등록한다.

각 모듈의 공통 인터페이스:
  NAME, LOGIN_URL, BROWSE_PAGES, SUPPORTS_DRAFT
  is_logged_in(page) -> bool
  post(page, account, row, body, base_dir, mode, dry_run)
"""
import importlib

_NAMES = ["naver", "instagram"]


def get(name: str):
    name = (name or "naver").lower()
    if name not in _NAMES:
        raise SystemExit(f"지원하지 않는 platform: {name} (가능: {', '.join(_NAMES)})")
    return importlib.import_module(f"platforms.{name}")
