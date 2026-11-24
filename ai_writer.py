"""AI 글 생성 (Claude API). GUI/CLI 공용, 화면 없음.

주제·프롬프트·말투·분량·키워드(+선택적으로 사진)를 보내 제목 / 네이버 본문 / 인스타 캡션을 JSON 으로 받는다.
설정: config.yaml 의 `ai:` 섹션 (api_key 또는 환경변수 ANTHROPIC_API_KEY).
"""
import base64
import io
import json
import os
import re
from pathlib import Path

import yaml

import topics
from common import IMAGE_EXT, VIDEO_EXT

ROOT = Path(__file__).resolve().parent
TONES_PATH = ROOT / "tone_presets.json"
DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"  # 정책 거절 시 서버가 자동으로 다른 모델로 재시도
IG_CAPTION_MAX, IG_HASHTAG_MAX = 2200, 30
THREADS_MAX, THREADS_HASHTAG_MAX = 500, 1  # 스레드: 글자 수 제한, 주제 태그는 게시물당 1개로 알려져 있음
MARKER_RE = re.compile(r"^\s*\[\[image:(.+?)\]\]\s*$", re.M)

DEFAULT_TONES = [
    {"name": "친근한 후기체", "instruction": "직접 써 본 사람이 이웃에게 이야기하듯 편하고 따뜻한 말투(~했어요, ~더라고요). 과장 없이 솔직하게, 장단점을 함께."},
    {"name": "정보 전달체", "instruction": "독자가 궁금해하는 정보를 소제목과 짧은 문단으로 정리. 단정적이고 간결한 존댓말(~합니다). 감탄사·이모지 최소."},
    {"name": "전문가 설명체", "instruction": "해당 분야를 잘 아는 사람이 차분히 설명하는 말투. 근거와 이유를 들되 어려운 용어는 풀어서."},
    {"name": "감성 에세이체", "instruction": "장면과 감정을 묘사하는 담백한 문장. 짧은 문단, 여운 있는 마무리."},
    {"name": "간결한 홍보체", "instruction": "핵심 혜택을 먼저, 짧고 힘 있는 문장. 과장·허위·최상급 남발 금지."},
]

