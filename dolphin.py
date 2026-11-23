"""Dolphin{Anty} Local API 래퍼 + Playwright CDP 연결."""
import requests
from contextlib import contextmanager
from playwright.sync_api import sync_playwright


class Dolphin:
    def __init__(self, base: str, token: str):
        self.base = base.rstrip("/")
        r = requests.post(f"{self.base}/v1.0/auth/login-with-token",
                          json={"token": token}, timeout=15)
        r.raise_for_status()

    def start(self, profile_id: str) -> dict:
        r = requests.get(f"{self.base}/v1.0/browser_profiles/{profile_id}/start",
                         params={"automation": 1}, timeout=60)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(f"프로필 시작 실패: {data}")
        return data["automation"]  # {"port":..., "wsEndpoint":...}

    def stop(self, profile_id: str):
        requests.get(f"{self.base}/v1.0/browser_profiles/{profile_id}/stop", timeout=30)


@contextmanager
def open_profile(dolphin: Dolphin, profile_id: str):
    auto = dolphin.start(profile_id)
    ws = f"ws://127.0.0.1:{auto['port']}{auto['wsEndpoint']}"
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(ws)
        try:
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            yield page
        finally:
            try:
                browser.close()
            except Exception:
                pass
            dolphin.stop(profile_id)
