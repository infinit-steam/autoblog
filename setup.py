"""대화식 초기 설정: config.yaml 생성 + 의존성 설치 안내."""
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).parent
CFG = ROOT / "config.yaml"


def ask(msg, default=""):
    v = input(f"{msg}" + (f" [{default}]" if default else "") + ": ").strip()
    return v or default


def main():
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10 이상이 필요합니다.")

    print("== 1) 패키지 설치 ==")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])

    if CFG.exists() and ask("config.yaml 이 이미 있습니다. 덮어쓸까요? (y/N)", "N").lower() != "y":
        print("기존 config.yaml 유지. 종료.")
        return

    print("\n== 2) Dolphin 설정 ==")
    api = ask("Dolphin Local API 주소", "http://localhost:3001")
    token = ask("Dolphin API 토큰")

    print("\n== 3) 계정 설정 ==")
    n = int(ask("계정 수", "2"))
    lines = ["dolphin:", f'  local_api: "{api}"', f'  token: "{token}"', "", "accounts:"]
    for i in range(1, n + 1):
        name = ask(f"[{i}] 계정 이름", f"acc{i}")
        pid = ask(f"[{i}] Dolphin 프로필 ID")
        bid = ask(f"[{i}] 네이버 블로그 ID")
        lines += [f"  - name: {name}", f'    profile_id: "{pid}"', f'    blog_id: "{bid}"']
    lines += ["", "delay:", "  between_posts: [60, 180]", ""]
    CFG.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n완료: {CFG}")
    print("다음 단계:")
    print("  python main.py --login-only <계정이름>   # 최초 1회 수동 로그인")
    print("  python main.py --dry-run                  # 발행 직전까지 테스트")
    print("  python main.py                            # 실제 발행")


if __name__ == "__main__":
    main()