SYSTEM = """당신은 한국어 블로그(네이버)와 인스타그램 콘텐츠를 쓰는 카피라이터입니다.

가장 중요한 규칙 - 사실 원칙:
1. 글에 쓰는 모든 구체적 서술은 (a) 사용자의 요청·주제 메모에 있거나 (b) 첨부 사진에서 직접 보이는 것이어야 합니다. 입력에 없는 것은 쓰지 않고 '생략'합니다. 모르는 것을 '일반적인 표현'으로 얼버무려 쓰는 것도 금지입니다.
2. 입력에 없으면 쓰지 말아야 할 것의 예: 맛·식감·향·온도, 가격·할인, 주차·위치·영업시간, 방문 요일·시간대·날씨·동행, 혼잡도·대기·예약 여부, 직원·서비스 평가, 제품의 재질·무게·크기·성능·수치, 장단점, 효능.
   "주말엔 붐벼요", "예약하고 가세요", "가볍고 휴대하기 좋아요", "촉촉하고 달지 않아요"처럼 일반론처럼 들려도 입력에 없으면 사실 주장이므로 쓰지 않습니다.
3. 1인칭 경험("먹어 봤어요", "앉았어요")은 사용자가 말한 경험만 씁니다. 감상과 분위기도 입력에서 나온 것만 씁니다.
4. 정보가 부족하면 분량을 채우려 하지 마세요. 분량은 '최대'입니다. 지어내서 늘린 긴 글보다 사실만 담은 짧은 글이 낫습니다. 짧게 쓴 경우 notes 에 어떤 정보를 더 주면 풍부해지는지 적습니다.
5. 위 원칙을 지키지 못하고 입력에 없는 구체적 서술을 썼다면, 그 문장을 unverified 배열에 그대로 모두 적습니다. 모두 지켰다면 빈 배열입니다.

그 밖의 규칙:
- 의학적 효능, 수익 보장, 최고/1위 같은 검증 불가한 주장은 쓰지 않습니다.
- 사진 속 사람의 신원을 추측하지 않습니다. 사진에 보이는 내용만 묘사합니다.
- 글은 직접 쓴 것처럼 자연스럽게, 같은 문장 구조를 반복하지 않습니다. 상투적인 AI 문투(예: "~에 대해 알아보겠습니다", "결론적으로")는 피합니다.
- title 은 네이버 글 제목입니다 (40자 안팎, 클릭을 유도하되 과장 금지).
- naver_body: 본문만 씁니다 (제목 제외). 문단은 빈 줄로 구분하고 마크다운 문법은 쓰지 않습니다. 첨부 사진이 있으면 내용에 맞는 위치에 한 줄로 [[image:../media/파일명]] 을 넣습니다. 파일명은 아래 '사용 가능한 파일'에 있는 것만, 한 번씩만 씁니다.
- instagram_caption: 첫 줄에 시선을 끄는 문장, 이어서 본문, 마지막에 관련 해시태그(최대 10개). 이미지 마커는 넣지 않습니다.
- threads_post: 스레드에 올릴 글입니다. 반드시 500자 이하(해시태그 포함). 인스타 캡션을 줄인 것이 아니라 스레드에 맞는 대화체 글로 새로 씁니다. 첫 문장으로 시선을 끌고 짧은 문단으로 나눕니다. 해시태그는 많아야 1개(없어도 됨)이고 이모지는 최소화합니다. 이미지 마커는 넣지 않습니다.
- 요청되지 않은 플랫폼의 필드는 빈 문자열로 둡니다.
- notes: 사용자에게 알릴 짧은 메모(예: 사진이 흐려 제외한 것, 확인이 필요한 사실). 없으면 빈 문자열."""

SYSTEM_STRICT = SYSTEM
_TAIL = SYSTEM[SYSTEM.index("그 밖의 규칙:"):]
SYSTEM_PREDICT = """당신은 한국어 블로그(네이버)와 인스타그램 콘텐츠를 쓰는 카피라이터입니다.

작성 방식 - 추정 허용(분량 맞춤):
1. 사용자가 준 정보를 뼈대로 삼아, 그 주제의 글에 자연스럽게 들어갈 만한 내용을 상상해서 보충합니다. 예: 분위기와 감각적 묘사, 그 정보가 독자에게 주는 의미, 이용 팁, 장점과 아쉬운 점, 어울리는 사람이나 상황, 소감, 마무리 권유. 정보가 적어도 요청한 분량을 채웁니다.
2. 분량은 목표치입니다. 네이버 본문은 요청한 글자 수의 90~110%로 씁니다. 지나치게 짧게 쓰지 마세요. 문단 수와 소제목 없이 자연스러운 흐름으로 늘립니다.
3. 보충한 내용은 사용자가 말한 사실과 모순되면 안 되고, 사용자가 겪은 일처럼 쓰는 1인칭 경험도 입력과 어긋나지 않는 선에서만 씁니다.
4. 입력에 없으면 절대 쓰지 않는 것: 구체적 숫자(가격·할인율·시간·거리·용량·인원·평점), 상호·주소·전화번호·URL, 날짜·요일, 효능·의학·안전에 관한 주장, 최고·1위·유일 같은 최상급 주장, 다른 업체와의 비교나 비방.
5. 입력에 없는 내용을 추정해서 쓴 문장은 빠짐없이 unverified 배열에 문장 그대로 적습니다 (사용자가 실제와 맞는지 확인합니다). 입력을 그대로 옮긴 문장은 적지 않습니다.

""" + _TAIL

