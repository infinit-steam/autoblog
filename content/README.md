# content/ 관리 규칙

**주제 하나 = 폴더 하나.** 한 주제의 글(플랫폼별)과 이미지·영상을 모두 이 안에 둔다.

```
content/
  <주제>/
    topic.md              주제 메모 (핵심 내용, 키워드, 말투, 분량, 사진 설명)
    media/                이미지·영상 원본 (모든 플랫폼 공용)
      01.jpg 02.jpg ...   파일명 순서 = 사진 순서
      clip.mp4
    naver/post.txt        네이버 블로그 본문
    instagram/caption.txt 인스타 캡션
    youtube/…  facebook/… (추가 예정)
```

## 규칙
- 주제 이름: 알아볼 수 있는 이름. `\ / : * ? " < > |` 불가, `_` 로 시작 불가. 한글 가능.
- 이미지: jpg/png/webp. 영상: mp4/mov. 파일명은 `01.jpg` 처럼 번호를 붙이면 순서가 보장된다.
- 영상(mp4/mov)은 git 에 올라가지 않는다 (`.gitignore`). 글·이미지는 올라간다.
- `<<작성 필요>>` 가 남은 글은 대기열에 등록되지 않는다.

## 플랫폼별 작성법
**네이버 `naver/post.txt`** — 본문. 사진 위치에 한 줄로
`[[image:../media/01.jpg]]` (여러 장: `[[image:../media/01.jpg|../media/02.jpg]]`).
제목은 파일에 쓰지 않고 `queue.csv` 의 `title` (등록 시 `--title`).

**인스타 `instagram/caption.txt`** — 캡션만. 2200자 이하, 해시태그 30개 이하.
이미지는 `media/` 의 이미지 전부(이름순, 최대 10장). 릴스는 `--reel` 로 `media/` 의 동영상 1개.

## 작업 순서
```
python tools/new_topic.py 제주여행                       # 골격 생성
(media/ 에 파일 넣기, topic.md 작성, 각 글 작성)
python tools/enqueue.py 제주여행 --account acc1 --title "제목"   # 대기열 등록
python main.py --dry-run                                  # 확인
```
인스타 릴스: `python tools/enqueue.py 제주여행 --account acc1 --platforms instagram --reel`
