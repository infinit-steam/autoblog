# autoblog — Dolphin{Anty} + Playwright 네이버 블로그 자동 발행

## 다른 컴퓨터로 옮기기
1. 이 폴더 전체를 복사 (단, `config.yaml`, `logs/` 는 제외 — 토큰이 들어 있음)
2. 새 컴퓨터에 준비
   - Python 3.10+
   - Dolphin{Anty} 설치 · 로그인 · 프로필 생성 · 프록시 연결 (Dolphin 앱을 켜둔 상태로 실행)
   - Dolphin API 토큰 발급
3. `python setup.py` — 패키지 설치 + `config.yaml` 대화식 생성
4. 최초 1회 계정별 수동 로그인: `python main.py --login-only acc1`
5. 테스트: `python main.py --dry-run`
6. 실제 발행: `python main.py`

> 프로필 ID는 컴퓨터마다 다릅니다. 새 컴퓨터에서 프로필을 새로 만들면 ID가 바뀌므로 setup 때 다시 입력하세요.
> 로그인 세션은 프로필(그 컴퓨터의 Dolphin)에 저장되므로 컴퓨터를 옮기면 다시 로그인해야 합니다.

## 발행 대기열 (`queue.csv`)
| 컬럼 | 설명 |
|---|---|
| account | config.yaml 의 계정 이름 |
| title | 글 제목 |
| body_file | 본문 텍스트 파일 경로 (`content/…`) |
| category | (미구현) |
| status | `pending` 만 처리. 결과: done / dry / failed |

## 문제 해결
- 실패 시 `logs/` 에 스크린샷이 저장됩니다. 셀렉터는 `naver_blog.py` 의 `SEL` 에서 수정.
- `프로필 시작 실패`: Dolphin 앱이 켜져 있는지, 토큰/프로필ID가 맞는지 확인.
- `로그아웃 상태`: `--login-only` 로 다시 로그인.

## 보안
`config.yaml` 에 API 토큰이 있으므로 공유/업로드하지 마세요 (`.gitignore` 에 포함됨).

## 본문 중간 이미지
본문 txt 에서 이미지를 넣을 위치에 한 줄로 [[image:파일경로]] 를 쓴다. 여러 장은 [[image:a.jpg|b.jpg]].
경로는 본문 파일이 있는 폴더 기준(없으면 프로젝트 루트 기준) 상대경로 또는 절대경로.