MODES = {
    "predict": {"label": "추정 허용 (분량 맞춤)", "system": SYSTEM_PREDICT},
    "strict": {"label": "사실만 (엄격)", "system": SYSTEM_STRICT},
}
DEFAULT_MODE = "predict"

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "naver_body": {"type": "string"},
        "instagram_caption": {"type": "string"},
        "threads_post": {"type": "string"},
        "notes": {"type": "string"},
        "unverified": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "naver_body", "instagram_caption", "threads_post", "notes", "unverified"],
    "additionalProperties": False,
}


class AIError(Exception):
    """사용자에게 그대로 보여줄 수 있는 한국어 오류."""


# ---------------------------------------------------------------- 설정 / 프리셋
def load_ai_config() -> dict:
    try:
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    except OSError:
        cfg = {}
    ai = cfg.get("ai") or {}
    model = ai.get("model") or DEFAULT_MODEL
    return {
        "api_key": (ai.get("api_key") or os.environ.get("ANTHROPIC_API_KEY") or "").strip(),
        "model": model,
        "effort": ai.get("effort") or "medium",
        "max_images": int(ai.get("max_images") or 6),
        # Haiku 5.5 는 서버 측 거절 폴백을 지원하지 않는다 → 자동으로 끈다
        "use_fallback": bool(ai.get("use_fallback", True)) and "haiku" not in str(model).lower(),
    }


def load_tones() -> list[dict]:
    try:
        data = json.loads(TONES_PATH.read_text(encoding="utf-8"))
        tones = [t for t in data if t.get("name") and t.get("instruction")]
        if tones:
            return tones
    except (OSError, ValueError):
        pass
    return [dict(t) for t in DEFAULT_TONES]


def save_tones(tones: list[dict]):
    TONES_PATH.write_text(json.dumps(tones, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 요청 만들기
def encode_image(path: Path, max_side: int = 1280) -> tuple[str, str]:
    """긴 변 max_side 로 줄여 JPEG base64 로. 전송량과 비용을 줄인다."""
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(path))
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=85)
    return "image/jpeg", base64.standard_b64encode(buf.getvalue()).decode("ascii")


def build_content(topic: str, prompt: str, tone: dict, platforms, naver_chars: int, ig_chars: int,
                  keywords: str, use_images: bool, max_images: int, mode: str = DEFAULT_MODE,
                  threads_chars: int = 300) -> tuple[list[dict], list[str], list[str]]:
    """user 메시지 content 블록, 사진으로 보낸 파일명, 알림 메모를 돌려준다."""
    files = topics.media_files(topic)
    imgs = [f for f in files if f.suffix.lower() in IMAGE_EXT]
    vids = [f for f in files if f.suffix.lower() in VIDEO_EXT]
    sent = imgs[:max_images] if use_images else []
    notes = []
    if use_images and len(imgs) > max_images:
        notes.append(f"이미지 {len(imgs)}장 중 앞의 {max_images}장만 AI에게 보냈습니다 (설정 ai.max_images)")
    plat_names = [topics.PLATFORMS[p]["label"] for p in platforms]
    memo = topics.read_memo(topic).strip()

    lines = [f"# 요청\n{prompt.strip()}", "",
             "# 조건",
             f"- 작성할 플랫폼: {', '.join(plat_names)}",
             f"- 말투({tone['name']}): {tone['instruction']}"]
    if "naver" in platforms:
        lines.append(
            f"- 네이버 본문 분량: 공백 포함 {int(naver_chars * 0.9)}~{int(naver_chars * 1.1)}자 (목표 {naver_chars}자)"
            if mode == "predict" else
            f"- 네이버 본문 분량: 공백 포함 최대 약 {naver_chars}자 (정보가 부족하면 이보다 짧아도 됨. 지어내서 채우지 말 것)")
    if "instagram" in platforms:
        lines.append(
            f"- 인스타 캡션 분량: 해시태그 제외 약 {ig_chars}자 (±20%)" if mode == "predict" else
            f"- 인스타 캡션 분량: 해시태그 제외 최대 약 {ig_chars}자 (정보가 부족하면 더 짧아도 됨)")
    if "threads" in platforms:
        cap = min(threads_chars, THREADS_MAX)
        lines.append(
            f"- 스레드 글 분량: 해시태그 포함 약 {cap}자 (±20%, 반드시 {THREADS_MAX}자 이하)" if mode == "predict" else
            f"- 스레드 글 분량: 해시태그 포함 최대 약 {cap}자 (정보가 부족하면 더 짧아도 됨, 반드시 {THREADS_MAX}자 이하)")
    if keywords.strip():
        lines.append(f"- 자연스럽게 넣을 키워드: {keywords.strip()}")
    if memo:
        lines += ["", f"# 주제 메모\n{memo}"]
    lines += ["", "# 사용 가능한 파일 (media/)"]
    if sent:
        lines.append("이미지(아래에 첨부): " + ", ".join(f.name for f in sent))
    elif imgs:
        lines.append("이미지(내용은 보지 못함, 마커로 배치하지 말 것): " + ", ".join(f.name for f in imgs))
    else:
        lines.append("이미지 없음")
    if vids:
        lines.append("영상(내용 미확인): " + ", ".join(f.name for f in vids))

    content: list[dict] = [{"type": "text", "text": "\n".join(lines)}]
    for f in sent:
        media_type, data = encode_image(f)
        content.append({"type": "text", "text": f"[이미지 파일명: {f.name}]"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
    return content, [f.name for f in sent], notes


# ---------------------------------------------------------------- 결과 검증/보정
def normalize_result(result: dict, platforms, image_names: list[str],
                     mode: str = DEFAULT_MODE) -> tuple[dict, list[str], list[str]]:
    """결과를 보정하고 (결과, 재생성이 필요한 문제들, 사용자 알림)을 돌려준다."""
    r = {k: (result.get(k) or "").strip() for k in ("title", "naver_body", "instagram_caption", "threads_post", "notes")}
    r["unverified"] = [s.strip() for s in (result.get("unverified") or []) if str(s).strip()]
    label = ("AI가 추정해 쓴 문장 — 실제와 맞는지 확인하세요" if mode == "predict"
             else "입력에 없던 서술(AI 자체 신고) — 사실인지 확인하세요")
    problems, warns = [], [f"{label}: {s}" for s in r["unverified"]]
    if "naver" not in platforms:
        r["naver_body"] = ""
    if "instagram" not in platforms:
        r["instagram_caption"] = ""
    if "threads" not in platforms:
        r["threads_post"] = ""

    if r["naver_body"]:
        known = set(image_names)

        def fix(m):
            name = Path(m.group(1).strip().replace("\\", "/")).name
            if name in known:
                return f"[[image:../media/{name}]]"
            warns.append(f"본문에 없는 이미지 마커를 제거했습니다: {m.group(1).strip()}")
            return ""
        r["naver_body"] = re.sub(r"\n{3,}", "\n\n", MARKER_RE.sub(fix, r["naver_body"])).strip()
        if not r["title"]:
            problems.append("title 이 비어 있습니다")
    if "naver" in platforms and not r["naver_body"]:
        problems.append("naver_body 가 비어 있습니다")

    if "instagram" in platforms:
        cap = r["instagram_caption"]
        if not cap:
            problems.append("instagram_caption 이 비어 있습니다")
        if len(cap) > IG_CAPTION_MAX:
            problems.append(f"instagram_caption 이 {len(cap)}자로 {IG_CAPTION_MAX}자를 넘습니다")
        tags = len(re.findall(r"#\w+", cap))
        if tags > IG_HASHTAG_MAX:
            problems.append(f"해시태그가 {tags}개로 {IG_HASHTAG_MAX}개를 넘습니다")

    if "threads" in platforms:
        th = r["threads_post"]
        th = re.sub(r"\[\[image:.*?\]\]", "", th).strip()  # 스레드 글에는 이미지 마커가 필요 없다
        r["threads_post"] = th
        if not th:
            problems.append("threads_post 가 비어 있습니다")
        if len(th) > THREADS_MAX:
            problems.append(f"threads_post 가 {len(th)}자로 {THREADS_MAX}자를 넘습니다. {THREADS_MAX}자 이하로 줄이세요")
        tags = len(re.findall(r"#\w+", th))
        if tags > THREADS_HASHTAG_MAX:
            problems.append(f"threads_post 의 해시태그가 {tags}개입니다. {THREADS_HASHTAG_MAX}개 이하로 줄이세요")
    return r, problems, warns


# ---------------------------------------------------------------- 호출
def make_client(ai_cfg: dict):
    if not ai_cfg["api_key"]:
        raise AIError("API 키가 없습니다. config.yaml 의 ai.api_key 에 넣거나 환경변수 ANTHROPIC_API_KEY 를 설정하세요.")
    import anthropic
    return anthropic.Anthropic(api_key=ai_cfg["api_key"], timeout=240.0)


def _call(client, ai_cfg: dict, messages: list[dict], use_fallback: bool, system: str = SYSTEM_PREDICT):
    kwargs = dict(
        model=ai_cfg["model"], max_tokens=16000, system=system, messages=messages,
        output_config={"effort": ai_cfg["effort"], "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    if use_fallback:  # 정책 거절 시 같은 요청을 서버가 다른 모델로 재시도 (실패 시 refusal 로 끝남)
        kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")
    return client.beta.messages.create(**kwargs)


def _friendly(e: Exception) -> AIError:
    import anthropic
    if isinstance(e, anthropic.AuthenticationError):
        return AIError("API 키가 올바르지 않습니다. config.yaml 의 ai.api_key 를 확인하세요.")
    if isinstance(e, anthropic.PermissionDeniedError):
        return AIError("이 API 키로는 해당 모델/기능을 쓸 수 없습니다.")
    if isinstance(e, anthropic.RateLimitError):
        return AIError("요청이 너무 많습니다. 잠시 후 다시 시도하세요.")
    if isinstance(e, anthropic.APIConnectionError):
        return AIError("네트워크 오류입니다. 인터넷 연결을 확인하세요.")
    if isinstance(e, anthropic.APIStatusError):
        return AIError(f"API 오류({e.status_code}): {getattr(e, 'message', e)}")
    return AIError(f"{type(e).__name__}: {e}")


def length_problems(r: dict, platforms, naver_chars: int, ig_chars: int, threads_chars: int = 300) -> list[str]:
    """추정 허용 모드에서 분량이 목표에서 크게 벗어나면 재작성을 요청할 문제 목록."""
    out = []
    if "threads" in platforms and r["threads_post"] and threads_chars:
        n, goal = len(r["threads_post"]), min(threads_chars, THREADS_MAX)
        if n < goal * 0.6:
            out.append(f"threads_post 가 {n}자로 목표 {goal}자보다 많이 짧습니다. 보충해서 늘리세요 (최대 {THREADS_MAX}자)")
    if "naver" in platforms and r["naver_body"] and naver_chars:
        n = len(r["naver_body"])
        if n < naver_chars * 0.8:
            out.append(f"naver_body 가 {n}자로 목표 {naver_chars}자보다 많이 짧습니다. 보충해서 {int(naver_chars * 0.9)}~{int(naver_chars * 1.1)}자로 늘리세요")
        elif n > naver_chars * 1.25:
            out.append(f"naver_body 가 {n}자로 목표 {naver_chars}자보다 많이 깁니다. {int(naver_chars * 0.9)}~{int(naver_chars * 1.1)}자로 줄이세요")
    if "instagram" in platforms and r["instagram_caption"] and ig_chars:
        n = len(re.sub(r"#\w+", "", r["instagram_caption"]).strip())
        if n < ig_chars * 0.6:
            out.append(f"instagram_caption 본문이 해시태그 제외 {n}자로 목표 {ig_chars}자보다 많이 짧습니다. 보충하세요")
        elif n > ig_chars * 1.5:
            out.append(f"instagram_caption 본문이 해시태그 제외 {n}자로 목표 {ig_chars}자보다 많이 깁니다. 줄이세요")
    return out


def generate(topic: str, prompt: str, tone: dict, platforms, naver_chars: int = 1500, ig_chars: int = 300,
             keywords: str = "", use_images: bool = True, client=None, ai_cfg: dict | None = None,
             mode: str = DEFAULT_MODE, threads_chars: int = 300) -> dict:
    """결과: {title, naver_body, instagram_caption, notes, unverified, warnings, usage, model}. 실패 시 AIError."""
    import anthropic
    if not prompt.strip():
        raise AIError("주제/프롬프트를 입력하세요.")
    if not platforms:
        raise AIError("작성할 플랫폼을 하나 이상 선택하세요.")
    if mode not in MODES:
        raise AIError(f"알 수 없는 작성 방식: {mode}")
    system = MODES[mode]["system"]
    ai_cfg = ai_cfg or load_ai_config()
    client = client or make_client(ai_cfg)

    content, image_names, warnings = build_content(
        topic, prompt, tone, platforms, naver_chars, ig_chars, keywords, use_images, ai_cfg["max_images"], mode,
        threads_chars)
    messages = [{"role": "user", "content": content}]
    use_fallback = bool(ai_cfg.get("use_fallback", True))
    usage = {"input": 0, "output": 0}

    for attempt in range(2):
        try:
            try:
                resp = _call(client, ai_cfg, messages, use_fallback, system)
            except anthropic.BadRequestError as e:
                if use_fallback and "fallback" in str(e).lower():
                    use_fallback = False  # 이 계정/환경이 폴백 파라미터를 거부하면 끄고 재시도
                    resp = _call(client, ai_cfg, messages, False, system)
                    warnings.append("자동 폴백을 지원하지 않아 끄고 실행했습니다")
                else:
                    raise
        except AIError:
            raise
        except Exception as e:
            raise _friendly(e) from e

        usage["input"] += getattr(resp.usage, "input_tokens", 0) or 0
        usage["output"] += getattr(resp.usage, "output_tokens", 0) or 0
        if resp.stop_reason == "refusal":
            cat = getattr(getattr(resp, "stop_details", None), "category", None)
            raise AIError(f"AI가 이 요청에 대한 작성을 거절했습니다{f' ({cat})' if cat else ''}. 주제나 표현을 바꿔 보세요.")
        if resp.stop_reason == "max_tokens":
            raise AIError("응답이 길이 제한에서 잘렸습니다. 분량을 줄여 다시 시도하세요.")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except ValueError as e:
            raise AIError("AI 응답을 해석하지 못했습니다. 다시 시도하세요.") from e

        result, problems, warns = normalize_result(data, platforms, image_names, mode)
        if mode == "predict":
            problems += length_problems(result, platforms, naver_chars, ig_chars, threads_chars)
        if not problems or attempt == 1:
            warnings += warns  # 마지막 시도의 경고만 사용 (재시도 전 결과의 경고는 버림)
            if problems:
                warnings += [f"확인 필요: {p}" for p in problems]
            result["warnings"] = warnings
            result["usage"] = usage
            result["model"] = getattr(resp, "model", ai_cfg["model"])
            return result
        # 한 번만 자동 수정 요청 (같은 대화에 이어서)
        messages = messages + [
            {"role": "assistant", "content": resp.content},
            {"role": "user", "content": "다음 문제를 고쳐서 같은 형식으로 다시 작성하세요: " + "; ".join(problems)},
        ]
    raise AIError("생성에 실패했습니다.")  # 도달하지 않음
